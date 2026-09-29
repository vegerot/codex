# Mac nightly build helpers

The Mac's scheduled task chooses the build backend with
`python3 scripts/macos/build_backend.py`. SCM is selected only when both Codebase
and SCM route through macOS VPN (`utun`) interfaces. The script does not change
network settings. The existing `./build.py` is the local path.

For an exact-source SCM build, push the source to `max.coplan/codex`, resolve the
stable upstream version before submission, and supply:

```json
{"CUSTOM_CODEX_TARGET":"aarch64-apple-darwin","CUSTOM_CODEX_BASE_VERSION":"<stable-version>"}
```

`build-scm.sh` selects `build-scm-macos.py` for that target. With no target override,
it retains the existing Linux SCM build. The Mac path cross-compiles the CLI,
Code Mode host, and voice host from one commit with Zig, SDK 15.5, and the
prepared voice SDK. It includes the matching voice runtime in the package.

On the Mac, verify/download without installation:

```bash
python3 scripts/macos/install_scm.py --version-id <id> --commit <full-source-sha>
```

Add `--install` to prepare and place the complete package under
`~/.local/share/codex-macos-build/packages/<source-commit>/`. After verification,
the installer selects it for both CLI launchers and the managed daemon, disables
the daemon's upstream automatic updater, and removes its latest-release marker.
It preserves other daemon settings and the existing package/PID namespace.
Selection uses the upstream install lock; an in-flight installer causes a retryable
failure rather than competing writes. Each link is replaced atomically.

The installer relocates/signs the voice helper on the Mac and saves its receipt
under `~/.local/state/codex-macos-build/`. An independent restart worker checks all
loaded tasks and their queues, including the nightly task itself. Idle ephemeral
tasks have no queue; active ones still block restart. The worker waits up to 30
minutes for idle, sends SIGHUP to drain any raced work without force-killing it,
then starts and verifies the selected daemon version. `restart.json` and
`restart.log` record the outcome; selection alone does not mean restart completed.
ChatGPT's separate app-server processes are not restarted by this helper.

To reselect an already installed, verified package (no download/build):

```sh
python3 scripts/macos/activate.py --receipt ~/.local/state/codex-macos-build/scm-<id>.json --schedule-restart
```

To inspect restart readiness without signaling any process:

```sh
uv --system-certs run --script scripts/macos/restart_if_idle.py --receipt ~/.local/state/codex-macos-build/scm-<id>.json --check
```

The worker resolves `uv` before detaching and uses system TLS certificates, so it
does not depend on a scheduler shell's PATH initialization or a separate CA bundle.
Tests: `uv --system-certs run --with websockets==15.0.1 python -m unittest discover
--start-directory scripts/macos --pattern 'test_*.py'`.

The scheduler definition lives in the ai-conversations archive under
`codex/source-builds/macos-automations/rebuild-codex-cli/automation.toml`.
