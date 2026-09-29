#!/usr/bin/env python3
"""Build and install this desktop's Codex fork; scheduling and updates stay in Codex."""

import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib

REPO = Path(__file__).resolve().parents[2]
CACHE = Path.home() / ".cache/codex-desktop-build"
STATE = Path.home() / ".local/state/codex-desktop-build"
PACKAGES = Path.home() / ".local/share/codex-desktop-build/packages"
GIB = 1024**3


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def revision():
    return run(
        "sl", "log", "--rev", ".", "--template", "{node}", cwd=REPO, capture_output=True
    ).stdout.strip()


def select_daemon_package(package):
    home = Path.home() / ".codex"
    root = home / "packages/app-server-daemon"
    root.mkdir(parents=True, exist_ok=True)
    with (root / "install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        settings_file = home / "app-server-daemon/settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings = (
            json.loads(settings_file.read_text()) if settings_file.exists() else {}
        )
        settings.setdefault("updater", {})["autoUpdateEnabled"] = False
        temporary = settings_file.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(settings, indent=2) + "\n")
        temporary.replace(settings_file)
        current = root / "current"
        assert not current.exists() or current.is_symlink(), (
            "Unexpected daemon package directory"
        )
        pending = root / ".desktop-build-current"
        pending.unlink(missing_ok=True)
        pending.symlink_to(package)
        pending.replace(current)


def verify(package, version):
    assert os.access(package / "codex-resources/bwrap", os.X_OK), (
        "Missing executable bwrap"
    )
    actual = run(
        str(package / "bin/codex"), "--version", capture_output=True
    ).stdout.strip()
    assert actual == f"codex-cli {version}", actual
    run(
        sys.executable,
        str(CACHE / "source/scripts/codex_package/test_host.py"),
        str(package / "bin/codex-code-mode-host"),
        timeout=60,
    )
    doctor = subprocess.run(
        [str(package / "bin/codex"), "doctor", "--json"],
        text=True,
        capture_output=True,
        timeout=120,
    )
    report = json.loads(doctor.stdout)
    (STATE / "doctor.json").write_text(json.dumps(report, indent=2) + "\n")
    assert doctor.returncode == 0 and report["overallStatus"] != "fail", (
        "See doctor.json"
    )
    return report


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
    pending = run(
        "sl",
        "status",
        "--modified",
        "--added",
        "--removed",
        "--deleted",
        cwd=REPO,
        capture_output=True,
    ).stdout
    if pending:
        raise RuntimeError(
            f"Tracked changes must be resolved before building:\n{pending}"
        )
    commit = revision()
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
    source = CACHE / "source"
    source.mkdir(exist_ok=True)
    # Stable source paths and unchanged mtimes preserve Cargo's dependency cache.
    # Version stamping touches only this disposable snapshot, never the working copy.
    with tempfile.TemporaryDirectory(dir=CACHE) as temporary:
        snapshot = Path(temporary) / "source"
        run(
            "sl",
            "--config",
            "ui.archivemeta=false",
            "archive",
            "--type",
            "files",
            "--include",
            "glob:**",
            "--rev",
            commit,
            str(snapshot),
            cwd=REPO,
        )
        sys.path.insert(0, str(snapshot))
        from scripts.codex_package.nightly_version import stamp_nightly_version

        version = stamp_nightly_version(snapshot, commit)
        run(
            "rsync",
            "--recursive",
            "--links",
            "--perms",
            "--checksum",
            "--delete",
            str(snapshot) + "/",
            str(source) + "/",
        )
    os.environ["CODEX_REPO_ROOT"] = str(source)
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
    launcher = Path.home() / ".local/bin/codex"
    receipt_path = STATE / "installed.json"
    if receipt_path.exists():
        installed = json.loads(receipt_path.read_text())
        package = Path(installed["package"])
        if (
            installed["commit"] == commit
            and installed["version"] == version["version"]
            and launcher.resolve() == package / "bin/codex"
        ):
            verify(package, version["version"])
            select_daemon_package(package)
            print(
                f"Unchanged source; warm build verified in {compile_seconds}s. Already installed: {package}"
            )
            return
    with tempfile.TemporaryDirectory(prefix="staging-", dir=PACKAGES) as temporary:
        package = Path(temporary)
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
        report = verify(package, version["version"])
        assert revision() == commit, "Working-copy revision changed during build"
        destination = PACKAGES / f"{commit}-{time.time_ns()}"
        package.rename(destination)
    if launcher.exists() and not launcher.is_symlink():
        raise RuntimeError(f"Refusing to overwrite non-symlink launcher: {launcher}")
    previous = str(launcher.resolve())
    temporary_link = launcher.with_name(".codex-desktop-build-next")
    temporary_link.unlink(missing_ok=True)
    temporary_link.symlink_to(destination / "bin/codex")
    temporary_link.replace(launcher)
    select_daemon_package(destination)
    receipt = {
        "commit": commit,
        **version,
        "jobs": jobs,
        "package": str(destination),
        "previous_executable": previous,
        "compile_seconds": compile_seconds,
        "total_seconds": round(time.monotonic() - started, 2),
        "initial_available_gib": round(available / GIB, 2),
        "doctor_status": report["overallStatus"],
    }
    (STATE / "installed.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
