#!/usr/bin/env python3
"""Build and install this desktop's Codex fork; scheduling and updates stay in Codex."""

import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib

REPO = Path(__file__).resolve().parents[2]
CACHE = Path.home() / ".cache/codex-desktop-build"
STATE = Path.home() / ".local/state/codex-desktop-build"
PACKAGES = Path.home() / ".local/share/codex-desktop-build/packages"
GIB = 1024**3


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def main():
    os.environ["PATH"] = (
        str(Path.home() / ".cargo/bin") + os.pathsep + os.environ["PATH"]
    )
    started = time.monotonic()
    CACHE.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    PACKAGES.mkdir(parents=True, exist_ok=True)
    lock = (STATE / "build.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    commit = os.environ["CODEX_FROZEN_SOURCE"]
    run_dir = Path(os.environ["CODEX_NIGHTLY_RUN_DIR"])
    if shutil.disk_usage(CACHE).free < 15 * GIB:
        raise RuntimeError("Build requires at least 15 GiB free; no automatic cleanup")
    memory = dict(
        line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()
    )
    available = int(memory["MemAvailable"].split()[0]) * 1024
    # The 5900X has 24 threads; reserve RAM for the desktop and large Rust crates.
    jobs = min(16, len(os.sched_getaffinity(0)), int((available / GIB - 6) / 1.5))
    if jobs < 1:
        raise RuntimeError("Insufficient available memory for a desktop build")
    source = REPO
    sys.path.insert(0, str(source))
    from scripts.codex_package.nightly_version import stamp_nightly_version

    version = stamp_nightly_version(source, commit)
    from scripts.codex_package.layout import build_package_dir
    from scripts.codex_package.ripgrep import resolve_rg_bin
    from scripts.codex_package.targets import (
        PACKAGE_VARIANTS,
        TARGET_SPECS,
        PackageInputs,
    )
    from scripts.codex_package.v8 import resolve_codex_v8_cargo_env

    spec = TARGET_SPECS["x86_64-unknown-linux-gnu"]
    toolchain = tomllib.loads((source / "codex-rs/rust-toolchain.toml").read_text())[
        "toolchain"
    ]["channel"]
    target = CACHE / "target"
    env = {
        **os.environ,
        "CARGO_TARGET_DIR": str(target),
        "CARGO_BUILD_JOBS": str(jobs),
        "CARGO_PROFILE_RELEASE_LTO": "off",
        "CARGO_PROFILE_RELEASE_CODEGEN_UNITS": "16",
        "CARGO_PROFILE_RELEASE_INCREMENTAL": "false",
        "CARGO_PROFILE_RELEASE_DEBUG": "0",
        "CARGO_NET_GIT_FETCH_WITH_CLI": "true",
        "CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER": "clang",
        "RUSTFLAGS": "-C link-arg=-fuse-ld=lld-19",
        **resolve_codex_v8_cargo_env(spec, cache_root=CACHE / "v8"),
    }
    print(
        f"Desktop build: {commit}, {jobs} jobs, {available / GIB:.1f} GiB available",
        flush=True,
    )
    compile_started = time.monotonic()
    run(
        "cargo",
        f"+{toolchain}",
        "build",
        "--locked",
        "--release",
        "--target",
        spec.target,
        "--bin",
        "codex",
        "--bin",
        "codex-code-mode-host",
        "--bin",
        "bwrap",
        "--timings",
        cwd=source / "codex-rs",
        env=env,
    )
    compile_seconds = round(time.monotonic() - compile_started, 2)
    binary_dir = target / spec.target / "release"
    package = PACKAGES / f"{commit}-{time.time_ns()}"
    package.mkdir()
    build_package_dir(
        package,
        version["version"],
        PACKAGE_VARIANTS["codex"],
        spec,
        PackageInputs(
            entrypoint_bin=binary_dir / "codex",
            code_mode_host_bin=binary_dir / "codex-code-mode-host",
            rg_bin=resolve_rg_bin(spec, None),
            zsh_bin=None,
            bwrap_bin=binary_dir / "bwrap",
            codex_command_runner_bin=None,
            codex_windows_sandbox_setup_bin=None,
        ),
    )
    for name in ("LICENSE", "NOTICE"):
        shutil.copy2(source / name, package / name)
    info = {
        "commit": commit,
        **version,
        "target": spec.target,
        "jobs": jobs,
        "compile_seconds": compile_seconds,
        "total_seconds": round(time.monotonic() - started, 2),
    }
    (package / "build-info.json").write_text(json.dumps(info, indent=2))
    from scripts.codex_package.nightly import record_stage
    from scripts.codex_package.verify_nightly import verify_run

    record_stage(run_dir, "build", "success", evidence=info)
    print(json.dumps(verify_run(run_dir, package), indent=2))


if __name__ == "__main__":
    if os.environ.get("CODEX_FROZEN_SOURCE"):
        main()
    else:
        import argparse

        sys.path.insert(0, str(REPO))
        from scripts.codex_package.source_snapshot import dispatch

        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--commit", required=True)
        parser.add_argument("--run-dir", required=True, type=Path)
        args = parser.parse_args()
        dispatch(REPO, args.commit, args.run_dir, "scripts/debian/build.py", [])
