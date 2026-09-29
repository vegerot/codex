#!/usr/bin/env python3
"""Verify an exact-commit SCM package and optionally activate it on the devbox."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

SCM_REPO = "max/coplan/codex"
TARGET = "x86_64-unknown-linux-gnu"
STATE = Path.home() / ".local/state/codex-rebuild"
PACKAGES = Path.home() / ".local/share/codex-rebuild-packages"


def cli_json(*args):
    result = subprocess.run(
        ["bytedcli", "--json", *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    value = json.loads(result.stdout)
    if value["status"] != "success":
        raise RuntimeError(value.get("error"))
    return value["data"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version-id", required=True, type=int)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    if len(args.commit) != 40 or any(c not in "0123456789abcdef" for c in args.commit):
        parser.error("--commit must be the complete lowercase 40-character Git SHA")
    metadata = cli_json(
        "scm", "repo", "artifact", "get", "--version-id", str(args.version_id)
    )
    if metadata["name"] != SCM_REPO:
        raise RuntimeError("Version belongs to a different SCM repository")
    matches = [item for item in metadata["x86_64"] if item["asset_kind"] == "package"]
    if len(matches) != 1:
        raise RuntimeError("Expected exactly one Linux x86_64 SCM package")
    artifact = matches[0]
    PACKAGES.mkdir(parents=True, exist_ok=True)
    destination = PACKAGES / f"{args.version_id}-{args.commit}"
    downloaded_seconds = None
    if not destination.exists():
        if shutil.disk_usage(PACKAGES).free < 8 * 1024**3:
            raise RuntimeError(
                "Need at least 8 GiB free to stage and verify the package"
            )
        # Obtain auth via bytedcli, retaining the JWT only in memory.
        token = cli_json("--nomask", "auth", "get-bytecloud-jwt-token")["jwt"]
        with tempfile.TemporaryDirectory(prefix=".stage-", dir=PACKAGES) as temporary:
            stage = Path(temporary)
            archive = stage / "package.tar.gz"
            digest = hashlib.sha256()
            started = time.monotonic()
            request = Request(artifact["download_url"], headers={"x-jwt-token": token})
            with (
                urlopen(request, timeout=120) as response,
                archive.open("wb") as output,
            ):
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
            downloaded_seconds = round(time.monotonic() - started, 2)
            if digest.hexdigest() != artifact["sha256"]:
                raise RuntimeError("SCM archive checksum mismatch; not extracting")
            package = stage / "package"
            package.mkdir()
            with tarfile.open(archive) as bundle:
                bundle.extractall(package, filter="data")
            package.rename(destination)
    info = json.loads((destination / "build-info.json").read_text())
    receipt = {
        "versionId": args.version_id,
        "scmVersion": metadata["version"],
        "commit": args.commit,
        "package": str(destination),
        "archiveSha256": artifact["sha256"],
        "downloadSeconds": downloaded_seconds,
        "build": info,
        "installed": False,
    }
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.codex_package.verify_nightly import verify_run
    from scripts.codex_package.nightly import atomic_json

    verify_run(args.run_dir, destination)
    atomic_json(args.run_dir / "artifact.json", receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
