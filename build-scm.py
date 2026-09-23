#!/usr/bin/env python3
"""Compile the Linux CLI/host in SCM and stage a verifiable output package."""

import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import tomllib

ROOT = Path(__file__).resolve().parent
os.environ["CODEX_REPO_ROOT"] = str(ROOT)

from scripts.codex_package.layout import build_package_dir
from scripts.codex_package.nightly_version import stamp_nightly_version
from scripts.codex_package.ripgrep import resolve_rg_bin
from scripts.codex_package.targets import PACKAGE_VARIANTS, TARGET_SPECS, PackageInputs
from scripts.codex_package.v8 import resolve_codex_v8_cargo_env
from scripts.codex_package.version import read_workspace_version

GIB = 1024**3


def memory_status():
    info = dict(
        line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines()
    )
    total = int(info["MemTotal"].split()[0]) * 1024
    available = int(info["MemAvailable"].split()[0]) * 1024
    groups = [(Path("/sys/fs/cgroup"), "memory.max", "memory.current")]
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        _, controllers, path = line.split(":", 2)
        if not controllers:
            groups.append(
                (
                    Path("/sys/fs/cgroup") / path.lstrip("/"),
                    "memory.max",
                    "memory.current",
                )
            )
        elif "memory" in controllers.split(","):
            groups.append(
                (
                    Path("/sys/fs/cgroup/memory") / path.lstrip("/"),
                    "memory.limit_in_bytes",
                    "memory.usage_in_bytes",
                )
            )
    groups.append(
        (
            Path("/sys/fs/cgroup/memory"),
            "memory.limit_in_bytes",
            "memory.usage_in_bytes",
        )
    )
    for directory, limit_name, usage_name in groups:
        limit_file = directory / limit_name
        if not limit_file.is_file():
            continue
        raw = limit_file.read_text().strip()
        if raw == "max" or int(raw) >= total:
            continue
        limit = int(raw)
        used = int((directory / usage_name).read_text())
        stats = dict(
            line.split()
            for line in (directory / "memory.stat").read_text().splitlines()
        )
        reclaimable = int(
            stats.get("inactive_file", stats.get("total_inactive_file", "0"))
        )
        total = min(total, limit)
        available = min(available, limit - used + reclaimable)
    return total, available


def main():
    started = time.monotonic()
    toolchain = tomllib.loads((ROOT / "codex-rs/rust-toolchain.toml").read_text())[
        "toolchain"
    ]["channel"]
    spec = TARGET_SPECS["x86_64-unknown-linux-gnu"]
    total, available = memory_status()
    cpus = len(os.sched_getaffinity(0))
    jobs = int(
        os.environ.get(
            "CUSTOM_CODEX_BUILD_JOBS", min(cpus, max(1, int(total / GIB - 4) // 2), 32)
        )
    )
    print(
        f"SCM resources: CPUs={cpus}, memory={total / GIB:.2f} GiB, "
        f"available={available / GIB:.2f} GiB, Cargo jobs={jobs}",
        flush=True,
    )
    cargo_home = Path(os.environ.get("CARGO_HOME", str(Path.home() / ".cargo")))
    # SCM's documented Rust cache includes CARGO_HOME. Keep both downloaded
    # inputs and Cargo outputs there so a new source commit can reuse them.
    target = cargo_home / "codex-target"
    env = {
        **os.environ,
        "CARGO_TARGET_DIR": str(target),
        "CARGO_BUILD_JOBS": str(jobs),
        "CARGO_PROFILE_RELEASE_LTO": "off",
        "CARGO_PROFILE_RELEASE_CODEGEN_UNITS": "8",
        "CARGO_PROFILE_RELEASE_INCREMENTAL": "false",
        "CARGO_NET_GIT_FETCH_WITH_CLI": "true",
        **resolve_codex_v8_cargo_env(spec, cache_root=cargo_home / "codex-v8"),
    }
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    version_info = stamp_nightly_version(ROOT, commit)
    rustc = subprocess.check_output(
        ["rustc", f"+{toolchain}", "--version"], text=True
    ).strip()
    metadata = {
        "commit": commit,
        **version_info,
        "target": spec.target,
        "rustc": rustc,
        "jobs": jobs,
        "affinity_cpus": cpus,
        "memory_limit_gib": round(total / GIB, 3),
        "initial_available_gib": round(available / GIB, 3),
        "cargo_target_dir": str(target),
        "target_existed": target.is_dir(),
        "rustflags": env.get("RUSTFLAGS", ""),
    }
    print(json.dumps(metadata), flush=True)
    if available < GIB:
        raise RuntimeError("Less than 1 GiB available before compilation")
    command = [
        "cargo",
        f"+{toolchain}",
        "build",
        "--locked",
        "--target",
        spec.target,
        "--release",
        "--bin",
        "codex",
        "--bin",
        "codex-code-mode-host",
        "--timings",
    ]
    compile_started = time.monotonic()
    minimum = available
    last_report = 0
    process = subprocess.Popen(
        command, cwd=ROOT / "codex-rs", env=env, start_new_session=True
    )
    try:
        while process.poll() is None:
            _, available = memory_status()
            minimum = min(minimum, available)
            if available < GIB:
                raise RuntimeError(
                    "Aborting SCM build: less than 1 GiB available in host/container"
                )
            if time.monotonic() - last_report > 30:
                print(
                    f"Build heartbeat: available={available / GIB:.2f} GiB", flush=True
                )
                last_report = time.monotonic()
            time.sleep(1)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                time.sleep(2)
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()
    metadata["compile_seconds"] = round(time.monotonic() - compile_started, 2)
    metadata["minimum_available_gib"] = round(minimum / GIB, 3)
    binaries = target / spec.target / "release"
    output = ROOT / "output"
    # SCM prepares a fresh output directory for each version.
    output.mkdir(exist_ok=True)
    build_package_dir(
        output,
        read_workspace_version(),
        PACKAGE_VARIANTS["codex"],
        spec,
        PackageInputs(
            entrypoint_bin=binaries / "codex",
            code_mode_host_bin=binaries / "codex-code-mode-host",
            rg_bin=resolve_rg_bin(spec, None),
            zsh_bin=None,
            bwrap_bin=None,
            codex_command_runner_bin=None,
            codex_windows_sandbox_setup_bin=None,
        ),
    )
    for name in ("LICENSE", "NOTICE"):
        (output / name).write_bytes((ROOT / name).read_bytes())
    cli_version = subprocess.check_output(
        [str(output / "bin/codex"), "--version"], text=True
    ).strip()
    assert cli_version == f"codex-cli {version_info['version']}", cli_version
    print(cli_version, flush=True)
    subprocess.run([str(output / "bin/codex-code-mode-host"), "--help"], check=True)
    metadata["total_seconds"] = round(time.monotonic() - started, 2)
    (output / "build-info.json").write_text(json.dumps(metadata, indent=2) + "\n")
    sums = []
    for relative in ("bin/codex", "bin/codex-code-mode-host", "codex-path/rg"):
        with (output / relative).open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        sums.append(f"{digest}  {relative}\n")
    (output / "SHA256SUMS").write_text("".join(sums))
    print(json.dumps(metadata), flush=True)


if __name__ == "__main__":
    main()
