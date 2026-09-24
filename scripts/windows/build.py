"""Native Windows release packages for the root build.py entry point."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import zipfile
from datetime import datetime
from pathlib import Path

from scripts.codex_package.layout import build_package_dir, validate_package_dir
from scripts.codex_package.nightly_version import stamp_nightly_version
from scripts.codex_package.ripgrep import resolve_rg_bin
from scripts.codex_package.targets import PACKAGE_VARIANTS, TARGET_SPECS, PackageInputs


def msvc_environment() -> dict[str, str]:
    """Read the installed x64 MSVC SDK environment from an ordinary PowerShell."""
    script = r"""$ErrorActionPreference = 'Stop'
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw 'Visual Studio C++ x64 build tools are required' }
$batch = Join-Path $vs 'Common7\Tools\VsDevCmd.bat'
$lines = & cmd.exe /d /c ('"{0}" -no_logo -arch=x64 -host_arch=x64 >nul && set' -f $batch)
if ($LASTEXITCODE -ne 0) { throw 'MSVC environment setup failed' }
$selected = @{}
foreach ($line in $lines) {
    if ($line -match '^(INCLUDE|LIB|LIBPATH|PATH|UCRTVersion|UniversalCRTSdkDir|VCINSTALLDIR|VCToolsInstallDir|WindowsLibPath|WindowsSdkBinPath|WindowsSdkDir|WindowsSDKLibVersion|WindowsSDKVersion)=(.*)$') {
        $selected[$Matches[1].ToUpperInvariant()] = $Matches[2]
    }
}
ConvertTo-Json $selected -Compress
"""
    return json.loads(
        subprocess.check_output(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script], text=True
        )
    )


def snapshot(repo: Path, cache: Path, commit: str) -> tuple[Path, dict]:
    """Stamp a disposable HEAD snapshot, preserving unchanged cached file times."""
    archive = cache / "source.zip"
    previous = set()
    if archive.exists():
        with zipfile.ZipFile(archive) as old:
            previous = {
                entry.filename for entry in old.infolist() if not entry.is_dir()
            }
    subprocess.run(
        ["git", "archive", "--format=zip", f"--output={archive}", commit],
        cwd=repo,
        check=True,
    )
    source = cache / "source"
    with zipfile.ZipFile(archive) as zipped:
        names = {entry.filename for entry in zipped.infolist() if not entry.is_dir()}
        # Only the manifests need a disposable copy for version stamping. Avoid
        # extracting and deleting thousands of unchanged files on each build.
        manifests = ("codex-rs/Cargo.toml", "codex-rs/Cargo.lock")
        with tempfile.TemporaryDirectory(dir=cache) as directory:
            staged = Path(directory)
            (staged / "codex-rs").mkdir()
            for name in manifests:
                (staged / name).write_bytes(zipped.read(name))
            version = stamp_nightly_version(staged, commit)
            stamped = {name: (staged / name).read_bytes() for name in manifests}
        for name in previous - names:
            obsolete = (source / name).resolve()
            assert obsolete.is_relative_to(source.resolve())
            obsolete.unlink(missing_ok=True)
        for name in names:
            destination = source / name
            data = stamped[name] if name in stamped else zipped.read(name)
            if not destination.exists() or destination.read_bytes() != data:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
    return source, version


def verify(package: Path, binaries: Path, repo: Path, run: Path, version: str) -> dict:
    spec = TARGET_SPECS["x86_64-pc-windows-msvc"]
    validate_package_dir(package, PACKAGE_VARIANTS["codex"], spec, include_zsh=False)
    cli = package / "bin/codex.exe"
    actual = subprocess.check_output([str(cli), "--version"], text=True).strip()
    if actual != f"codex-cli {version}":
        raise RuntimeError(f"Unexpected CLI version: {actual}")
    for script, executable in (
        ("scripts/devbox/test-host.py", package / "bin/codex-code-mode-host.exe"),
        ("scripts/codex_package/check_runtime_version.py", cli),
    ):
        subprocess.run(
            [sys.executable, str(repo / script), str(executable)],
            check=True,
            timeout=60,
        )
    features = subprocess.check_output([str(cli), "features", "list"], text=True)
    (run / "features.txt").write_text(features, encoding="utf-8")
    doctor = subprocess.run(
        [str(cli), "doctor", "--json"], capture_output=True, text=True, timeout=120
    )
    (run / "doctor.json").write_text(doctor.stdout, encoding="utf-8")
    (run / "doctor.stderr.txt").write_text(doctor.stderr, encoding="utf-8")
    report = json.loads(doctor.stdout)
    if doctor.returncode or report["overallStatus"] == "fail":
        raise RuntimeError(f"Doctor failed; see {run / 'doctor.json'}")
    hashes = {}
    for path in package.rglob("*.exe"):
        with path.open("rb") as file:
            hashes[path.relative_to(package).as_posix()] = hashlib.file_digest(
                file, "sha256"
            ).hexdigest()
        if path.name != "rg.exe":
            with (binaries / path.name).open("rb") as file:
                expected = hashlib.file_digest(file, "sha256").hexdigest()
            if hashes[path.relative_to(package).as_posix()] != expected:
                raise RuntimeError(f"Packaged binary differs from build output: {path}")
    return {"hashes": hashes, "doctor_status": report["overallStatus"]}


def build_windows(repo: Path, command: list[str], *, jobs: int) -> None:
    cache = Path.home() / ".cache/codex-windows-build"
    state = Path.home() / ".local/state/codex-windows-build"
    run = state / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    packages = Path.home() / ".local/share/codex-windows-build/packages"
    cache.mkdir(parents=True, exist_ok=True)
    run.mkdir(parents=True)
    packages.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()
    print(
        f"Building committed HEAD {commit}; working-copy edits are not included.",
        flush=True,
    )
    source, version = snapshot(repo, cache, commit)
    spec = TARGET_SPECS["x86_64-pc-windows-msvc"]
    toolchain = tomllib.loads((source / "codex-rs/rust-toolchain.toml").read_text())[
        "toolchain"
    ]["channel"]
    # Resolve V8 against the snapshot's lockfile and trusted checksum manifest,
    # not potentially edited files in the driver's working copy.
    v8_env = json.loads(
        subprocess.check_output(
            [
                sys.executable,
                "-c",
                "import json,sys; from pathlib import Path; "
                "from scripts.codex_package.targets import TARGET_SPECS; "
                "from scripts.codex_package.v8 import resolve_codex_v8_cargo_env; "
                "print(json.dumps(resolve_codex_v8_cargo_env("
                "TARGET_SPECS['x86_64-pc-windows-msvc'],cache_root=Path(sys.argv[1]))))",
                str(cache / "v8"),
            ],
            cwd=source,
            env={**os.environ, "CODEX_REPO_ROOT": str(source)},
            text=True,
        )
    )
    env = {
        **os.environ,
        **msvc_environment(),
        **v8_env,
        "CODEX_REPO_ROOT": str(source),
        "CARGO_TARGET_DIR": str(cache / "target"),
        "CARGO_BUILD_JOBS": str(jobs),
        "CARGO_PROFILE_RELEASE_LTO": "off",
        "CARGO_PROFILE_RELEASE_CODEGEN_UNITS": "16",
        "CARGO_PROFILE_RELEASE_INCREMENTAL": "false",
        "CARGO_PROFILE_RELEASE_DEBUG": "0",
        "CARGO_NET_GIT_FETCH_WITH_CLI": "true",
        "LIBSQLITE3_FLAGS": "SQLITE_DISABLE_INTRINSIC",
        "STABLE_GIT_COMMIT": commit,
    }
    command = [command[0], f"+{toolchain}", *command[1:]]
    info = {
        "commit": commit,
        **version,
        "jobs": jobs,
        "source": str(source),
        "target": spec.target,
        "cargo_target_dir": str(cache / "target"),
    }
    (run / "build-info.json").write_text(json.dumps(info, indent=2))
    print(f"Building with {jobs} jobs; log: {run / 'build.log'}", flush=True)
    started = time.monotonic()
    with (run / "build.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=source / "codex-rs",
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        monitor = subprocess.Popen(
            [
                "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(repo / "scripts/windows/monitor.ps1"),
                "-CargoPid",
                str(process.pid),
                "-OutputPath",
                str(run / "usage.csv"),
            ]
        )
        try:
            code = process.wait()
        finally:
            monitor.terminate()
            monitor.wait()
    info.update(compile_seconds=round(time.monotonic() - started, 2), exit_code=code)
    (run / "build-info.json").write_text(json.dumps(info, indent=2))
    if code:
        raise RuntimeError(f"Cargo failed ({code}); see {run / 'build.log'}")
    binaries = cache / "target" / spec.target / "release"
    # Windows can retain executable handles briefly after runtime checks. Build
    # in a unique destination and publish only the verified receipt; do not
    # rename a directory containing binaries that just ran.
    destination = packages / f"{version['version']}-{run.name}"
    package = destination
    package.mkdir()
    build_package_dir(
        package,
        version["version"],
        PACKAGE_VARIANTS["codex"],
        spec,
        PackageInputs(
            entrypoint_bin=binaries / "codex.exe",
            code_mode_host_bin=binaries / "codex-code-mode-host.exe",
            rg_bin=resolve_rg_bin(spec, None),
            zsh_bin=None,
            bwrap_bin=None,
            codex_command_runner_bin=binaries / "codex-command-runner.exe",
            codex_windows_sandbox_setup_bin=binaries
            / "codex-windows-sandbox-setup.exe",
        ),
    )
    shutil.copy2(
        binaries / "codex-windows-sandbox-service.exe",
        package / "codex-resources/codex-windows-sandbox-service.exe",
    )
    for name in ("LICENSE", "NOTICE"):
        shutil.copy2(source / name, package / name)
    info.update(verify(package, binaries, repo, run, version["version"]))
    info["package"] = str(destination)
    (run / "verified.json").write_text(json.dumps(info, indent=2))
    (state / "verified.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2), flush=True)
