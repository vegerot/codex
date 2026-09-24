#!/usr/bin/env python3
"""Queue the nightly build in the user's existing coordination task."""

import argparse
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

THREAD = "01a0cb94-2040-7fb0-a0b9-87132ed0aecc"
SCRIPTS = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="Check task access without queuing a build"
    )
    args = parser.parse_args()
    command = ["uv", "run", "--script", str(SCRIPTS / "notify.py"), "--thread", THREAD]
    if args.check:
        subprocess.run([*command, "--check"], check=True, timeout=180)
        return
    state = Path.home() / ".local/state/codex-rebuild"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = state / "runs" / stamp
    run_dir.mkdir(parents=True)
    (run_dir / "prompt.md").write_text((SCRIPTS / "prompt.md").read_text())
    message = (
        "Scheduled devbox Codex build request. Coordinate this run here using a subagent; "
        "this is a build trigger, not a completed-run notification.\n\n"
        f"Run directory: {run_dir}\nSource repository: {SCRIPTS.parents[1]}\n\n"
        + (SCRIPTS / "coordinator.md").read_text()
    )
    (run_dir / "request.md").write_text(message)
    with (run_dir / "dispatch.log").open("w") as log:
        subprocess.run(
            [*command, "--message", message],
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=180,
        )
    pending = state / "latest.new"
    pending.symlink_to(run_dir)
    os.replace(pending, state / "latest")
    print(f"Queued nightly build in task {THREAD}; run records: {run_dir}")


if __name__ == "__main__":
    main()
