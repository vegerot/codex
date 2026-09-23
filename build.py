#!/usr/bin/env python3

# Personal macOS/Linux setup: the terminal and installed ChatGPT.app use
# ~/.local/bin/codex -> codex-rs/target/codex-package-release/bin/codex.
# CODEX_CLI_PATH names that executable for Computer Use too. This script resolves V8 build inputs
# and builds matching release codex and codex-code-mode-host binaries. It then
# validates the existing package and atomically replaces each binary, preserving
# the rg/zsh resource symlinks; it does not create a package from scratch.
# Link-time optimization is off and codegen uses 8 units to favor build speed
# over maximum optimization. Incremental compilation is off to save disk space
# for daily unattended builds, accepting slower rebuilds. Reusing installed
# resources avoids duplication but lets their versions change with updates.
# Linux builds use 6 jobs. These full-access packages do not need a separate sandbox executable.
# Restart the app/server to load rebuilt binaries. More: ~/ai-conversations/codex/README.md

import json
import os
import platform
import shutil
import signal
import subprocess
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
os.environ["CODEX_REPO_ROOT"] = str(REPO_ROOT)

from scripts.codex_package.cargo import cargo_profile_output_dir  # noqa: E402
from scripts.codex_package.layout import validate_package_dir  # noqa: E402
from scripts.codex_package.targets import PACKAGE_VARIANTS  # noqa: E402
from scripts.codex_package.targets import TARGET_SPECS  # noqa: E402
from scripts.codex_package.targets import TargetSpec  # noqa: E402
from scripts.codex_package.v8 import resolve_codex_v8_cargo_env  # noqa: E402


PACKAGE_DIR = REPO_ROOT / "codex-rs" / "target" / "codex-package-release"
MIN_AVAILABLE_BYTES = 1024**3


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

    # The canonical Linux validator requires bwrap. Our full-access package
    # deliberately omits it, and does not require the optional patched zsh.
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

    validate_existing_package(spec)
    print(f"Updated Codex package binaries at {PACKAGE_DIR}")


def main() -> None:
    spec = host_spec()
    validate_existing_package(spec)
    env = {
        **os.environ,
        "CARGO_PROFILE_RELEASE_LTO": "off",
        "CARGO_PROFILE_RELEASE_CODEGEN_UNITS": "8",
        "CARGO_PROFILE_RELEASE_INCREMENTAL": "false",
        **resolve_codex_v8_cargo_env(spec),
    }

    command = [
        "cargo",
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
        "--timings",
    ]
    if spec.is_linux:
        build_linux(command, env)
    else:
        subprocess.run(command, cwd=REPO_ROOT / "codex-rs", env=env, check=True)
    install_release_binaries(spec)


if __name__ == "__main__":
    main()
