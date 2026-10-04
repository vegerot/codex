# Fork changes compared with main

Brief inventory of the current fork’s behavior changes and build tooling. Related
fixes are grouped together rather than listed once per commit.

Runtime inventory reviewed 2026-10-04 against `upstream/main`
(`afb436df8b70`); build workflows include the shared-nightly refactor and detached
Linux finisher. This describes source changes, not which version is installed
or which scheduled tasks are enabled.

## Runtime changes

- **More timing diagnostics:** the terminal’s existing runtime metrics include
  synchronous hook counts/duration and local command counts/duration. Inference
  traces record request start, response creation, first model delta, completion,
  and server timestamps when supplied, including WebSocket responses. Local
  timing and tool metrics remain visible even when excluded from Statsig export.
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
- **Quiet Windows Code Mode host:** the Code Mode host does not open a console
  window under a detached daemon. General pipe-based helper suppression is now
  provided upstream. [Source](codex-rs/code-mode/src/remote_session/connection.rs)

## Build and maintenance tooling

- **Personal local builds:** [`build.py`](build.py) rebuilds matching CLI and Code
  Mode binaries on macOS/Linux using matching V8 inputs and complete versioned
  packages;
  Linux includes bubblewrap and memory-aware build concurrency.
- **SCM build-service packages:** versioned Linux packages and cross-compiled
  Apple Silicon macOS packages, with exact-source verification/install helpers.
  Linux uses Offline versions and macOS uses Test versions to separate build timings.
  Linux includes bubblewrap; macOS includes a matching voice host/runtime,
  library relocation/signing, and VPN-aware backend selection. SCM version stamping
  accepts a stable release tag resolved by the authenticated submitter, so workers
  need no GitHub credentials for release lookup. Artifact acquisition
  and verification are separate from activation. Unix
  activation selects the package for CLI and daemon and disables upstream
  automatic updates; a separate worker restarts after publication and idle checks.
  Native Mac/Windows desktop apps retain their official bundled backends; remote
  devbox desktop connections share the source-built server.
  [Linux details](scripts/devbox/README.md) · [Mac details](scripts/macos/README.md)
- **Devbox nightly workflow:** repository-owned 3 AM Pacific scheduling, dispatch
  through an existing Codex task, verified package installation, saved run
  evidence, and daemon restart after all tasks become idle.
  [Details](scripts/devbox/README.md)
- **Native Windows builds:** `build.py` selects a Windows backend that packages
  committed source, records CPU/memory usage, and verifies the CLI, Code Mode,
  App Server, and sandbox helpers before saving a package and receipt. After
  verification, removes older Windows packages except the selected CLI and those
  still running. Migration files use CRLF to preserve official Windows database
  checksums, with a verification regression gate. Verified packages replace the
  separate CLI/daemon and cut over when idle; desktop runtime files stay official.
  [Details](scripts/windows/README.md)
- **Source-build instructions:** use package assembly to fetch matching V8
  artifacts and launch the packaged executable. [Guide](docs/install.md)

- **Consistent formatter line endings:** Bazel/Starlark files and justfile use
  explicit LF attributes, preventing Windows CRLF checkout sizes from producing
  false modified status after formatting. Nightly preflight can refresh index
  entries only after proving the affected files equal committed bytes.
  [Attributes](.gitattributes) · [Procedure](scripts/nightly/workflow.md)
- **Shared nightly workflow:** four platform profiles use one missing-patch replay
  procedure, committed helper snapshots, complete packages, and separate build,
  verification, activation, publication and restart records. Unix restarts wait
  for idle after publication and leave unmanaged App Servers untouched; Windows
  selects its source CLI and separate daemon while leaving the official desktop
  runtime unchanged. A host-local status
  command reports selected and running packages. Every nightly mirrors upstream
  main by exact commit SHA; fork-only changes stay on fork, never main.
  [Operations](scripts/nightly/README.md)

## Keeping this list current

Update this file in the same change whenever fork behavior or build workflows
change. After rebasing onto main, remove differences now provided by upstream
and refresh the reviewed revisions. Keep entries brief and link to details.
Compare the current stack and net diff with:

```sh
sl log --rev 'only(., upstream/main)' --template '{node|short} {desc|firstline}\n' --pager=never
sl diff --rev upstream/main --stat --pager=never
```
