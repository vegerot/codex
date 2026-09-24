Use this task as the coordinator. The user explicitly authorizes a subagent
for each nightly build. Spawn one with `fork_turns="none"`, providing only the
source repository, this run directory, and an instruction to read and execute
the run directory's saved `prompt.md`. Do not pass this conversation's history.
Use the normal inherited model unless the user explicitly selects another.

Before spawning, inspect this run directory for `worker-id.txt` and `report.md`.
If a worker already exists, follow that worker instead of starting a duplicate.
Record the spawned agent ID in `worker-id.txt`. Do not overlap source updates
with another unfinished nightly worker; wait for that worker first.

The worker owns source synchronization, conflict resolution, SCM submission and
polling, verified installation, publication, and the feature audit. It must save
its final report to `report.md` in the run directory, including failures, and
retain command/build evidence there. Its subagent task retains the full tool
transcript. It must never restart the daemon or use notify.py to send a report.
It returns the result through normal subagent completion.

Wait for the worker to finish. Review its report and evidence, preserving failures
and uncertainties. If it fails without a report, save an honest failure report
yourself. If this run already has `restart.json`, report that outcome without
scheduling another restart check.

At the very end, only if `restart.json` is absent, the worker is finished, and
`report.md` exists, schedule
the external finisher before sending your final response:

`systemd-run --user --unit=codex-nightly-finish-<run-directory-name> --on-active=20s --timer-property=AccuracySec=1s --property=Type=oneshot --collect /usr/bin/python3 <source-repository>/scripts/devbox/finish.py --run-dir <run-directory>`

Use actual absolute paths. If that unit is already scheduled or running, retain
it. The finisher checks all tasks, including this task and the worker; never
exclude either. It waits up to 30 minutes for idle, uses the graceful restart
helper, saves `restart.json`, and posts the restart result here. It survives the
daemon stopping. If scheduling fails, report that restart remains pending;
never restart directly from this task.

Announce the build result and noteworthy features concisely as your final
response, leading with sacrificed behavior or significant preservation
uncertainty. For a newly scheduled finisher, say the idle restart check is
scheduled, not completed. For a completed run, report its saved restart outcome.
Ending your response allows this task to become idle. A restart-result
notification is informational and must not trigger another build or restart.
