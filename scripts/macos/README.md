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
it retains the existing Linux SCM build. The Mac path cross-compiles with Zig,
SDK 15.5, and target-specific V8 inputs; it clears the image's x86 native flags.

On the Mac, verify/download without installation:

```bash
python3 scripts/macos/install_scm.py --version-id <id> --commit <full-source-sha>
```

Add `--install` to update the two executables and package version in the existing
`codex-rs/target/codex-package-release` package. Resource symlinks and the CLI path
are preserved; running servers are not restarted. Replacement is per executable,
not atomic for the whole package. Receipts go to `~/.local/state/codex-macos-build/`.
The scheduled task runs the installed package's doctor and other final checks.

The scheduler definition lives in the ai-conversations archive under
`codex/source-builds/macos-automations/rebuild-codex-cli/automation.toml`.
