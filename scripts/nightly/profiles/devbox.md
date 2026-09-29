# Devbox

Linux x86_64; existing systemd schedule at 03:00 America/Los_Angeles.
Use SCM only, never local Rust compilation or Rust tests. Source/format and Python
helper tests are local; validate compiled artifacts from SCM.

Push the frozen SHA to the existing Codebase mirror's immutable
codex/builds/<SHA> ref. SCM repository max/coplan/codex, ID 591837, offline x86_64,
build-scm.sh, existing rust.compile.lyra image. Query versions by exact commit
before submitting; reuse matching successful builds or wait for running ones.
Use `bytedcli --json scm repo build --repo-id 591837 --commit <SHA> --type offline
--arch x86_64`. Poll every 30–60 seconds and save version ID and logs.
Before submission, use authenticated GitHub access on the submitter to list
`repos/openai/codex/git/matching-refs/tags/rust-v`, save the non-secret tag data,
and select the highest stable `rust-vX.Y.Z` tag. Pass that tag with
`--env '{"CUSTOM_CODEX_RELEASE_TAG":"<tag>"}'`; SCM must not need GitHub credentials
just to stamp the package version.

Keep the memory guard, 32-job cap, V8 resolver and source-built bwrap. Do not enable
optional patched zsh. Require 8 GiB free for download/staging. Use
scripts/devbox/install-scm.py for authenticated artifact acquisition. Keep tokens
in memory. Validate bwrap execution as well as the shared package checks.
The coordinator delegates the build worker using coordinator.md and schedules
an independent systemd finisher only after publication succeeds.
