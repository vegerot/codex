#!/usr/bin/env python3
"""Select a verified nightly for the CLI and daemon without interrupting work."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


from scripts.codex_package.activation import select_package


def verify_receipt(receipt):
    if not receipt["installed"]:
        raise RuntimeError("Receipt does not describe an installed package")
    package = Path(receipt["package"]).resolve()
    manifest = json.loads((package / "codex-package.json").read_text())
    if manifest["version"] != receipt["build"]["version"]:
        raise RuntimeError("Package version differs from receipt")
    for name, expected in receipt["binary_hashes"].items():
        with (package / "bin" / name).open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
        if actual != expected:
            raise RuntimeError(f"Installed checksum differs from receipt: {name}")
    return package


def activate(receipt_path):
    receipt = json.loads(receipt_path.read_text())
    package = verify_receipt(receipt)
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    info = json.loads(
        subprocess.check_output(
            [str(package / "bin/codex"), "app-server", "daemon", "version"], text=True
        )
    )
    # Ask Codex which package root it owns; preserve the existing PID namespace.
    current = Path(info["managedCodexPath"]).parent.parent
    if current.name != "current":
        raise RuntimeError(f"Unexpected managed package path: {current}")
    previous = select_package(
        package,
        current,
        Path.home() / ".local/bin",
        home / "app-server-daemon/settings.json",
    )
    state = receipt_path.parent
    result = {
        "package": str(package),
        "previousLinks": previous,
        "daemonRestartRequired": info["status"] == "running",
    }
    (state / "activation.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(activate(args.receipt), indent=2))
