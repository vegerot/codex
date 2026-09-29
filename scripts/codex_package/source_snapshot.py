"""Run build helpers from the same committed snapshot they compile."""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def dispatch(repo, commit, run_dir, entrypoint, arguments):
    commit = subprocess.check_output(
        ["sl", "log", "--rev", commit, "--template", "{node}"], cwd=repo, text=True
    ).strip()
    cache = Path.home() / ".cache/codex-nightly-source"
    cache.mkdir(parents=True, exist_ok=True)
    source = cache / "source"
    # The caller's build lock serializes this stable cache. Byte comparison retains
    # unchanged mtimes, so a new snapshot does not invalidate every Cargo input.
    with tempfile.TemporaryDirectory(dir=cache) as temporary:
        staged = Path(temporary) / "source"
        subprocess.run(
            [
                "sl",
                "--config",
                "ui.archivemeta=false",
                "archive",
                "--type",
                "files",
                "--include",
                "glob:**",
                "--rev",
                commit,
                str(staged),
            ],
            cwd=repo,
            check=True,
        )
        for path in staged.rglob("*"):
            relative = path.relative_to(staged)
            dest = source / relative
            if path.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            elif path.is_symlink():
                dest.unlink(missing_ok=True)
                dest.symlink_to(path.readlink())
            elif not dest.exists() or dest.read_bytes() != path.read_bytes():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)
        for path in sorted(source.rglob("*"), reverse=True):
            if not (staged / path.relative_to(source)).exists():
                if path.is_dir() and not path.is_symlink():
                    path.rmdir()
                else:
                    path.unlink()
    run_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, str(source / entrypoint), *arguments],
        cwd=source,
        env={
            **os.environ,
            "CODEX_FROZEN_SOURCE": commit,
            "CODEX_NIGHTLY_RUN_DIR": str(run_dir.resolve()),
            "CODEX_REPO_ROOT": str(source),
        },
        check=True,
    )
