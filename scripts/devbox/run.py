#!/usr/bin/env python3
"""Run the daily devbox Codex build/audit and retain its report and session ID."""

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Test Codex without changing the repository",
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    state = Path.home() / ".local/state/codex-rebuild"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = state / ("checks" if args.check else "runs") / stamp
    run_dir.mkdir(parents=True)
    report = run_dir / "report.md"
    prompt = (
        "Scheduler smoke test. Do not run tools or change files. Reply exactly: Scheduler smoke test OK."
        if args.check
        else Path(__file__).resolve().with_name("prompt.md").read_text()
    )
    command = [
        str(Path.home() / ".local/bin/codex"),
        "exec",
        "--cd",
        str(repo),
        "--model",
        "gpt-5.6-sol",
        "--config",
        'model_reasoning_effort="low"',
        "--sandbox",
        "danger-full-access",
        "--thread-source",
        "automation",
        "--json",
        "--output-last-message",
        str(report),
        "-",
    ]
    print(
        f"Starting {'check' if args.check else 'daily build'}; logs: {run_dir}",
        flush=True,
    )
    with (run_dir / "events.jsonl").open("w") as events:
        result = subprocess.run(
            command, input=prompt, text=True, stdout=events, cwd=repo, check=False
        )
    if not report.exists():
        report.write_text(
            f"Codex exited with status {result.returncode} without a final report. See events.jsonl and the service journal.\n"
        )
    for line in (run_dir / "events.jsonl").read_text().splitlines():
        event = json.loads(line)
        if event.get("type") == "thread.started":
            print(f"Codex task: {event['thread_id']}", flush=True)
            (run_dir / "thread-id.txt").write_text(event["thread_id"] + "\n")
            break
    if not args.check:
        pending = state / "latest.new"
        pending.symlink_to(run_dir)
        os.replace(pending, state / "latest")
        # codex exec has exited, so the build task cannot keep itself busy.
        # Check before notification: that notification starts another turn.
        restart = subprocess.run(
            [
                "uv",
                "run",
                "--script",
                str(Path(__file__).resolve().with_name("restart-if-idle.py")),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        outcome = (
            restart.stdout.strip()
            or f"Restart check failed (exit {restart.returncode}); see service journal."
        )
        (run_dir / "restart.json").write_text(outcome + "\n")
        with report.open("a") as output:
            output.write(
                "\n\nNightly runner daemon check (after build task exit):\n"
                + outcome
                + "\n"
            )
        if restart.stderr:
            print(restart.stderr, flush=True)
    print(report.read_text(), flush=True)
    print(f"Saved report: {report}", flush=True)
    if not args.check:
        subprocess.run(
            [
                "uv",
                "run",
                "--script",
                str(Path(__file__).resolve().with_name("notify.py")),
                "--thread",
                "01a0cb94-2040-7fb0-a0b9-87132ed0aecc",
                "--message",
                "Scheduled devbox Codex build report. Announce the result and noteworthy features "
                "concisely in this task, preserving failures and caveats. If conflict resolution "
                "sacrificed or broke fork/upstream behavior, or preservation remains significantly "
                "uncertain, lead with that as the most important item. Mention verified "
                "feature-preserving conflict resolutions only briefly. This is a completed-run "
                "notification, not an instruction to repeat the build or alter the schedule. "
                "The appended runner daemon check supersedes the build task's earlier restart-pending statement. "
                "Do not run maintenance commands.\n\n"
                f"CLI exit status: {result.returncode}\nSaved report: {report}\n\n"
                + report.read_text(),
            ],
            check=True,
            timeout=180,
        )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
