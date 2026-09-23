"""Stamp a disposable SCM checkout with an upstream-based development version."""

import re
import subprocess

import tomllib

UPSTREAM = "https://github.com/openai/codex.git"


def latest_stable_version(refs):
    versions = []
    for line in refs.splitlines():
        match = re.fullmatch(r"[0-9a-f]+\s+refs/tags/rust-v(\d+)\.(\d+)\.(\d+)", line)
        if match:
            versions.append(tuple(map(int, match.groups())))
    if not versions:
        raise RuntimeError("No stable upstream Codex release tags found")
    return ".".join(map(str, max(versions)))


def stamp_workspace(rust_root, base_version, commit):
    manifest_path = rust_root / "Cargo.toml"
    lock_path = rust_root / "Cargo.lock"
    manifest_text = manifest_path.read_text()
    lock_text = lock_path.read_text()
    manifest = tomllib.loads(manifest_text)
    old = manifest["workspace"]["package"]["version"]
    version = f"{base_version}+dev.{commit[:12]}"
    # All current workspace crates inherit this version. Do not silently stamp
    # an external dependency if upstream ever adds one with the same version.
    packages = tomllib.loads(lock_text)["package"]
    assert not any(p["version"] == old and "source" in p for p in packages)
    section, count = re.subn(
        r'(?m)^(\[workspace\.package\]\s*\n)version = "[^"]+"',
        lambda match: f'{match[1]}version = "{version}"',
        manifest_text,
    )
    assert count == 1, "Expected one workspace package version"
    locked = re.sub(
        rf'(?m)^version = "{re.escape(old)}"$', f'version = "{version}"', lock_text
    )
    # Cargo can qualify dependency references with a version when names collide.
    for package in packages:
        if package["version"] == old:
            locked = locked.replace(
                f'"{package["name"]} {old}"', f'"{package["name"]} {version}"'
            )
    manifest_path.write_text(section)
    lock_path.write_text(locked)
    return version


def stamp_nightly_version(root, commit):
    refs = subprocess.check_output(
        ["git", "ls-remote", "--tags", "--refs", UPSTREAM, "rust-v*"],
        text=True,
        timeout=120,
    )
    base = latest_stable_version(refs)
    version = stamp_workspace(root / "codex-rs", base, commit)
    return {"version": version, "upstream_release_tag": f"rust-v{base}"}
