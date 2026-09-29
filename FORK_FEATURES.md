# Fork changes compared with main

Brief inventory of the current fork’s behavior changes and build tooling. Related
fixes are grouped together rather than listed once per commit.

Reviewed 2026-09-28: fork `9bf534ddc805` against locally recorded
`upstream/main` (`1b1835f751eb`), covering 26 fork commits. This describes source
changes, not which version is installed or which scheduled tasks are enabled.

## Runtime changes

- **More timing diagnostics:** the terminal’s existing runtime metrics include
  synchronous hook counts/duration and local command counts/duration. Inference
  traces record request start, response creation, first model delta, completion,
  and server timestamps when supplied, including WebSocket responses.
  [Sources](codex-rs/otel/src/metrics/runtime_metrics.rs) ·
  [Trace fields](codex-rs/rollout-trace/src/model/conversation.rs)
- **Stable context usage during compaction:** retain the displayed usage until
  compaction completes, then apply the deferred update; manual compaction no
  longer clears it early. [Source](codex-rs/tui/src/chatwidget/compaction.rs)
- **User skill directory:** bundled skill creation/installation guidance and
  installer/listing scripts use `~/.agents/skills`; Codex-managed system skills
  remain under `$CODEX_HOME/skills/.system`.
  [Source](codex-rs/skills/src/assets/samples/skill-installer/SKILL.md)
- **Correct personal-build identity:** Remote Control enrollment and App Server
  initialization use the package version. Metrics strip `+build` metadata from
  version tags so development versions do not invalidate telemetry.
  [Details](scripts/devbox/README.md) · [Metric tags](codex-rs/otel/src/metrics/tags.rs)
- **Quiet Windows helpers:** pipe-based subprocesses and the Code Mode host do
  not open console windows under a detached daemon; interactive terminals keep
  their separate terminal path. [Source](codex-rs/utils/pty/src/child_command.rs)

## Build and maintenance tooling

- **Personal local builds:** [`build.py`](build.py) rebuilds matching CLI and Code
  Mode binaries on macOS/Linux using matching V8 inputs and an existing package;
  Linux includes bubblewrap and memory-aware build concurrency.
- **SCM build-service packages:** versioned Linux packages and cross-compiled
  Apple Silicon macOS packages, with exact-source verification/install helpers.
  Linux includes bubblewrap; macOS includes a matching voice host/runtime,
  library relocation/signing, and VPN-aware backend selection. The Mac installer
  selects the nightly for CLI and daemon, disables upstream automatic updates,
  and restarts after publication once all tasks become idle.
  [Linux details](scripts/devbox/README.md) · [Mac details](scripts/macos/README.md)
- **Devbox nightly workflow:** repository-owned 5 AM Pacific scheduling, dispatch
  through an existing Codex task, verified package installation, saved run
  evidence, and daemon restart after all tasks become idle.
  [Details](scripts/devbox/README.md)
- **Native Windows builds:** `build.py` selects a Windows backend that packages
  committed source, records CPU/memory usage, and verifies the CLI, Code Mode,
  App Server, and sandbox helpers before saving a package and receipt.
  [Details](scripts/windows/README.md)
- **Source-build instructions:** use package assembly to fetch matching V8
  artifacts and launch the packaged executable. [Guide](docs/install.md)

- **Shared nightly workflow:** four platform profiles use one missing-patch replay
  procedure, committed helper snapshots, complete packages, and separate build,
  verification, activation, publication and restart records. Unix restarts wait
  for idle after publication; Windows remains build-only. A host-local status
  command reports selected and running packages. [Operations](scripts/nightly/README.md)

## Keeping this list current

Update this file in the same change whenever fork behavior or build workflows
change. After rebasing onto main, remove differences now provided by upstream
and refresh the reviewed revisions. Keep entries brief and link to details.
Compare the current stack and net diff with:

```sh
sl log --rev 'only(., upstream/main)' --template '{node|short} {desc|firstline}\n' --pager=never
sl diff --rev upstream/main --stat --pager=never
```
