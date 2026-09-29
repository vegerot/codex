"""Unix package selection under the managed daemon install lock."""

import fcntl
import json
import os
from pathlib import Path
import subprocess


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


def activate_verified(run):
    from scripts.codex_package.nightly import record_stage
    from scripts.codex_package.verify_nightly import hashes

    record = json.loads((run / "run.json").read_text())
    if record["profile"] == "windows":
        raise RuntimeError("Windows activation is not requested")
    verified = record["stages"]["verify"]
    if verified["status"] != "success":
        raise RuntimeError("Activation requires successful package verification")
    package = Path(verified["package"]).resolve()
    if hashes(package) != verified["hashes"]:
        raise RuntimeError("Package changed after verification")
    info = json.loads(
        subprocess.check_output(
            [str(package / "bin/codex"), "app-server", "daemon", "version"], text=True
        )
    )
    current = Path(info["managedCodexPath"]).parent.parent
    if current.name != "current":
        raise RuntimeError(f"Unexpected daemon package path: {current}")
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    previous = select_package(
        package,
        current,
        Path.home() / ".local/bin",
        home / "app-server-daemon/settings.json",
    )
    record_stage(run, "activate", "success", package=str(package), previous=previous)
    record_stage(run, "restart", "pending", package=str(package))
    return {"package": str(package), "restart": "pending"}
