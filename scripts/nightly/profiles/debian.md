# Debian desktop

Native Debian, existing 04:00 America/Los_Angeles heartbeat. Build locally from a
committed snapshot, preserving stable Cargo cache/source paths. Keep the 15 GiB
free-space requirement, memory-derived jobs capped at 16, clang/lld-19, 16 codegen
units, no LTO/debug/incremental. Package CLI, Code Mode, ripgrep and source-built
bwrap. Activate the verified full package and arrange an independent idle restart
after successful publication. Do not substitute WSL for native Debian validation
or mount disks/start stopped distributions as part of deployment.

Build command: `python3 scripts/debian/build.py --commit <SHA> --run-dir <run>`.
