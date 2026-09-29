# Desktop and CLI backend selection

The CLI runs all source-built agent code, including its managed App Server,
model/tool orchestration and Code Mode host. Native Mac/Windows desktop apps
use official backends. Personal Debian remains entirely source-built. Desktop
connections to the devbox use that host's source-built backend.

| Connection | Backend |
|---|---|
| Mac terminal CLI | Source-built managed App Server |
| Mac desktop, local project | Official app-owned App Server |
| Mac desktop, SSH/Remote Control to devbox | Devbox source-built managed App Server |
| Devbox terminal CLI | Same devbox source-built managed App Server |
| Windows terminal CLI | Source-built backend; native verification pending |
| Windows desktop, local project | Official app-owned backend; native verification pending |
| Personal Debian CLI and desktop | Source-built backend |

Keep one shared daemon on the devbox. A separate official remote desktop server
would add service, routing and update configuration without a current benefit.
Keep the same Codex home and history/authentication paths.

## macOS

Keep these desktop-only launchctl settings unset:

```sh
launchctl unsetenv CODEX_CLI_PATH
launchctl unsetenv CODEX_APP_SERVER_USE_LOCAL_DAEMON
```

Reopen ChatGPT when its tasks are idle. Without the executable override, this app
resolves its bundled `codex-cli/CodexCLI.app/Contents/MacOS/codex`, including matching
helper runtimes. Its local App Server uses private stdio pipes and remains separate
from the CLI daemon. Do not point it at `~/.local/bin/codex` or enable attachment to
the CLI's shared local daemon.

The terminal launcher and managed daemon both select the verified source package.
The daemon's upstream automatic updater stays disabled; nightlies own its updates.

## Devbox

Normal terminal clients, Desktop SSH and Remote Control use the source-built daemon.
Remove the devbox-only CODEX_INSTALL_DIR override previously added to `.zshenv`.
Desktop SSH should resolve `~/.local/bin/codex`, which selects the source package.
Use `codex app-server daemon version` and `/proc/<pid>/exe` to verify both selected
and running binaries. A client executable path alone does not establish its backend.

## Windows, when available

Use native PowerShell. Clear the native desktop executable override from both the
user environment and the current shell, then reopen ChatGPT when idle:

```powershell
[Environment]::SetEnvironmentVariable('CODEX_CLI_PATH', $null, 'User')
Remove-Item Env:CODEX_CLI_PATH -ErrorAction SilentlyContinue
[Environment]::SetEnvironmentVariable('CODEX_APP_SERVER_USE_LOCAL_DAEMON', $null, 'User')
Remove-Item Env:CODEX_APP_SERVER_USE_LOCAL_DAEMON -ErrorAction SilentlyContinue
[Environment]::GetEnvironmentVariable('CODEX_CLI_PATH', 'Machine')
```

If a machine-wide executable override is reported, remove that value from an
elevated PowerShell window. Preserve the source-built CLI daemon; do not run
`codex app-server daemon update`, which restores an official daemon. Native Windows
junction/config traversal and actual desktop routing still need verification.
Windows nightly builds remain build-only until activation is separately authorized.

## Personal Debian, when available

Keep its source-built CLI, daemon and desktop App Server. No desktop executable
reset is needed. If its application owns an unmanaged App Server, restart through
that owner when idle and verify the loaded executable.

## Startup and nightly ownership

Normal CLI startup reuses the selected managed package; it does not replace it
with whichever client launches first. Mac local desktop has a separate App Server.
The initial install on a host with no daemon selection can seed a package from
its initiating CLI; explicit package selection removes that ambiguity on later boots.

Unix nightlies activate the verified complete source package for both terminal CLI
and managed daemon, disable the daemon's upstream updater, and arrange an independent
idle restart after publication. They leave native desktop App Servers untouched.
