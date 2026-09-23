#!/usr/bin/env python3
"""Verify an exact-commit SCM package and optionally activate it on the devbox."""

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

SCM_REPO = "max/coplan/codex"
TARGET = "x86_64-unknown-linux-gnu"
STATE = Path.home() / ".local/state/codex-rebuild"
PACKAGES = Path.home() / ".local/share/codex-rebuild-packages"


def cli_json(*args):
    result = subprocess.run(
        ["bytedcli", "--json", *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    value = json.loads(result.stdout)
    if value["status"] != "success":
        raise RuntimeError(value.get("error"))
    return value["data"]


def verify_package(package, commit):
    info = json.loads((package / "build-info.json").read_text())
    manifest = json.loads((package / "codex-package.json").read_text())
    if (
        info["commit"] != commit
        or info["target"] != TARGET
        or manifest["target"] != TARGET
    ):
        raise RuntimeError(
            "SCM package does not match the requested source commit/target"
        )
    version = info["version"]
    if version.split("+", 1)[0] == "0.0.0" or manifest["version"] != version:
        raise RuntimeError("SCM package has an unstamped or inconsistent version")
    checksums = {
        path: digest
        for digest, path in (
            line.split() for line in (package / "SHA256SUMS").read_text().splitlines()
        )
    }
    for name in (
        "bin/codex",
        "bin/codex-code-mode-host",
        "codex-path/rg",
        "codex-resources/bwrap",
    ):
        with (package / name).open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != checksums[name]:
            raise RuntimeError(f"SCM package checksum mismatch: {name}")
    for binary, flag in (("codex", "--version"), ("codex-code-mode-host", "--help")):
        result = subprocess.run(
            [str(package / "bin" / binary), flag],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if binary == "codex" and result.stdout.strip() != f"codex-cli {version}":
            raise RuntimeError("CLI version does not match SCM build metadata")
    host_test = Path(__file__).resolve().with_name("test-host.py")
    subprocess.run(
        [sys.executable, str(host_test), str(package / "bin/codex-code-mode-host")],
        check=True,
        capture_output=True,
        timeout=60,
    )
    result = subprocess.run(
        [str(package / "bin/codex"), "doctor", "--json"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    doctor = json.loads(result.stdout)
    reports = STATE / "doctor"
    reports.mkdir(parents=True, exist_ok=True)
    report = reports / f"{commit}.json"
    report.write_text(json.dumps(doctor, indent=2) + "\n")
    if result.returncode or doctor["overallStatus"] == "fail":
        failures = [
            check["summary"]
            for check in doctor["checks"].values()
            if check["status"] == "fail"
        ]
        raise RuntimeError(f"SCM package doctor failed: {failures}; report: {report}")
    return (
        info,
        report,
        [
            check["summary"]
            for check in doctor["checks"].values()
            if check["status"] == "warning"
        ],
    )


def replace_link(target, link):
    if link.exists() and not link.is_symlink():
        raise RuntimeError(f"Refusing to overwrite a non-symlink launcher: {link}")
    previous = os.readlink(link) if link.is_symlink() else None
    pending = link.with_name(f".codex-scm-{os.getpid()}")
    try:
        pending.symlink_to(target)
        os.replace(pending, link)
    finally:
        pending.unlink(missing_ok=True)
    return previous


def activate(package, cli_link, daemon_current, settings_file):
    # The daemon selects its own package, independently of the invoking CLI.
    # Keep its existing package root/PID namespace; do not migrate a live daemon.
    for link in (cli_link, daemon_current):
        if link.exists() and not link.is_symlink():
            raise RuntimeError(f"Refusing to overwrite a non-symlink launcher: {link}")
    with (daemon_current.parent / "install.lock").open("a") as lock:
        # Coordinate with an official installer already in flight. Retry the
        # installation later if busy; do not compete with its package selection.
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        settings = json.loads(settings_file.read_text())
        previous_updater = settings.get("updater", {}).get("autoUpdateEnabled", True)
        settings.setdefault("updater", {})["autoUpdateEnabled"] = False
        temporary = settings_file.with_name(f".settings-nightly-{os.getpid()}.json")
        try:
            temporary.write_text(json.dumps(settings, indent=2) + "\n")
            os.replace(temporary, settings_file)
        finally:
            temporary.unlink(missing_ok=True)
        previous_daemon = replace_link(package, daemon_current)
        previous_cli = replace_link(package / "bin/codex", cli_link)
    return {
        "previousCodexTarget": previous_cli,
        "previousDaemonTarget": previous_daemon,
        "previousAutoUpdateEnabled": previous_updater,
        "daemonCurrent": str(daemon_current),
        "daemonRestartRequired": True,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version-id", required=True, type=int)
    parser.add_argument("--commit", required=True)
    parser.add_argument(
        "--install",
        action="store_true",
        help="Select the verified package for CLI and daemon; do not restart the daemon",
    )
    args = parser.parse_args()
    if len(args.commit) != 40 or any(c not in "0123456789abcdef" for c in args.commit):
        parser.error("--commit must be the complete lowercase 40-character Git SHA")
    metadata = cli_json(
        "scm", "repo", "artifact", "get", "--version-id", str(args.version_id)
    )
    if metadata["name"] != SCM_REPO:
        raise RuntimeError("Version belongs to a different SCM repository")
    matches = [item for item in metadata["x86_64"] if item["asset_kind"] == "package"]
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one Linux x86_64 SCM package")
    artifact = matches[0]
    PACKAGES.mkdir(parents=True, exist_ok=True)
    destination = PACKAGES / f"{args.version_id}-{args.commit}"
    downloaded_seconds = None
    if not destination.exists():
        if shutil.disk_usage(PACKAGES).free < 8 * 1024**3:
            raise RuntimeError(
                "Need at least 8 GiB free to stage and verify the package"
            )
        # Obtain auth via bytedcli, retaining the JWT only in memory.
        token = cli_json("--nomask", "auth", "get-bytecloud-jwt-token")["jwt"]
        with tempfile.TemporaryDirectory(prefix=".stage-", dir=PACKAGES) as temporary:
            stage = Path(temporary)
            archive = stage / "package.tar.gz"
            digest = hashlib.sha256()
            started = time.monotonic()
            request = Request(artifact["download_url"], headers={"x-jwt-token": token})
            with (
                urlopen(request, timeout=120) as response,
                archive.open("wb") as output,
            ):
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
            downloaded_seconds = round(time.monotonic() - started, 2)
            if digest.hexdigest() != artifact["sha256"]:
                raise RuntimeError("SCM archive checksum mismatch; not extracting")
            package = stage / "package"
            package.mkdir()
            with tarfile.open(archive) as bundle:
                bundle.extractall(package, filter="data")
            info, report, warnings = verify_package(package, args.commit)
            package.rename(destination)
    else:
        info, report, warnings = verify_package(destination, args.commit)
    receipt = {
        "versionId": args.version_id,
        "scmVersion": metadata["version"],
        "commit": args.commit,
        "package": str(destination),
        "archiveSha256": artifact["sha256"],
        "downloadSeconds": downloaded_seconds,
        "doctorReport": str(report),
        "doctorWarnings": warnings,
        "build": info,
        "installed": False,
    }
    if args.install:
        probe = subprocess.run(
            [str(destination / "bin/codex"), "app-server", "daemon", "version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        managed_binary = Path(json.loads(probe.stdout)["managedCodexPath"])
        daemon_current = managed_binary.parent.parent
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        allowed_roots = {
            (codex_home / "packages" / name).resolve()
            for name in ("standalone", "app-server-daemon")
        }
        if (
            managed_binary.name != "codex"
            or managed_binary.parent.name != "bin"
            or daemon_current.name != "current"
            or daemon_current.parent.resolve() not in allowed_roots
        ):
            raise RuntimeError(f"Unexpected managed daemon layout: {managed_binary}")
        receipt.update(
            activate(
                destination,
                Path.home() / ".local/bin/codex",
                daemon_current,
                codex_home / "app-server-daemon/settings.json",
            )
        )
        receipt["installed"] = True
        (STATE / "installed-scm.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
