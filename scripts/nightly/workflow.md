# Nightly Codex workflow

Read this file and the selected profile before starting. Preserve unrelated work,
untracked files, installed packages, and caches. Keep the existing schedule.
Snapshot these instructions and the profile in the run directory; retain commands,
logs, failed attempts, verification evidence, and report.md there. Never save credentials.

## Reconcile source (agent-directed)

Record the local tip, fetched upstream tip, previous verified installed source,
resolved CLI path/version/features, and clean tracked status. Stop for unrelated
tracked edits or unfinished operations. Resume an automation-owned rebase only
when its run evidence proves ownership, original tips, and pending changes.

1. Verify default points to vegerot/codex and upstream to openai/codex. Pull
   `sl pull default --bookmark fork`; freeze the full fetched origin/fork SHA.
   This is the expected publication tip, not a moving bookmark.
2. Enumerate local commits not ancestors of that tip. Compare their complete
   binary Git-format diffs (`sl diff --git --binary --change REV`) with candidate
   remote patches using `git patch-id --verbatim` on stdin. Git here is a hash
   utility; use Sapling for repository operations. Stable patch IDs, subjects,
   bodies, and changed paths are candidate hints, never proof of equivalence.
3. Inspect current remote behavior for every apparent match. Account for amended,
   split, squashed, and reverted changes. A matching historical patch does not
   prove it survives at the remote tip. Preserve intentional remote removals;
   port only the missing delta of an amended local patch. Do not add Change-Ids.
4. Save a mapping of local SHA, remote counterpart/evidence, and disposition
   (already present, replay, port delta, or intentional removal) in the run.
   Replay only explicitly selected missing revisions, in dependency order, with
   `sl rebase --rev <selected-revset> --dest <frozen-tip> --tool internal:fail`.
   Never use blanket `sl rebase --base .`. If none remain, `sl goto <frozen-tip>`.
5. Pull upstream/main, synchronize the fork main bookmark, then use the same
   equivalence procedure to select surviving fork patches for upstream replay.
   Preserve source dates using the existing Sapling configuration.

Resolve routine conflicts autonomously by reading base, both sides, original
patches, callers and tests. Preserve both feature sets. Do not preapply later
patches wholesale while replaying an earlier commit. Verify the final behavior,
not only conflict markers. Lead the report with any sacrificed behavior or
significant preservation uncertainty. Never delete tests to make a conflict pass.

## Build, verify, activate, publish, restart

Freeze one full committed source SHA with no tracked changes. Follow the profile
for backend selection before changing history, and again before submission.
Compile and package from that snapshot, including its own helpers. Preserve stable
cache paths and unchanged source mtimes. Stamp CLI and package versions together
in the disposable source. Build complete packages; never mutate an installed one.

Reconcile uncertain submissions by exact source and target before retrying.
Automatically diagnose and repair routine source, dependency and workflow failures;
commit scoped repairs, freeze a new SHA and record each attempt. Never bypass
required validation. Stop when credentials/infrastructure or a user decision is
needed, or repeated failures have no supported new approach.

Verify the full package: source, target, nonzero version, resources, checksums,
CLI execution, real V8 execution, App Server initialization/version, and doctor.
Keep doctor warnings distinct from failures. Verify platform requirements in the
profile. Record downloaded artifact hashes separately from final package hashes
when relocation/signing changes files. Compilation success alone is insufficient.

On Unix, select only a verified versioned package for CLI and managed daemon,
discovering the daemon namespace. Under its install lock preserve settings,
disable upstream automatic updates and remove stale latest-release markers.
Record activation separately from the running daemon. Windows is build-only.

Confirm HEAD still equals the tested SHA with no new tracked changes. Publish
exactly that SHA with an explicit expected-tip lease:
`git push --force-with-lease=refs/heads/fork:<fetched-tip> <verified-default-remote> <tested-SHA>:refs/heads/fork`.
Git is used solely for the explicit lease. Verify the remote ref afterward. If
concurrent publication rejects the lease, reconcile, rebuild and verify the combined
source before retrying. Never force-push unconditionally.

Only after build, verification, Unix activation, and publication succeed, arrange
an independent idle restart worker. It checks every loaded task and queue, including
the coordinator. Active ephemeral tasks block; idle ephemeral tasks need no queue
lookup. Never force-kill work or restart ChatGPT-owned processes. Wait at most
30 minutes, then leave restart pending for the next nightly/manual retry. Do not
restart a superseded package. Verify running executable identity and version.

## Report

Compare against the previous verified installed source, not the old checkout tip.
Inspect source registries, schemas, history and runtime output. Rank useful findings:
stable/default-on improvements; workflow/debugging/observability; experimental flags;
then developer/protocol changes. Explain entry point, default/maturity, usefulness,
and supporting SHA/path. Do not enable flags or claim server-gated behavior from
`features list`. Distinguish observation, inference and untested behavior.

Save report.md including source/version, target/backend, durations, jobs/memory/cache
observations, artifact/package paths, verification, publication and restart states.
Report failed attempts honestly; do not infer speedups across unlike cache/source
states. No extra timers, coordinator migration or stacked PR workflow in this change.

## Run commands

Create the run with `python3 scripts/nightly.py init --profile <profile>` unless
the coordinator already supplied one. Read its saved workflow.md/profile.md.
After reconciliation, run `python3 scripts/nightly.py source --run-dir <run>
--commit <SHA>`. New repaired source means a new run linked in the report. The source command
snapshots that revision's helpers in <run>/helpers. Use those saved scripts for
SCM download, verification, activation and restart, not the moving working copy.
Use `record --run-dir <run> --stage build --status success --evidence <JSON>`
only after an actual successful build; retain the build's source/target/logs in
that JSON. Installers acquire/stage artifacts; then use `verify --profile
<profile> --run-dir <run> --package <final-package>` and, on Unix,
`activate --profile <profile> --run-dir <run>`.
After observing the published remote ref equals the tested SHA, save that evidence
as JSON and `record --run-dir <run> --stage publish --status success --evidence
<JSON>`. The coordinator finally calls `restart --run-dir <run>` and ends its turn
so it can become idle. `status --profile <profile> [--json]` reports host-local
attempt, verification and live daemon state. Failed/skipped stages use their actual
status; never manufacture successful evidence to bypass restart prerequisites.
