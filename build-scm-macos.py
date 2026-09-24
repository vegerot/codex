#!/usr/bin/env python3
"""Cross-build an Apple Silicon Codex package on a Linux SCM worker."""

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import zipfile
from urllib.request import urlopen
import shutil

from build import RELEASE_ENV, REPO_ROOT, scm_memory_status
from scripts.codex_package.layout import build_package_dir
from scripts.codex_package.nightly_version import stamp_workspace
from scripts.codex_package.ripgrep import resolve_rg_bin
from scripts.codex_package.targets import PACKAGE_VARIANTS, TARGET_SPECS, PackageInputs
from scripts.codex_package.v8 import resolve_codex_v8_cargo_env
from scripts.codex_package.zsh import resolve_zsh_bin


def run(args, **kwargs):
    print("+", " ".join(map(str, args)), flush=True)
    return subprocess.run(args, check=True, **kwargs)


def fetch(cache, url, digest):
    archive = cache / url.rsplit("/", 1)[1]
    if not archive.exists():
        print(f"Downloading {url}", flush=True)
        temporary = archive.with_suffix(".download")
        with urlopen(url, timeout=60) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        temporary.replace(archive)
    with archive.open("rb") as src:
        assert hashlib.file_digest(src, "sha256").hexdigest() == digest, archive
    if archive.suffix == ".whl":
        with zipfile.ZipFile(archive) as wheel:
            wheel.extractall(cache)
        (cache / "ziglang/zig").chmod(0o755)
    else:
        run(["tar", "-xJf", str(archive), "-C", str(cache)])


def main():
    started = time.monotonic()
    cache = (
        Path(os.environ.get("CARGO_HOME", str(Path.home() / ".cargo")))
        / "codex-macos-zig"
    )
    cache.mkdir(parents=True, exist_ok=True)
    fetch(
        cache,
        "https://bytedpypi.byted.org/packages/ziglang/ziglang-0.16.0-py3-none-manylinux_2_12_x86_64.manylinux2010_x86_64.musllinux_1_1_x86_64.whl",
        "9fcda73f62b851dd72a54b710ad40a209896db14cfb13649e62191243556342b",
    )
    fetch(
        cache,
        "https://github.com/rust-cross/cargo-zigbuild/releases/download/v0.23.4/cargo-zigbuild-x86_64-unknown-linux-musl.tar.xz",
        "9e3cf73485edbd45905c8aadbc0fdf869c7ddc3848f0c898229f2680db52e44b",
    )
    fetch(
        cache,
        "https://github.com/joseluisq/macosx-sdks/releases/download/15.5/MacOSX15.5.sdk.tar.xz",
        "c15cf0f3f17d714d1aa5a642da8e118db53d79429eb015771ba816aa7c6c1cbd",
    )
    zigbuild = next(cache.rglob("cargo-zigbuild"))
    assert zigbuild.is_file(), zigbuild
    spec = TARGET_SPECS["aarch64-apple-darwin"]
    toolchain = os.environ["CODEX_TOOLCHAIN"]
    run(["rustup", "target", "add", "--toolchain", toolchain, spec.target])
    env = {
        **os.environ,
        **RELEASE_ENV,
        "PATH": f"{zigbuild.parent}:{cache / 'ziglang'}:{os.environ['PATH']}",
        "SDKROOT": str(cache / "MacOSX15.5.sdk"),
        "MACOSX_DEPLOYMENT_TARGET": "14.0",
        "CARGO_TARGET_DIR": str(cache / "target"),
        "CARGO_BUILD_JOBS": "24",
        "CARGO_ZIGBUILD_CACHE_DIR": str(cache / "wrappers"),
        "ZIG_GLOBAL_CACHE_DIR": str(cache / "zig-cache"),
        "CARGO_NET_GIT_FETCH_WITH_CLI": "true",
        "RUSTFLAGS": "-C force-frame-pointers=yes",
    }
    # The SCM image injects Linux CPU flags; never use those for the Mac target.
    for name in (
        "CARGO_ENCODED_RUSTFLAGS",
        "CFLAGS",
        "CXXFLAGS",
        "CPPFLAGS",
        "LDFLAGS",
    ):
        env.pop(name, None)
    run(["zig", "version"], env=env)
    probe = cache / "probe"
    (probe / "src").mkdir(parents=True, exist_ok=True)
    (probe / "Cargo.toml").write_text(
        '[package]\nname="macos-link-probe"\nversion="0.1.0"\nedition="2021"\n'
    )
    (probe / "src/main.rs").write_text("""#[link(name = "Security", kind = "framework")]
extern "C" { fn SecRandomCopyBytes(rnd: *const u8, count: usize, bytes: *mut u8) -> i32; }
fn main() {
    let mut bytes = [0u8; 16];
    assert_eq!(unsafe { SecRandomCopyBytes(std::ptr::null(), bytes.len(), bytes.as_mut_ptr()) }, 0);
    println!("macOS cross-build: Rust std and Security framework OK");
}
""")
    run(
        ["cargo", f"+{toolchain}", "zigbuild", "--release", "--target", spec.target],
        cwd=probe,
        env=env,
    )
    run(["file", str(cache / "target" / spec.target / "release/macos-link-probe")])
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    # Resolve the stable version on the submitting Mac, before freezing build inputs.
    base_version = os.environ["CUSTOM_CODEX_BASE_VERSION"]
    version = {
        "version": stamp_workspace(REPO_ROOT / "codex-rs", base_version, commit),
        "upstream_release_tag": f"rust-v{base_version}",
    }
    env.update(resolve_codex_v8_cargo_env(spec, cache_root=cache / "v8"))
    command = [
        "cargo",
        f"+{toolchain}",
        "zigbuild",
        "--locked",
        "--release",
        "--target",
        spec.target,
        "--bin",
        "codex",
        "--bin",
        "codex-code-mode-host",
        "--timings",
    ]
    print("+", " ".join(command), flush=True)
    build_started = time.monotonic()
    process = subprocess.Popen(
        command, cwd=REPO_ROOT / "codex-rs", env=env, start_new_session=True
    )
    minimum = scm_memory_status()[1]
    last_report = 0
    try:
        while process.poll() is None:
            available = scm_memory_status()[1]
            minimum = min(minimum, available)
            if available < 1024**3:
                raise RuntimeError(
                    "Less than 1 GiB available; stopping experimental build"
                )
            if time.monotonic() - last_report >= 30:
                print(
                    f"Cross-build heartbeat: available={available / 1024**3:.2f} GiB",
                    flush=True,
                )
                last_report = time.monotonic()
            time.sleep(1)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait()
    compile_seconds = round(time.monotonic() - build_started, 2)
    bins = cache / "target" / spec.target / "release"
    output = REPO_ROOT / "output"
    output.mkdir(exist_ok=True)
    build_package_dir(
        output,
        version["version"],
        PACKAGE_VARIANTS["codex"],
        spec,
        PackageInputs(
            entrypoint_bin=bins / "codex",
            code_mode_host_bin=bins / "codex-code-mode-host",
            rg_bin=resolve_rg_bin(spec, None),
            zsh_bin=resolve_zsh_bin(spec),
            bwrap_bin=None,
            codex_command_runner_bin=None,
            codex_windows_sandbox_setup_bin=None,
        ),
    )
    for name in ("LICENSE", "NOTICE"):
        (output / name).write_bytes((REPO_ROOT / name).read_bytes())
    (output / "macos-link-probe").write_bytes((bins / "macos-link-probe").read_bytes())
    (output / "macos-link-probe").chmod(0o755)
    metadata = {
        "commit": commit,
        **version,
        "target": spec.target,
        "build_host": os.uname().sysname,
        "zig": "0.16.0",
        "cargo_zigbuild": "0.23.4",
        "sdk": "15.5",
        "deployment_target": "14.0",
        "compile_seconds": compile_seconds,
        "total_seconds": round(time.monotonic() - started, 2),
        "minimum_available_gib": round(minimum / 1024**3, 3),
    }
    (output / "build-info.json").write_text(json.dumps(metadata, indent=2) + "\n")
    sums = []
    for binary in sorted(p for p in output.rglob("*") if p.is_file()):
        with binary.open("rb") as src:
            sums.append(
                f"{hashlib.file_digest(src, 'sha256').hexdigest()}  {binary.relative_to(output)}\n"
            )
    (output / "SHA256SUMS").write_text("".join(sums))
    run(["file", str(output / "bin/codex"), str(output / "bin/codex-code-mode-host")])
    print(json.dumps(metadata), flush=True)


if __name__ == "__main__":
    main()
