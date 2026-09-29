"""Verify a complete final package without changing installation selection."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from scripts.codex_package.layout import validate_package_dir
from scripts.codex_package.targets import PACKAGE_VARIANTS, TARGET_SPECS
from scripts.codex_package.nightly import atomic_json, record_stage


def hashes(package):
    return {
        path.relative_to(package).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(package.rglob("*"))
        if path.is_file()
    }


def verify(package, commit, target, run):
    package = package.resolve()
    run.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((package / "codex-package.json").read_text())
    info = json.loads((package / "build-info.json").read_text())
    if (
        info["commit"] != commit
        or info["target"] != target
        or manifest["target"] != target
    ):
        raise RuntimeError("Package source/target differs from requested build")
    version = info["version"]
    if manifest["version"] != version or version.split("+", 1)[0] == "0.0.0":
        raise RuntimeError("Unstamped or inconsistent package version")
    spec = TARGET_SPECS[target]
    validate_package_dir(
        package,
        PACKAGE_VARIANTS["codex"],
        spec,
        include_zsh=(package / "codex-resources/zsh/bin/zsh").exists(),
    )
    sums = package / "SHA256SUMS"
    if sums.exists():
        for line in sums.read_text().splitlines():
            digest, name = line.split(maxsplit=1)
            path = package / name.lstrip("*")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"Artifact checksum mismatch: {name}")
    cli = package / "bin" / f"codex{spec.exe_suffix}"
    actual = subprocess.check_output(
        [str(cli), "--version"], text=True, timeout=30
    ).strip()
    if actual != f"codex-cli {version}":
        raise RuntimeError(f"Unexpected CLI version: {actual}")
    scripts = Path(__file__).resolve().parent
    for script, binary in (
        ("test_host.py", package / "bin" / f"codex-code-mode-host{spec.exe_suffix}"),
        ("check_runtime_version.py", cli),
    ):
        with (run / f"{script}.log").open("w") as log:
            subprocess.run(
                [sys.executable, str(scripts / script), str(binary)],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=60,
            )
    if spec.is_linux:
        subprocess.run(
            [str(package / "codex-resources/bwrap"), "--version"],
            check=True,
            timeout=30,
        )
    if spec.is_windows:
        if not (
            package / "codex-resources/codex-windows-sandbox-service.exe"
        ).is_file():
            raise RuntimeError("Windows sandbox service is missing")
    voice = package / "codex-resources/voice/manifest.json"
    if voice.exists():
        metadata = json.loads(voice.read_text())
        if metadata["buildCommit"] != commit or metadata["appVersion"] != version:
            raise RuntimeError("Voice source/version mismatch")
        for name, digest in metadata["sha256"].items():
            if hashlib.sha256((package / name).read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"Voice checksum mismatch: {name}")
        for binary in (
            cli,
            package / "bin/codex-code-mode-host",
            package / "codex-resources/voice/bin/codex-voice-host",
        ):
            subprocess.run(
                ["codesign", "--verify", "--strict", str(binary)], check=True
            )
    doctor = subprocess.run(
        [str(cli), "doctor", "--json"], capture_output=True, text=True, timeout=120
    )
    (run / "doctor.json").write_text(doctor.stdout)
    (run / "doctor.stderr.txt").write_text(doctor.stderr)
    report = json.loads(doctor.stdout)
    if doctor.returncode or report["overallStatus"] == "fail":
        raise RuntimeError(f"Doctor failed; see {run / 'doctor.json'}")
    result = {
        "package": str(package),
        "commit": commit,
        "target": target,
        "version": version,
        "hashes": hashes(package),
        "doctor_status": report["overallStatus"],
    }
    atomic_json(run / "verified.json", result)
    return result


def verify_run(run, package):
    record = json.loads((run / "run.json").read_text())
    try:
        commit = record["source_revision"]
        if not commit:
            raise RuntimeError("Set the run source_revision before verification")
        targets = {
            "devbox": "x86_64-unknown-linux-gnu",
            "debian": "x86_64-unknown-linux-gnu",
            "macos": "aarch64-apple-darwin",
            "windows": "x86_64-pc-windows-msvc",
        }
        result = verify(package, commit, targets[record["profile"]], run)
        record_stage(run, "verify", "success", **result)
        return result
    except Exception as error:
        record_stage(run, "verify", "failed", error=str(error))
        raise
