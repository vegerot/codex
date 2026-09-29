#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["websockets==15.0.1"]
# ///
"""Load a selected nightly once all managed tasks are idle; never force-kill work."""

import argparse
import asyncio
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.codex_package.idle_tasks import inspect_tasks
from scripts.macos.activate import verify_receipt


def version(cli):
    return json.loads(
        subprocess.check_output(
            [str(cli), "app-server", "daemon", "version"], text=True
        )
    )


def process_start(pid):
    return subprocess.check_output(
        ["ps", "-p", str(pid), "-o", "lstart="], text=True
    ).strip()


def running_executable(pid):
    output = subprocess.check_output(
        ["lsof", "-a", "-p", str(pid), "-d", "txt", "-Fn"], text=True
    )
    return next(
        Path(line[1:]).resolve() for line in output.splitlines() if line.startswith("n")
    )


def restart(package, check_only=False):
    cli = package / "bin/codex"
    info = version(cli)
    if Path(info["managedCodexPath"]).resolve() != cli:
        return {"status": "deferred", "reason": "Selected package changed"}
    if info["status"] != "running":
        return {"status": "not-running"}
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    legacy = "standalone" in Path(info["managedCodexPath"]).parts
    pid_file = (
        home / "app-server-daemon" / ("app-server.pid" if legacy else "daemon.pid")
    )
    record = pid_file.read_text()
    process = json.loads(record)
    pid = process["pid"]
    if process_start(pid) != process["processStartTime"]:
        raise RuntimeError("Stale daemon PID record")
    expected = json.loads((package / "codex-package.json").read_text())["version"]
    if info["appServerVersion"] == expected and running_executable(pid) == cli:
        return {"status": "already-current", "version": expected}
    busy = asyncio.run(inspect_tasks())
    if busy:
        return {"status": "deferred", "reason": "Tasks are busy", "tasks": busy}
    if check_only:
        return {"status": "idle", "restartRequired": True}
    if (
        pid_file.read_text() != record
        or process_start(pid) != process["processStartTime"]
        or Path(info["managedCodexPath"]).resolve() != cli
    ):
        return {"status": "deferred", "reason": "Daemon or selection changed"}
    # SIGHUP closes admission and drains turns that raced the idle check.
    # Do not use `daemon restart`: its grace timeout can escalate to SIGKILL.
    os.kill(pid, signal.SIGHUP)
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        try:
            if process_start(pid) != process["processStartTime"]:
                break
        except subprocess.CalledProcessError:
            break
        time.sleep(1)
    else:
        return {"status": "deferred", "reason": "Daemon is still draining"}
    if Path(info["managedCodexPath"]).resolve() != cli:
        return {"status": "deferred", "reason": "Selected package changed"}
    subprocess.run([str(cli), "app-server", "daemon", "start"], check=True)
    after = version(cli)
    new_pid = json.loads(pid_file.read_text())["pid"]
    if after["appServerVersion"] != expected or running_executable(new_pid) != cli:
        raise RuntimeError("Restart did not load the verified nightly version")
    return {"status": "restarted", "version": expected}


def finish(receipt_path, check_only=False):
    package = verify_receipt(json.loads(receipt_path.read_text()))
    with (receipt_path.parent / "restart.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        deadline = time.monotonic() + 1800
        while True:
            result = restart(package, check_only)
            print(json.dumps(result), flush=True)
            if check_only:
                return result
            (receipt_path.parent / "restart.json").write_text(
                json.dumps(result, indent=2) + "\n"
            )
            if result.get("reason") != "Tasks are busy" or time.monotonic() >= deadline:
                return result
            time.sleep(15)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        finish(args.receipt, args.check)
    except Exception as error:
        result = {"status": "error", "reason": str(error)}
        print(json.dumps(result), flush=True)
        if not args.check:
            (args.receipt.parent / "restart.json").write_text(
                json.dumps(result, indent=2) + "\n"
            )
        sys.exit(1)
