# Personal devbox builds

Linux-only orchestration for the personal fork. Build entry points stay at the
repository root: `build.py` builds locally (macOS or Linux), while `build-scm.sh`
invokes `build.py --scm` to build and package on SCM workers. This directory owns the
devbox scheduler and installation workflow, not another compiler implementation.
SCM runs its configured script path through Bash and has no entry-point argument
field, so the small shell wrapper installs the pinned Rust toolchain and selects
the Python script's SCM mode.
The Linux SCM mode installs `libcap-dev` on the worker when `pkg-config` cannot
find libcap, then verifies it before compiling the required `bwrap` executable.

Remote Control enrollment and the App Server initialization user-agent advertise
the version from `codex-package.json`, using the same `BuildInfo` API as the
execution server. Local `build.py` builds keep the Cargo
workspace version (normally `0.0.0`) and write the upstream-based development
version into the package metadata. Thus local `codex --version` and the Remote
Control package version can differ intentionally. Local builds do not stamp or
restore Cargo manifests. Run the installed package's `bin/codex`, not a bare
Cargo output, to supply the Remote Control version.

SCM retains its existing disposable-checkout stamping and matching executable,
manifest, and build-metadata checks. Those packages also advertise their manifest
version. Restart App Server after installation; package build information is
cached at startup.

- `run.py`: runs the saved `prompt.md`, stores reports/events under
  `~/.local/state/codex-rebuild`, and sends the completed report through `notify.py`.
  After the build task exits and before notification, `restart-if-idle.py` checks
  for a verified package change and all loaded task statuses/queues. Busy,
  approval/input-waiting, queued, or unknown states defer restart. SIGHUP drains
  work that races the check without force-killing it, then the separate
  `codex-rebuild-daemon-start.service` starts the selected package. The report
  includes the outcome; busy runs leave restart pending until a later run.
  `uv run --script scripts/devbox/restart-if-idle.py --check` only inspects.
  `python3 scripts/devbox/run.py --check` runs a no-change scheduler smoke test.
- `install-scm.py`: downloads an exact-commit SCM artifact and verifies hashes,
  version, bwrap, V8 execution, and doctor. `--install` selects it for both CLI
  and managed daemon without restarting active tasks. Without that flag it only
  downloads/verifies; this replaces the original pilot download script.
- `test-host.py`: exercises the actual packaged Code Mode host protocol.
- `watch_memory.py`: optional Linux RSS/PSS/available-memory recording around a
  command. Set `BUILD_LOG_DIR` to a nonexistent directory before invoking it.
  The command must keep its children in its process group. Do not wrap the
  ordinary build helpers, which create separate groups and already contain
  their own memory abort guards and retry policies.
- `test_build_helper.py` and `test_install_scm.py`: focused local tests, with
  mocked platform routing and synthetic memory pressure rather than real builds.

Run tests from the repository root:

```sh
uv run --with websockets==15.0.1 python -B -m unittest discover --start-directory scripts/devbox --pattern 'test_*.py'
```

The installed `~/.local/share/codex-rebuild` symlink points to this directory.
The systemd user service and timer symlink to the corresponding files here;
`codex-rebuild-daemon-start.service` must also be linked into the user unit directory.
the enabled timer symlink points to `~/.config/systemd/user/codex-rebuild.timer`.
After changing units, run `systemctl --user daemon-reload`. The timer remains
daily at 09:00 America/Los_Angeles, including daylight-saving transitions.

The notifier uses `uv run --script` with a pinned WebSocket dependency and sends
reports to task `01a0cb94-2040-7fb0-a0b9-87132ed0aecc`. Change that thread argument
in `run.py` to choose a different report destination. Preserve the existing
App Server and login environment; installing a package does not restart it.
Each run reads its prompt once; changing the saved prompt does not steer an
already-running task.

Operational code lives here. Historical measurements and phone diagnostics
remain in the `~/ai-conversations` repository under `codex/source-builds/`.
