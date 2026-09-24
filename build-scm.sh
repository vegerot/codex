#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 --version
CODEX_TOOLCHAIN="$(python3 -c 'import tomllib; print(tomllib.load(open("codex-rs/rust-toolchain.toml", "rb"))["toolchain"]["channel"])')"
export CODEX_TOOLCHAIN
rustup toolchain install "$CODEX_TOOLCHAIN" --profile minimal --no-self-update
case "${CUSTOM_CODEX_TARGET:-x86_64-unknown-linux-gnu}" in
  aarch64-apple-darwin)
    : "${CUSTOM_CODEX_BASE_VERSION:?Set the verified stable upstream version}"
    exec python3 build-scm-macos.py
    ;;
  x86_64-unknown-linux-gnu)
    exec python3 build.py --scm
    ;;
  *)
    echo "Unsupported SCM target: $CUSTOM_CODEX_TARGET" >&2
    exit 2
    ;;
esac
