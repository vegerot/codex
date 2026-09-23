#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 --version
CODEX_TOOLCHAIN="$(python3 -c 'import tomllib; print(tomllib.load(open("codex-rs/rust-toolchain.toml", "rb"))["toolchain"]["channel"])')"
export CODEX_TOOLCHAIN
rustup toolchain install "$CODEX_TOOLCHAIN" --profile minimal --no-self-update
exec python3 build-scm.py
