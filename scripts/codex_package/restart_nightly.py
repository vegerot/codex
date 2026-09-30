"""Bounded idle restart of the package recorded by a published Unix run."""

import asyncio
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from contextlib import nullcontext
from functools import partial
from pathlib import Path

from scripts.codex_package.nightly import ROOT, atomic_json, record_stage


def require_published(run):
    record = json.loads((run / "run.json").read_text())
    for stage in ("build", "verify", "activate", "publish"):
        if record["stages"][stage]["status"] != "success":
            raise RuntimeError(f"Restart requires successful {stage}")
    return record


def schedule(run):
    require_published(run)
    frozen = run / "helpers"
    if not frozen.exists():
        shutil.copytree(
            ROOT / "scripts",
            frozen / "scripts",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
    command = [
        shutil.which("uv") or "uv",
        "--native-tls",
        "run",
        "--with",
        "websockets==15.0.1",
        "python",
        str(frozen / "scripts/nightly.py"),
        "restart",
        "--run-dir",
        str(run),
        "--worker",
    ]
    try:
        log_context = (
            nullcontext(None)
            if sys.platform == "win32"
            else (run / "restart.log").open("a")
        )
        with log_context as log:
            if sys.platform == "win32":
                from scripts.windows.activation import powershell

                starter = run / "restart-worker.ps1"
                invocation = "& " + " ".join(
                    "'" + arg.replace("'", "''") + "'" for arg in command
                )
                starter.write_text(
                    invocation
                    + " *> '"
                    + str(run / "restart.log").replace("'", "''")
                    + "'\n"
                )
                launched = json.loads(
                    powershell(
                        "$startup = New-CimInstance Win32_ProcessStartup -ClientOnly -Property @{ShowWindow=[uint16]0}; "
                        "$r = Invoke-CimMethod Win32_Process -MethodName Create -Arguments @{CommandLine=$env:NIGHTLY_COMMAND; ProcessStartupInformation=$startup}; "
                        "$r | Select-Object ProcessId,ReturnValue | ConvertTo-Json -Compress",
                        NIGHTLY_COMMAND=subprocess.list2cmdline(
                            [
                                shutil.which("pwsh"),
                                "-NoProfile",
                                "-WindowStyle",
                                "Hidden",
                                "-File",
                                str(starter),
                            ]
                        ),
                    )
                )
                if launched["ReturnValue"]:
                    raise RuntimeError(f"Restart worker dispatch failed: {launched}")
                result = {"worker_pid": launched["ProcessId"]}
            elif sys.platform == "darwin":
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
                result = {"worker_pid": process.pid}
            else:
                unit = f"codex-nightly-finish-{run.name}"
                subprocess.run(
                    [
                        "systemd-run",
                        "--user",
                        "--no-block",
                        f"--unit={unit}",
                        "--collect",
                        "--property=Type=oneshot",
                        f"--property=StandardOutput=append:{run / 'restart.log'}",
                        f"--property=StandardError=append:{run / 'restart.log'}",
                        *command,
                    ],
                    check=True,
                    stdout=log,
                    stderr=log,
                )
                result = {"unit": unit}
    except (OSError, subprocess.SubprocessError) as error:
        result = {"status": "error", "reason": str(error)}
        atomic_json(run / "restart.json", result)
        record_stage(run, "restart", "error", result=result)
        raise
    record_stage(run, "restart", "scheduled", **result)
    return result


def finish(run, check=False):
    from contextlib import contextmanager

    record = require_published(run)
    package = Path(record["stages"]["verify"]["package"])
    if record["profile"] == "windows":
        from scripts.windows.activation import lock_file
    else:

        @contextmanager
        def lock_file(path):
            import fcntl

            with path.open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield

    with lock_file(run / "restart.lock"):
        saved = run / "restart.json"
        if not check and saved.exists():
            previous = json.loads(saved.read_text())
            if previous["status"] in ("restarted", "already-current", "not-running"):
                report_result(run, record, previous)
                return previous
            shutil.copy2(saved, run / f"restart-attempt-{time.time_ns()}.json")
        deadline = time.monotonic() + 1800
        if record["profile"] == "windows":
            from scripts.windows.activation import restart

            action = partial(restart, package, check_only=check, deadline=deadline)
        elif record["profile"] == "macos":
            from scripts.macos.restart_if_idle import restart

            action = partial(restart, package, check_only=check, deadline=deadline)
        else:
            spec = importlib.util.spec_from_file_location(
                "linux_restart", ROOT / "scripts/devbox/restart-if-idle.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            action = partial(
                module.restart, check_only=check, package=package, deadline=deadline
            )
        while True:
            try:
                result = action()
            except Exception as error:
                result = {"status": "error", "reason": str(error)}
            if check:
                return result
            atomic_json(run / "restart.json", result)
            record_stage(run, "restart", result["status"], result=result)
            if result.get("reason") != "Tasks are busy" or time.monotonic() >= deadline:
                report_result(run, record, result)
                return result
            time.sleep(15)


def report_result(run, record, result):
    if record["profile"] == "windows":
        return
    thread = record.get("coordinator_thread")
    if not thread:
        return
    receipt = run / "notification.json"
    if receipt.exists():
        previous = json.loads(receipt.read_text())
        if previous["status"] == "sent" and previous.get("result") == result:
            return
    from scripts.codex_package.rpc import notify

    try:
        asyncio.run(
            notify(
                thread,
                "Nightly idle restart result. Saved evidence: "
                f"{run / 'restart.json'}\n" + json.dumps(result),
            )
        )
    except Exception as error:
        atomic_json(
            receipt, {"status": "error", "reason": str(error), "result": result}
        )
        raise
    atomic_json(receipt, {"status": "sent", "result": result})
