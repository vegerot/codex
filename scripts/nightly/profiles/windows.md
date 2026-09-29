# Windows

Native Windows PowerShell, existing 05:00 heartbeat. Never use Bash. Use the native
MSVC builder in scripts/windows/build.py through root build.py, retaining its cache,
resource monitor and 24-job limit. Build only committed source and a complete
package including command runner, sandbox setup and sandbox service. Verify in
the final versioned directory; do not rename a directory after executing its files.
Use `sl.exe` in PowerShell (`sl` is a Set-Location alias); Git source operations are allowed only if Sapling is incompatible.
Build and publish only: do not change launchers, junctions, daemon settings, app
configuration or running processes. Activation and restart are not requested. The desktop app uses its official
bundled executable with no CODEX_CLI_PATH override. Preserve that choice; do not
point it at the personal build.

Build command: `python build.py --commit <SHA> --run-dir <run>` (add `--jobs 24`).
