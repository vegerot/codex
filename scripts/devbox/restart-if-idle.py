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
from pathlib import Path

from notify import connect, request


async def busy_threads(rpc):
    busy = []
    cursor = None
    while True:
        page = await rpc("thread/loaded/list", {"cursor": cursor, "limit": 100})
        for thread_id in page["data"]:
            thread = (
                await rpc("thread/read", {"threadId": thread_id, "includeTurns": False})
            )["thread"]
            status = thread["status"]["type"]
            # Waiting on approval/input is still active work. Unknown/error states
            # cannot establish idleness. Never exclude the nightly's own task.
            if status not in ("idle", "notLoaded"):
                busy.append({"threadId": thread_id, "status": status})
            else:
                queue = await rpc(
                    "thread/queue/list", {"threadId": thread_id, "limit": 1}
                )
                if queue["data"]:
                    busy.append({"threadId": thread_id, "status": "queued"})
        cursor = page["nextCursor"]
        if cursor is None:
            return busy


async def inspect_tasks():
    socket = await connect()
    request_id = 1

    async def rpc(method, params):
        nonlocal request_id
        request_id += 1
        return await request(socket, request_id, method, params)

    try:
        return await busy_threads(rpc)
    finally:
        await socket.close()


def restart(check_only=False):
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
    receipt = json.loads(
        (Path.home() / ".local/state/codex-rebuild/installed-scm.json").read_text()
    )
    if (
        selected != Path(receipt["package"]).resolve() / "bin/codex"
        or cli.resolve() != selected
    ):
        return {
            "status": "deferred",
            "reason": "Selected package differs from verified installation receipt",
        }
    pid_file = codex_home / "app-server-daemon/app-server.pid"
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
        while not select.select([fd], [], [], 1)[0]:
            pass
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
        if not Path(f"/proc/{new_pid}/exe").samefile(selected):
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
