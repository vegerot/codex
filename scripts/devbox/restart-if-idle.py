#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["websockets==15.0.1"]
# ///
"""After the build task exits, load a verified nightly only if the daemon is idle."""

import argparse
import asyncio
import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.codex_package.idle_tasks import inspect_tasks


def restart(check_only=False, package=None):
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    cli = Path.home() / ".local/bin/codex"
    info = json.loads(
        subprocess.check_output(
            [str(cli), "app-server", "daemon", "version"], text=True
        )
    )
    if info["status"] != "running":
        return {"status": "not-running"}
    selected = Path(info["managedCodexPath"]).resolve()
    if package is None:
        receipt = json.loads(
            (Path.home() / ".local/state/codex-rebuild/installed-scm.json").read_text()
        )
        package = Path(receipt["package"])
    if selected != package.resolve() / "bin/codex" or cli.resolve() != selected:
        return {
            "status": "deferred",
            "reason": "Selected package differs from verified installation receipt",
        }
    namespace = (
        "app-server.pid"
        if "standalone" in Path(info["managedCodexPath"]).parts
        else "daemon.pid"
    )
    pid_file = codex_home / "app-server-daemon" / namespace
    record = pid_file.read_text()
    pid = json.loads(record)["pid"]
    # A pidfd pins the process even if the numeric PID is later reused.
    fd = os.pidfd_open(pid)
    try:
        start_ticks = int(
            Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
        )
        if start_ticks != json.loads(record)["processIdentity"]["startTicks"]:
            return {"status": "deferred", "reason": "Stale daemon PID record"}
        if Path(f"/proc/{pid}/exe").samefile(selected):
            return {"status": "already-current", "version": info["appServerVersion"]}
        busy = asyncio.run(inspect_tasks())
        if busy:
            return {"status": "deferred", "reason": "Tasks are busy", "tasks": busy}
        if check_only:
            return {"status": "idle", "restartRequired": True}
        if (
            pid_file.read_text() != record
            or Path(info["managedCodexPath"]).resolve() != selected
        ):
            return {
                "status": "deferred",
                "reason": "Daemon or selected package changed during check",
            }
        # SIGHUP closes admission and drains any turn that raced the idle check.
        # Unlike `daemon restart`, this path never escalates to SIGKILL.
        signal.pidfd_send_signal(fd, signal.SIGHUP)
        deadline = time.monotonic() + 1800
        while not select.select([fd], [], [], 1)[0]:
            if time.monotonic() >= deadline:
                return {"status": "deferred", "reason": "Daemon is still draining"}
        if Path(info["managedCodexPath"]).resolve() != selected:
            return {"status": "deferred", "reason": "Selected package changed"}
        # Start in a separate systemd cgroup so the nightly oneshot's cleanup
        # cannot kill the newly detached server. This unit has no ExecStop.
        subprocess.run(
            ["systemctl", "--user", "restart", "codex-rebuild-daemon-start.service"],
            check=True,
        )
        after = json.loads(
            subprocess.check_output(
                [str(cli), "app-server", "daemon", "version"], text=True
            )
        )
        new_pid = json.loads(pid_file.read_text())["pid"]
        expected = json.loads((package / "codex-package.json").read_text())["version"]
        if (
            not Path(f"/proc/{new_pid}/exe").samefile(selected)
            or after["appServerVersion"] != expected
        ):
            raise RuntimeError("Restart did not load the selected executable")
        return {
            "status": "restarted",
            "pid": new_pid,
            "version": after["appServerVersion"],
        }
    finally:
        os.close(fd)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Inspect only; never signal or restart"
    )
    args = parser.parse_args()
    try:
        result = restart(args.check)
    except Exception as error:  # noqa: BLE001 - report failures at the CLI boundary
        # A failed inspection never grants permission to restart. Still let the
        # runner announce its build report with this failure attached.
        result = {"status": "error", "reason": str(error)}
    print(json.dumps(result))
