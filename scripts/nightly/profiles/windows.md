# Windows

Native Windows PowerShell, existing 05:00 heartbeat. Never use Bash. Use the native
MSVC builder in scripts/windows/build.py through root build.py, retaining its cache,
resource monitor and 24-job limit. Build only committed source and a complete
package including command runner, sandbox setup and sandbox service. The Windows
builder restores CRLF migration text before compilation to match official Windows
SQLx checksums; verification checks the first migration's official checksum.
Verify in the final versioned directory; do not rename it after executing its files.
Use sl.exe in PowerShell (sl is a Set-Location alias); Git source operations are
allowed only if Sapling is incompatible.

After verification, run python scripts/nightly.py activate --profile windows
--run-dir <run>. This selects the verified package for ~/.local/bin/codex.cmd and
the separate source CLI daemon. It prepends the launcher directory to user PATH.
Publish the tested source, then run python scripts/nightly.py restart --run-dir <run>.
The independent hidden worker checks loaded CLI tasks and queues, then sends one
graceful shutdown request and verifies the new daemon. Busy tasks defer cutover
for at most 30 minutes. Never force-kill work.

Native Windows desktop remains official: never replace files under AppData/Local/
OpenAI/Codex or AppData/Local/Programs/OpenAI/Codex, alter desktop overrides
CODEX_CLI_PATH or CODEX_APP_SERVER_USE_LOCAL_DAEMON, change app settings, or stop
ChatGPT/Codex desktop processes or their app-owned App Servers. Leave daemon
settings unchanged. CLI daemon selection and its own graceful cutover are allowed;
the native desktop must continue using its bundled backend, as on macOS.

Build command: python build.py --commit <SHA> --run-dir <run> --jobs 24.
Save selected CLI, managed daemon and actual running identities separately.
