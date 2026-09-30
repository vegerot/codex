# Personal nightly builds

The maintained build code and shared instructions live in this repository.
Read [workflow.md](workflow.md) and the selected [profile](profiles/). Automation
registries stay where their existing schedulers read them. Their prompts only
select this workflow/profile; do not symlink individual task directories.

`python3 scripts/nightly.py init --profile macos|devbox|debian|windows` creates a
UTC run directory under `~/.local/state/codex-nightly/<profile>/runs/`. It saves
exact instructions, instruction revision, and `run.json`. Use `source --run-dir
<run> --commit <SHA>` after reconciliation. Build helpers execute from committed
source; record build/helper and instruction revisions separately. Keep logs,
artifact metadata, final hashes, doctor output and report.md with the run.

Local root builds require `python3 build.py --commit <SHA> --run-dir <run>`;
Windows also accepts `--jobs 24`. Debian uses `scripts/debian/build.py` with the
same arguments. SCM retains `build-scm.sh` and the platform installer, now with
`--commit <SHA> --version-id <ID> --run-dir <run>`. Installers stage and verify;
selection is a separate operation. Complete packages reuse compiler/resource
caches; packaging never recompiles Rust. Native Mac builds currently omit SCM's
voice runtime; see the Mac profile TODO.

`verify --profile <profile> --run-dir <run> --package <package>` writes final
verification evidence. `activate --profile <profile> --run-dir <run>` selects that
verified CLI and managed-daemon package under the install lock. Windows uses a
separate codex.cmd launcher and user PATH; Unix uses symlinks. It never restarts.
`record --stage build|publish --status success|failed|skipped --evidence <JSON>
--run-dir <run>` records observed outcomes. Source synchronization/publication
remain agent-directed; scripts do not guess which patches to drop or rebase.

After successful publication, `restart --run-dir <run>` starts an independent
worker from a saved copy of the scripts. Linux dispatch returns immediately so
the coordinating task can become idle; worker output is saved in restart.log.
It checks all tasks/queues, including the
nightly task, for up to 30 minutes. A busy daemon stays pending until a subsequent
nightly/manual retry. `restart --run-dir <run> --check` inspects without signaling.
Linux uses pidfd and the user `codex-nightly-daemon-start.service` linked from
this directory (install it on Debian and Devbox); Mac verifies PID
identity and sends graceful SIGHUP. Windows uses a hidden worker and the managed
daemon shutdown endpoint, never force termination. Neither force-kills work. Windows activates the verified source CLI and its separate daemon; desktop packages, settings and app-owned processes remain untouched.

`status --profile <profile> [--json]` is host-local: latest attempt, latest verified
package, each stage, selected CLI/daemon and running version. A failed attempt
does not replace latest-verified. Old state/packages are retained as historical
records; there is no legacy migration/parser. Reverify an existing package to
establish the new baseline. A selected package is not proof the running server
loaded it.

Devbox keeps its 03:00 Pacific systemd timer. macOS keeps 06:00, Debian
04:00 and Windows 05:00 in their existing task registries. No new recurring timers.
Reload systemd after unit changes and inspect its next trigger. Validate Debian
on native Debian, not WSL; keep native desktop runtimes separate from source CLI activation on Windows.
