#!/usr/bin/env python3

import os
import shutil
import subprocess
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


def atomic_copy(source: Path, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def install_release_binaries(spec: TargetSpec) -> None:
    variant = PACKAGE_VARIANTS["codex"]
    zsh_path = PACKAGE_DIR / "codex-resources" / "zsh" / "bin" / "zsh"
    include_zsh = zsh_path.is_file()
    validate_package_dir(PACKAGE_DIR, variant, spec, include_zsh=include_zsh)

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

    validate_package_dir(PACKAGE_DIR, variant, spec, include_zsh=include_zsh)
    print(f"Updated Codex package binaries at {PACKAGE_DIR}")


def main() -> None:
    spec = TARGET_SPECS["aarch64-apple-darwin"]
    env = {
        **os.environ,
        "CARGO_PROFILE_RELEASE_LTO": "off",
        "CARGO_PROFILE_RELEASE_CODEGEN_UNITS": "8",
        "CARGO_PROFILE_RELEASE_INCREMENTAL": "false",
        **resolve_codex_v8_cargo_env(spec),
    }

    subprocess.run(
        [
            "/usr/bin/caffeinate",
            "-i",
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
        ],
        cwd=REPO_ROOT / "codex-rs",
        env=env,
        check=True,
    )
    install_release_binaries(spec)


if __name__ == "__main__":
    main()
