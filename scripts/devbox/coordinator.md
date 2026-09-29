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

The user authorizes automatic repair of routine build and orchestration bugs,
including PATH, API compatibility, source integration, and package dependencies.
If a worker stops on a repairable failure, delegate the diagnosed repair and
continuation rather than treating its first failed attempt as final. Preserve
active work and feature/verification requirements; never bypass idle checks,
omit required package files, or weaken validation to manufacture success.
Report blockers requiring credentials, unavailable infrastructure, a user choice,
or repeated failures without a supported new approach. Briefly report repairs,
failed attempts, and any remaining uncertainty.

Wait for the worker to finish. Review its report and evidence, preserving failures
and uncertainties. If it fails without a report, save an honest failure report
yourself. If this run already has `restart.json`, report that outcome without
scheduling another restart check.

At the very end, only after build, verification, activation and publication
succeeded in run.json, run:

`python3 <source-repository>/scripts/nightly.py restart --run-dir <run-directory>`

This snapshots the helper scripts and starts an independent systemd worker. It
checks every task, including you, for up to 30 minutes. End your response to become
idle. Failed builds/publication must not schedule a restart. A busy deferral stays
pending for the next nightly or an explicit manual retry; no extra timer is added.

Announce the build result and noteworthy features concisely as your final
response, leading with sacrificed behavior or significant preservation
uncertainty. For a newly scheduled finisher, say the idle restart check is
scheduled, not completed. For a completed run, report its saved restart outcome.
Ending your response allows this task to become idle. A restart-result
notification reporting success or normal busy deferral is informational; do not
repeat successful work. An error notification authorizes diagnosing and fixing
the finisher, then retrying the same verified package after idle. Preserve the
failed restart.json under a distinct attempt filename before a deliberate retry;
never discard evidence or bypass the per-run lock. Retry failed notification
delivery without rerunning a successful restart.
