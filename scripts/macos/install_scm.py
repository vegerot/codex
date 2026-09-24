#!/usr/bin/env python3
"""Verify an exact-source macOS SCM package, then update the existing Mac package."""

import argparse
import hashlib
import json
import platform
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import build  # noqa: E402


def cli_json(*args):
    result = subprocess.run(
        ["bytedcli", "--json", *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    result = json.loads(result.stdout)
    if result["status"] != "success":
        raise RuntimeError(result.get("error"))
    return result["data"]


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def verify(package, commit):
    info = json.loads((package / "build-info.json").read_text())
    manifest = json.loads((package / "codex-package.json").read_text())
    if info["commit"] != commit or info["target"] != "aarch64-apple-darwin":
        raise RuntimeError("Wrong SCM source commit or target")
    if manifest["target"] != info["target"] or manifest["version"] != info["version"]:
        raise RuntimeError("Inconsistent SCM package metadata")
    checksums = dict(
        (name, digest)
        for digest, name in (
            line.split(maxsplit=1)
            for line in (package / "SHA256SUMS").read_text().splitlines()
        )
    )
    for name in ("bin/codex", "bin/codex-code-mode-host", "codex-path/rg"):
        if name not in checksums:
            raise RuntimeError(f"Missing required checksum: {name}")
    for name, digest in checksums.items():
        if sha256(package / name) != digest:
            raise RuntimeError(f"SCM checksum mismatch: {name}")
    build.validate_package_dir(
        package,
        build.PACKAGE_VARIANTS["codex"],
        build.TARGET_SPECS[info["target"]],
        include_zsh=True,
    )
    actual = subprocess.check_output(
        [str(package / "bin/codex"), "--version"], text=True
    )
    if actual.strip() != f"codex-cli {info['version']}":
        raise RuntimeError("SCM CLI version differs from build metadata")
    for name in ("codex", "codex-code-mode-host"):
        subprocess.run(
            ["codesign", "--verify", "--strict", str(package / "bin" / name)],
            check=True,
        )
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/devbox/test-host.py"),
            str(package / "bin/codex-code-mode-host"),
        ],
        check=True,
        timeout=60,
    )
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/codex_package/check_runtime_version.py"),
            str(package / "bin/codex"),
        ],
        check=True,
        timeout=60,
    )
    return info


def install(package, info):
    build.validate_existing_package(build.TARGET_SPECS["aarch64-apple-darwin"])
    for name in ("codex", "codex-code-mode-host"):
        build.atomic_copy(package / "bin" / name, build.PACKAGE_DIR / "bin" / name)
        if sha256(package / "bin" / name) != sha256(build.PACKAGE_DIR / "bin" / name):
            raise RuntimeError(f"Installed hash mismatch: {name}")
    build.update_package_version(info["version"])
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/codex_package/check_runtime_version.py"),
            str(build.PACKAGE_DIR / "bin/codex"),
        ],
        check=True,
        timeout=60,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("This installer is for Apple Silicon macOS")
    metadata = cli_json(
        "scm", "repo", "artifact", "get", "--version-id", args.version_id
    )
    if metadata["name"] != "max/coplan/codex":
        raise RuntimeError("SCM version belongs to another repository")
    # SCM labels artifacts by worker architecture; the package must identify macOS.
    artifacts = [item for item in metadata["x86_64"] if item["asset_kind"] == "package"]
    if len(artifacts) != 1:
        raise RuntimeError("Expected one SCM package")
    artifact = artifacts[0]
    token = cli_json("--nomask", "auth", "get-bytecloud-jwt-token")["jwt"]
    with tempfile.TemporaryDirectory(prefix="codex-macos-scm-") as directory:
        stage = Path(directory)
        archive = stage / "package.tar.gz"
        request = Request(artifact["download_url"], headers={"x-jwt-token": token})
        with urlopen(request, timeout=120) as response, archive.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if sha256(archive) != artifact["sha256"]:
            raise RuntimeError("SCM archive checksum mismatch")
        package = stage / "package"
        package.mkdir()
        with tarfile.open(archive) as bundle:
            bundle.extractall(package, filter="data")
        info = verify(package, args.commit)
        hashes = {
            name: sha256(package / "bin" / name)
            for name in ("codex", "codex-code-mode-host")
        }
        if args.install:
            install(package, info)
        receipt = {
            "backend": "scm",
            "version_id": args.version_id,
            "scm_version": metadata["version"],
            "build": info,
            "binary_hashes": hashes,
            "package": str(build.PACKAGE_DIR),
            "installed": args.install,
        }
        state = Path.home() / ".local/state/codex-macos-build"
        state.mkdir(parents=True, exist_ok=True)
        (state / f"scm-{args.version_id}.json").write_text(
            json.dumps(receipt, indent=2) + "\n"
        )
        print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
