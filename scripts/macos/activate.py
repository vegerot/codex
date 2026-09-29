#!/usr/bin/env python3
"""Select a verified nightly for the CLI and daemon without interrupting work."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def verify_receipt(receipt):
    if not receipt["installed"]:
        raise RuntimeError("Receipt does not describe an installed package")
    package = Path(receipt["package"]).resolve()
    manifest = json.loads((package / "codex-package.json").read_text())
    if manifest["version"] != receipt["build"]["version"]:
        raise RuntimeError("Package version differs from receipt")
    for name, expected in receipt["binary_hashes"].items():
        with (package / "bin" / name).open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != expected:
            raise RuntimeError(f"Installed checksum differs from receipt: {name}")
    return package


def select_package(package, current, launchers, settings_file):
    links = {current: package}
    links.update(
        {
            launchers / name: package / "bin" / name
            for name in ("codex", "codex-code-mode-host")
        }
    )
    for link in links:
        if link.exists() and not link.is_symlink():
            raise RuntimeError(f"Refusing to overwrite non-symlink: {link}")
    current.parent.mkdir(parents=True, exist_ok=True)
    with (current.parent / "install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        settings = (
            json.loads(settings_file.read_text()) if settings_file.exists() else {}
        )
        settings.setdefault("updater", {})["autoUpdateEnabled"] = False
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = settings_file.with_suffix(f".nightly-{os.getpid()}.tmp")
        temporary.write_text(json.dumps(settings, indent=2) + "\n")
        temporary.replace(settings_file)
        previous = {
            str(link): str(link.readlink()) if link.is_symlink() else None
            for link in links
        }
        for link, target in links.items():
            link.parent.mkdir(parents=True, exist_ok=True)
            temporary = link.with_name(f".{link.name}.nightly-{os.getpid()}")
            temporary.symlink_to(target)
            temporary.replace(link)
        (current.parent / "auto-update-version").unlink(missing_ok=True)
    return previous


def activate(receipt_path, schedule_restart=False):
    receipt = json.loads(receipt_path.read_text())
    package = verify_receipt(receipt)
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    info = json.loads(
        subprocess.check_output(
            [str(package / "bin/codex"), "app-server", "daemon", "version"], text=True
        )
    )
    # Ask Codex which package root it owns; preserve the existing PID namespace.
    current = Path(info["managedCodexPath"]).parent.parent
    if current.name != "current":
        raise RuntimeError(f"Unexpected managed package path: {current}")
    previous = select_package(
        package,
        current,
        Path.home() / ".local/bin",
        home / "app-server-daemon/settings.json",
    )
    state = receipt_path.parent
    result = {
        "package": str(package),
        "previousLinks": previous,
        "daemonRestartRequired": info["status"] == "running",
    }
    (state / "activation.json").write_text(json.dumps(result, indent=2) + "\n")
    if schedule_restart:
        uv = shutil.which("uv")
        if not uv:
            raise RuntimeError("uv is required to schedule the idle restart")
        with (state / "restart.log").open("a") as log:
            worker = subprocess.Popen(
                [
                    uv,
                    "--system-certs",
                    "run",
                    "--script",
                    str(Path(__file__).with_name("restart_if_idle.py")),
                    "--receipt",
                    str(receipt_path.resolve()),
                ],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        result["restartWorkerPid"] = worker.pid
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--schedule-restart", action="store_true")
    args = parser.parse_args()
    print(json.dumps(activate(args.receipt, args.schedule_restart), indent=2))
