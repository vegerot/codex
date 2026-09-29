"""Bounded idle restart of the package recorded by a published Unix run."""

from functools import partial
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from scripts.codex_package.nightly import ROOT, atomic_json, record_stage


def require_published(run):
    record = json.loads((run / "run.json").read_text())
    if record["profile"] == "windows":
        raise RuntimeError("Windows restart is not requested")
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
        "--system-certs",
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
    with (run / "restart.log").open("a") as log:
        if sys.platform == "darwin":
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
                    f"--unit={unit}",
                    "--collect",
                    "--property=Type=oneshot",
                    *command,
                ],
                check=True,
                stdout=log,
                stderr=log,
            )
            result = {"unit": unit}
    record_stage(run, "restart", "scheduled", **result)
    return result


def finish(run, check=False):
    import fcntl

    record = require_published(run)
    package = Path(record["stages"]["verify"]["package"])
    with (run / "restart.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        deadline = time.monotonic() + 1800
        if record["profile"] == "macos":
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
            result = action()
            atomic_json(run / "restart.json", result)
            record_stage(run, "restart", result["status"], result=result)
            if (
                check
                or result.get("reason") != "Tasks are busy"
                or time.monotonic() >= deadline
            ):
                return result
            time.sleep(15)
