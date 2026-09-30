# Windows source builds

Read the [shared guide](../nightly/README.md), [workflow](../nightly/workflow.md)
and [Windows profile](../nightly/profiles/windows.md).

The native builder compiles committed source locally with 24 jobs. It restores
CRLF in SQL migration files before compilation because SQLx hashes exact text;
official Windows packages embed CRLF checksums. A source archive supplies LF,
which otherwise produces a package that initializes fresh databases but rejects
existing official Windows databases. Verification checks the historical checksum.

After verification, activation selects the full package for ~/.local/bin/codex.cmd
and the separate CLI daemon. User PATH puts that launcher ahead of the official
standalone CLI; installed official binaries remain available at their full paths.
A hidden worker cuts over the CLI daemon after source publication and idle checks.
It never changes native desktop settings, overrides, installed runtime files or
app-owned processes. Native desktop uses its own official bundled backend.

Old package cleanup retains the selected CLI package and any running packages.
Locked packages are retried after the next verified build. Logs and compilation
caches remain available. Automations keep their existing schedule and identity.
