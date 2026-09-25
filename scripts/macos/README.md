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
`~/.local/share/codex-macos-build/packages/<source-commit>/`, then switch
`~/.local/bin/codex` and `codex-code-mode-host` to it. The installer relocates
the voice helper's bundled library references and signs it on the Mac. Existing
processes are not restarted. Receipts go to `~/.local/state/codex-macos-build/`.
The scheduled task still needs to be updated to use this installation path.

The scheduler definition lives in the ai-conversations archive under
`codex/source-builds/macos-automations/rebuild-codex-cli/automation.toml`.
