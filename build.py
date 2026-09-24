#!/usr/bin/env python3

# Local macOS/Linux setup: the terminal and installed ChatGPT.app use
# ~/.local/bin/codex -> codex-rs/target/codex-package-release/bin/codex.
# CODEX_CLI_PATH names that executable for Computer Use too. This script resolves V8 build inputs
# and builds matching release codex and codex-code-mode-host binaries. It then
# validates the existing package and atomically replaces each binary, preserving
# the rg/zsh resource symlinks; it does not create a package from scratch.
# Link-time optimization is off and codegen uses 8 units to favor build speed
# over maximum optimization. Incremental compilation is off to save disk space
# for daily unattended builds, accepting slower rebuilds. Reusing installed
# resources avoids duplication but lets their versions change with updates.
# Linux builds use 6 jobs and include bwrap for daemon package validation.
# Local builds set the package version used by Remote Control without editing Cargo files.
# --scm builds a fresh, versioned Linux package on an SCM worker instead.
# Restart the app/server to load rebuilt binaries. More: ~/ai-conversations/codex/README.md

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
os.environ["CODEX_REPO_ROOT"] = str(REPO_ROOT)

from scripts.codex_package.cargo import cargo_profile_output_dir  # noqa: E402
from scripts.codex_package.layout import (  # noqa: E402
    build_package_dir,
    validate_package_dir,
)
from scripts.codex_package.ripgrep import resolve_rg_bin  # noqa: E402
from scripts.codex_package.targets import (  # noqa: E402
    PACKAGE_VARIANTS,
    TARGET_SPECS,
    PackageInputs,
    TargetSpec,
)
from scripts.codex_package.v8 import resolve_codex_v8_cargo_env  # noqa: E402
from scripts.codex_package.version import read_workspace_version  # noqa: E402

PACKAGE_DIR = REPO_ROOT / "codex-rs" / "target" / "codex-package-release"
MIN_AVAILABLE_BYTES = 1024**3
RELEASE_ENV = {
    "CARGO_PROFILE_RELEASE_LTO": "off",
    "CARGO_PROFILE_RELEASE_CODEGEN_UNITS": "8",
    "CARGO_PROFILE_RELEASE_INCREMENTAL": "false",
}


def host_spec() -> TargetSpec:
    targets = {
        ("Darwin", "arm64"): "aarch64-apple-darwin",
        ("Darwin", "x86_64"): "x86_64-apple-darwin",
        ("Linux", "aarch64"): "aarch64-unknown-linux-gnu",
        ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
    }
    host = (platform.system(), platform.machine())
    if host not in targets:
        raise RuntimeError(f"Unsupported build host: {host}")
    return TARGET_SPECS[targets[host]]


def validate_existing_package(spec: TargetSpec) -> None:
    if not spec.is_linux:
        zsh_path = PACKAGE_DIR / "codex-resources" / "zsh" / "bin" / "zsh"
        validate_package_dir(
            PACKAGE_DIR, PACKAGE_VARIANTS["codex"], spec, include_zsh=zsh_path.is_file()
        )
        return

    # Validate the existing skeleton before installing newly built resources.
    # The complete Linux package is validated after bwrap is installed.
    metadata = json.loads((PACKAGE_DIR / "codex-package.json").read_text())
    expected = {
        "layoutVersion": 1,
        "target": spec.target,
        "variant": "codex",
        "entrypoint": "bin/codex",
        "resourcesDir": "codex-resources",
        "pathDir": "codex-path",
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise RuntimeError(f"Invalid package metadata: {key} must be {value!r}")
    for relative in ("bin/codex", "bin/codex-code-mode-host", "codex-path/rg"):
        path = PACKAGE_DIR / relative
        if not path.is_file() or not os.access(path, os.X_OK):
            raise RuntimeError(f"Missing package executable: {path}")


def available_memory() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise RuntimeError("Linux did not report MemAvailable")


def build_linux(command: list[str], env: dict[str, str]) -> None:
    for jobs in (6, 4, 2):
        minimum = available_memory()
        if minimum < MIN_AVAILABLE_BYTES:
            raise RuntimeError("Refusing build: less than 1 GiB RAM available")
        print(f"Building with {jobs} jobs; abort below 1 GiB available RAM", flush=True)
        aborted = False
        last_report = time.monotonic()
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT / "codex-rs",
            env={**env, "CARGO_BUILD_JOBS": str(jobs)},
            start_new_session=True,
        )
        try:
            while process.poll() is None:
                available = available_memory()
                minimum = min(minimum, available)
                if available < MIN_AVAILABLE_BYTES:
                    aborted = True
                    print("Aborting build: less than 1 GiB RAM available", flush=True)
                    break
                if time.monotonic() - last_report >= 30:
                    print(f"Available RAM: {available / 1024**3:.2f} GiB", flush=True)
                    last_report = time.monotonic()
                time.sleep(1)
        finally:
            # Also stop children if the monitor itself fails or is interrupted.
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    time.sleep(2)
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            result = process.wait()
        print(f"Minimum available RAM: {minimum / 1024**3:.2f} GiB", flush=True)
        if not aborted:
            if result:
                raise subprocess.CalledProcessError(result, command)
            return
    raise RuntimeError("Build exceeded the memory limit even with two jobs")


def atomic_copy(source: Path, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def install_release_binaries(spec: TargetSpec) -> None:
    variant = PACKAGE_VARIANTS["codex"]
    validate_existing_package(spec)

    output_dir = cargo_profile_output_dir(spec, "release")
    package_bin_dir = PACKAGE_DIR / "bin"
    atomic_copy(
        output_dir / variant.entrypoint_name(spec),
        package_bin_dir / variant.entrypoint_name(spec),
    )
    atomic_copy(
        output_dir / f"codex-code-mode-host{spec.exe_suffix}",
        package_bin_dir / f"codex-code-mode-host{spec.exe_suffix}",
    )

    if spec.is_linux:
        atomic_copy(output_dir / "bwrap", PACKAGE_DIR / "codex-resources" / "bwrap")
        validate_package_dir(PACKAGE_DIR, variant, spec, include_zsh=False)
    else:
        validate_existing_package(spec)
    print(f"Updated Codex package binaries at {PACKAGE_DIR}")


def update_package_version(version: str) -> None:
    metadata_path = PACKAGE_DIR / "codex-package.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["version"] = version
    temporary = metadata_path.with_name(f".{metadata_path.name}.tmp")
    try:
        temporary.write_text(json.dumps(metadata, indent=2) + "\n")
        os.replace(temporary, metadata_path)
    finally:
        temporary.unlink(missing_ok=True)


def cargo_command(spec: TargetSpec, toolchain: str | None = None) -> list[str]:
    command = ["cargo"]
    if toolchain is not None:
        command.append(f"+{toolchain}")
    command.extend(
        [
            "build",
            "--locked",
            "--target",
            spec.target,
            "--profile",
            "release",
            "--bin",
            "codex",
            "--bin",
            "codex-code-mode-host",
        ]
    )
    if spec.is_linux:
        command.extend(["--bin", "bwrap"])
    command.append("--timings")
    return command


def build_local() -> None:
    from scripts.codex_package.nightly_version import nightly_version

    spec = host_spec()
    validate_existing_package(spec)
    env = {
        **os.environ,
        **RELEASE_ENV,
        **resolve_codex_v8_cargo_env(spec),
    }
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()
    version_info = nightly_version(commit)
    command = cargo_command(spec)
    if spec.is_linux:
        build_linux(command, env)
    else:
        subprocess.run(command, cwd=REPO_ROOT / "codex-rs", env=env, check=True)
    binary = cargo_profile_output_dir(spec, "release") / "codex"
    cli_version = subprocess.check_output([str(binary), "--version"], text=True).strip()
    # --version remains the Cargo crate version; Remote Control uses the package version.
    expected = f"codex-cli {read_workspace_version()}"
    if cli_version != expected:
        raise RuntimeError(
            f"Built Codex reported {cli_version!r}, expected {expected!r}"
        )
    install_release_binaries(spec)
    update_package_version(version_info["version"])
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/codex_package/check_runtime_version.py"),
            str(PACKAGE_DIR / "bin/codex"),
        ],
        check=True,
    )
    print(
        f"{cli_version}; Remote Control package version {version_info['version']}",
        flush=True,
    )


def scm_memory_status() -> tuple[int, int]:
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


def build_scm() -> None:
    import tomllib

    from scripts.codex_package.nightly_version import stamp_nightly_version

    started = time.monotonic()
    # rust.compile.lyra has pkg-config but lacks bubblewrap's libcap headers.
    # Install them on the disposable Linux worker before starting Cargo.
    if subprocess.run(["pkg-config", "--exists", "libcap"], check=False).returncode:
        privilege = [] if os.geteuid() == 0 else ["sudo", "-n"]
        subprocess.run([*privilege, "apt-get", "update"], check=True)
        subprocess.run(
            [
                *privilege,
                "apt-get",
                "install",
                "--yes",
                "--no-install-recommends",
                "libcap-dev",
            ],
            check=True,
        )
    subprocess.run(["pkg-config", "--modversion", "libcap"], check=True)
    toolchain = tomllib.loads((REPO_ROOT / "codex-rs/rust-toolchain.toml").read_text())[
        "toolchain"
    ]["channel"]
    spec = TARGET_SPECS["x86_64-unknown-linux-gnu"]
    total, available = scm_memory_status()
    cpus = len(os.sched_getaffinity(0))
    jobs = int(
        os.environ.get(
            "CUSTOM_CODEX_BUILD_JOBS",
            min(cpus, max(1, int(total / MIN_AVAILABLE_BYTES - 4) // 2), 32),
        )
    )
    print(
        f"SCM resources: CPUs={cpus}, memory={total / MIN_AVAILABLE_BYTES:.2f} GiB, "
        f"available={available / MIN_AVAILABLE_BYTES:.2f} GiB, Cargo jobs={jobs}",
        flush=True,
    )
    cargo_home = Path(os.environ.get("CARGO_HOME", str(Path.home() / ".cargo")))
    # SCM caches CARGO_HOME, including Cargo outputs and V8 artifacts.
    target = cargo_home / "codex-target"
    env = {
        **os.environ,
        **RELEASE_ENV,
        "CARGO_TARGET_DIR": str(target),
        "CARGO_BUILD_JOBS": str(jobs),
        "CARGO_NET_GIT_FETCH_WITH_CLI": "true",
        **resolve_codex_v8_cargo_env(spec, cache_root=cargo_home / "codex-v8"),
    }
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()
    version_info = stamp_nightly_version(REPO_ROOT, commit)
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
        "memory_limit_gib": round(total / MIN_AVAILABLE_BYTES, 3),
        "initial_available_gib": round(available / MIN_AVAILABLE_BYTES, 3),
        "cargo_target_dir": str(target),
        "target_existed": target.is_dir(),
        "rustflags": env.get("RUSTFLAGS", ""),
    }
    print(json.dumps(metadata), flush=True)
    if available < MIN_AVAILABLE_BYTES:
        raise RuntimeError("Less than 1 GiB available before compilation")
    command = cargo_command(spec, toolchain)
    compile_started = time.monotonic()
    minimum = available
    last_report = 0
    process = subprocess.Popen(
        command, cwd=REPO_ROOT / "codex-rs", env=env, start_new_session=True
    )
    try:
        while process.poll() is None:
            _, available = scm_memory_status()
            minimum = min(minimum, available)
            if available < MIN_AVAILABLE_BYTES:
                raise RuntimeError(
                    "Aborting SCM build: less than 1 GiB available in host/container"
                )
            if time.monotonic() - last_report > 30:
                print(
                    f"Build heartbeat: available={available / MIN_AVAILABLE_BYTES:.2f} GiB",
                    flush=True,
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
    metadata["minimum_available_gib"] = round(minimum / MIN_AVAILABLE_BYTES, 3)
    binaries = target / spec.target / "release"
    output = REPO_ROOT / "output"
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
            bwrap_bin=binaries / "bwrap",
            codex_command_runner_bin=None,
            codex_windows_sandbox_setup_bin=None,
        ),
    )
    for name in ("LICENSE", "NOTICE"):
        (output / name).write_bytes((REPO_ROOT / name).read_bytes())
    cli_version = subprocess.check_output(
        [str(output / "bin/codex"), "--version"], text=True
    ).strip()
    assert cli_version == f"codex-cli {version_info['version']}", cli_version
    print(cli_version, flush=True)
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/codex_package/check_runtime_version.py"),
            str(output / "bin/codex"),
        ],
        check=True,
    )
    subprocess.run([str(output / "bin/codex-code-mode-host"), "--help"], check=True)
    subprocess.run([str(output / "codex-resources/bwrap"), "--version"], check=True)
    metadata["total_seconds"] = round(time.monotonic() - started, 2)
    (output / "build-info.json").write_text(json.dumps(metadata, indent=2) + "\n")
    sums = []
    for relative in (
        "bin/codex",
        "bin/codex-code-mode-host",
        "codex-path/rg",
        "codex-resources/bwrap",
    ):
        with (output / relative).open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        sums.append(f"{digest}  {relative}\n")
    (output / "SHA256SUMS").write_text("".join(sums))
    print(json.dumps(metadata), flush=True)


def main(scm: bool = False) -> None:
    if scm:
        build_scm()
    else:
        build_local()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Codex locally or on SCM")
    parser.add_argument("--scm", action="store_true", help="create an SCM package")
    main(parser.parse_args().scm)
