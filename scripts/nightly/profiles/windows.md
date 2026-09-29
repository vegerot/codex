# Windows

Native Windows PowerShell, existing 03:00 heartbeat. Never use Bash. Use the native
MSVC builder in scripts/windows/build.py through root build.py, retaining its cache,
resource monitor and 24-job limit. Build only committed source and a complete
package including command runner, sandbox setup and sandbox service. Verify in
the final versioned directory; do not rename a directory after executing its files.
Use Sapling; Git source operations are allowed only if Sapling is incompatible.
Build and publish only: do not change launchers, junctions, daemon settings, app
configuration or running processes. Activation and restart are not requested.
