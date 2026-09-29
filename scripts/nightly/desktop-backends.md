# Desktop backend selection

Desktop backends use official Codex on macOS, devbox and Windows. Personal
Debian is the exception and keeps the self-built backend. Terminal CLI builds
remain personal on all hosts. A self-built terminal client attached to an official
daemon retains its terminal rendering changes, but backend instrumentation comes
from official Codex.

## macOS

Remove the app executable override:

```sh
launchctl unsetenv CODEX_CLI_PATH
```

Quit and reopen ChatGPT when its tasks are idle. Without the override, this app
resolves its own bundled `codex-cli/CodexCLI.app/Contents/MacOS/codex`, including
matching helper runtimes. Do not point the desktop at `~/.local/bin/codex` or a
fixed version under `packages/standalone/releases`. The managed daemon also uses
an official package in `~/.codex/packages/app-server-daemon`, with automatic
updates enabled; local desktop sessions currently use a separate app-owned server.

## Devbox

Desktop SSH and Remote Control reach the shared managed daemon. Keep its official
package and upstream updater independent of `~/.local/bin/codex`, which remains
self-built. In the shared `.zshenv`, devbox login shells with
`CODEX_REMOTE_PAYLOAD` export
`CODEX_INSTALL_DIR=$HOME/.codex/packages/app-server-daemon/current/bin`. The desktop
SSH launcher prepends that directory to PATH for its bootstrap and proxy commands;
ordinary terminal shells keep the personal CLI. Personal Debian does not match
this host condition. Do not add a second Codex home or change history/authentication
paths.
Use `codex app-server daemon version` and the PID's `/proc/<pid>/exe` to verify
both selected and running binaries. Once installed in the dedicated daemon
namespace, `codex app-server daemon update` follows production updates; run it
when tasks are idle because manual updates can interrupt work.

## Windows, when available

Use native PowerShell. Clear the desktop executable override from both the user
environment and the current shell, then quit and reopen ChatGPT when idle:

```powershell
[Environment]::SetEnvironmentVariable('CODEX_CLI_PATH', $null, 'User')
Remove-Item Env:CODEX_CLI_PATH -ErrorAction SilentlyContinue
[Environment]::GetEnvironmentVariable('CODEX_CLI_PATH', 'Machine')
```

The last command should be empty. If it reports a machine-wide override, remove
that override from an elevated PowerShell window too. The desktop then resolves
its official bundled/registered executable and matching helpers. Keep the nightly
build task build-only. If Windows uses a managed daemon for desktop access, run
`codex app-server daemon update` when idle and verify its selected/running version;
if the old installation cannot migrate, inspect its actual package before changing
junctions. Do not guess a package path or replace the terminal launcher.

## Personal Debian, when available

Keep the self-built desktop App Server and daemon. Update the Codex working copy
to include this policy, then run the existing Debian nightly workflow. Its CLI and
daemon activation/restart remain enabled. No desktop executable reset is needed.
If the app owns an unmanaged App Server, quit/reopen its owner when idle and check
its loaded executable; a CLI launcher change alone does not restart that server.

## Nightly ownership

Mac/devbox activation changes only terminal CLI launchers. It preserves daemon
selection/settings/update markers and records daemon restart as `not_requested`.
Debian activation selects both CLI and daemon, disables its upstream updater and
retains publication-gated idle restart. Windows stays build-only. Build tasks must
not restore desktop overrides or attach a personal package to an official daemon.
