# Native Windows builds

From an ordinary PowerShell at the repository root:

```powershell
python build.py
python build.py --jobs 24
```

Windows x64 selects this backend automatically. Install Python 3.12+, PowerShell
7, Git, Rustup, and Visual Studio's C++ x64 tools and Windows SDK first. The Rust
toolchain comes from the source's `codex-rs/rust-toolchain.toml`. `--scm` retains
the existing Linux worker workflow.

The build archives **committed HEAD**, excluding working-copy edits, and stamps
an upstream-derived version in a disposable snapshot. Commit source changes
before building them. The reusable snapshot and Cargo/V8 caches live under
`~/.cache/codex-windows-build/`; unchanged snapshot files keep their timestamps.

The default is 24 Cargo jobs, 16 codegen units, no LTO, no debug information, and
no incremental compilation. A first 12-job build on the personal Windows desktop
averaged 49% total CPU during sampling and retained at least 13.3 GiB available
RAM, motivating the 24-job trial. This is not a measured speedup; use `--jobs`
to tune another machine.

Each run saves `build.log`, `build-info.json`, and CPU/memory samples under
`~/.local/state/codex-windows-build/runs/`. Total CPU includes other applications;
the build CPU counter is a lower bound because short-lived compiler processes
can exit between samples. Run one build at a time against these shared caches.

Successful builds package the CLI, matching Code Mode host, ripgrep, and Windows
command-runner/sandbox helpers. Verification checks their hashes, CLI version,
real V8 execution, App Server initialization, and doctor diagnostics. Diagnostic
warnings are retained; failures prevent publishing a verified receipt. Including
Windows helpers does not enable sandboxing.

Verified packages are saved separately under
`~/.local/share/codex-windows-build/packages/`, with the latest receipt at
`~/.local/state/codex-windows-build/verified.json`. Existing packages and running
applications are preserved. This command does not change PATH, select a daemon
package, fetch/rebase/push source, or schedule builds.
