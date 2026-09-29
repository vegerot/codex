# macOS

Existing 06:00 schedule. Run `python3 scripts/macos/build_backend.py` first.
If it does not select SCM, leave history and installed package unchanged and
record a skipped update. No automatic local fallback or VPN reconfiguration.
Both code.byted.org and cloud.bytedance.net must route over utun interfaces.
Recheck before submission/download if connectivity changes.

SCM repository 591837, existing Codebase mirror, immutable codex/macos-builds/<SHA>
ref. Resolve the latest stable upstream base version before submission. Submit
with CUSTOM_CODEX_TARGET=aarch64-apple-darwin and CUSTOM_CODEX_BASE_VERSION set;
SCM's x86_64 slot describes the worker, not the package target. Reuse only artifacts
matching exact SHA, target and version. Keep build-scm.sh and build-scm-macos.py.
Use scripts/macos/install_scm.py for acquisition, voice relocation and signing.
Verify voice manifest, signatures, CLI/host/voice source agreement and App Server.
Restart only after validation and publication, independently of the nightly task.
The CLI and its managed daemon both use the verified source-built package.
Keep launchctl CODEX_CLI_PATH unset so native ChatGPT uses its official bundled
App Server. Do not enable desktop local-daemon attachment. Nightly activation
and idle restart apply to the CLI daemon, not ChatGPT's separate App Server. Never control
com.openai.codex directly; use App Mirror when UI inspection is necessary.

Native developer builds package CLI and Code Mode without adding the SCM voice
toolchain. TODO: simplify native/SCM voice packaging once the toolchain is shared.
