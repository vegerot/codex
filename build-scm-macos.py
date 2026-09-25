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
import sys

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
    zigbuild = next(p for p in cache.rglob("cargo-zigbuild") if p.is_file())
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
    archive = REPO_ROOT / "voice-experiment-sdk.tar.gz"
    assert (
        hashlib.sha256(archive.read_bytes()).hexdigest()
        == "e16b158a2c5fdedb2cb448ce9791c2aad1ba118ca9a35a93a19b8a83f3159855"
    )
    inputs = cache / "voice-experiment-inputs"
    inputs.mkdir(exist_ok=True)
    run(["tar", "-xzf", str(archive), "-C", str(inputs)])
    wrapper = cache / "voice-pkg-config"
    wrapper.write_text('#!/bin/sh\nexec /usr/bin/pkg-config --define-prefix "$@"\n')
    wrapper.chmod(0o755)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    env.update(
        {
            "PKG_CONFIG": str(wrapper),
            "PKG_CONFIG_ALLOW_CROSS": "1",
            "PKG_CONFIG_SYSROOT_DIR": "/",
            "PKG_CONFIG_LIBDIR": str(inputs / "sdk/lib/pkgconfig"),
            "PKG_CONFIG_PATH": "",
            "STABLE_GIT_COMMIT": commit,
            "RUSTFLAGS": "-C force-frame-pointers=yes -C link-arg=-Wl,-rpath,@executable_path/../lib",
        }
    )
    base = os.environ["CUSTOM_CODEX_BASE_VERSION"]
    stamped = stamp_workspace(REPO_ROOT / "codex-rs", base, commit)
    # Upstream private voice assembly expects the full commit as build metadata.
    version = f"{base}+{commit}"
    for name in ("Cargo.toml", "Cargo.lock"):
        path = REPO_ROOT / "codex-rs" / name
        path.write_text(path.read_text().replace(stamped, version))
    env.update(resolve_codex_v8_cargo_env(spec, cache_root=cache / "v8"))
    begin = time.monotonic()
    run(
        [
            "cargo",
            f"+{toolchain}",
            "zigbuild",
            "--locked",
            "--release",
            "--target",
            spec.target,
            "--bin",
            "codex-voice-host",
            "--bin",
            "codex",
            "--bin",
            "codex-code-mode-host",
        ],
        cwd=REPO_ROOT / "codex-rs",
        env=env,
    )
    bins = cache / "target" / spec.target / "release"
    package = REPO_ROOT / "voice-base-package"
    package.mkdir()
    build_package_dir(
        package,
        version,
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
    sys.path.insert(0, str(REPO_ROOT / "third_party/voice"))
    from assemble_package import assemble

    output = REPO_ROOT / "output"
    assemble(
        package,
        bins / "codex-voice-host",
        spec.target,
        commit,
        output,
        runtime=inputs / "runtime",
    )
    (output / "build-info.json").write_text(
        json.dumps(
            {
                "commit": commit,
                "target": spec.target,
                "version": version,
                "compile_seconds": round(time.monotonic() - begin, 2),
                "total_seconds": round(time.monotonic() - started, 2),
            },
            indent=2,
        )
        + "\n"
    )
    print((output / "build-info.json").read_text(), flush=True)


if __name__ == "__main__":
    main()
