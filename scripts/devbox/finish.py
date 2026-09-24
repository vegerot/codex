#!/usr/bin/env python3
"""Wait for idle after the coordinator responds, then report the restart outcome."""

import argparse
import fcntl
import json
import subprocess
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
THREAD = "01a0cb94-2040-7fb0-a0b9-87132ed0aecc"


def finish(run_dir):
    if not (run_dir / "report.md").is_file():
        raise RuntimeError("The worker must finish and save report.md before restart")
    with (run_dir / "finish.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result_path = run_dir / "restart.json"
        if result_path.exists():
            return
        deadline = time.monotonic() + 1800
        with (run_dir / "restart.log").open("a") as log:
            while True:
                process = subprocess.run(
                    ["uv", "run", "--script", str(SCRIPTS / "restart-if-idle.py")],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                try:
                    result = json.loads(process.stdout)
                except ValueError:
                    result = {
                        "status": "error",
                        "reason": process.stderr or process.stdout,
                    }
                log.write(json.dumps(result) + "\n")
                log.flush()
                if (
                    result.get("status") != "deferred"
                    or result.get("reason") != "Tasks are busy"
                ):
                    break
                if time.monotonic() >= deadline:
                    result["reason"] = (
                        "Tasks remained busy for 30 minutes; restart still pending"
                    )
                    break
                time.sleep(15)
        result_path.write_text(json.dumps(result, indent=2) + "\n")
        subprocess.run(
            [
                "uv",
                "run",
                "--script",
                str(SCRIPTS / "notify.py"),
                "--thread",
                THREAD,
                "--message",
                "Nightly idle restart result. Announce concisely; do not build or restart again. "
                f"Saved result: {result_path}\n\n" + json.dumps(result),
            ],
            check=True,
            timeout=180,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    finish(parser.parse_args().run_dir)
