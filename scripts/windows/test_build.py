import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo))
spec = importlib.util.spec_from_file_location("windows_build_entry", repo / "build.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)

from scripts.windows import build  # noqa: E402


class WindowsBuildTests(unittest.TestCase):
    def test_windows_entry_selects_backend_and_jobs(self):
        with (
            patch.object(entry.platform, "system", return_value="Windows"),
            patch.object(entry.platform, "machine", return_value="AMD64"),
            patch.object(build, "build_windows") as backend,
        ):
            entry.main()
            self.assertEqual(backend.call_args.kwargs, {"jobs": 24})
            command = backend.call_args.args[1]
            binaries = [
                command[i + 1] for i, arg in enumerate(command) if arg == "--bin"
            ]
            self.assertEqual(
                binaries,
                [
                    "codex",
                    "codex-code-mode-host",
                    "codex-command-runner",
                    "codex-windows-sandbox-setup",
                    "codex-windows-sandbox-service",
                ],
            )
            entry.main(jobs=7)
            self.assertEqual(backend.call_args.kwargs, {"jobs": 7})
            with self.assertRaisesRegex(ValueError, "positive"):
                entry.main(jobs=0)

    def test_snapshot_excludes_edits_preserves_mtimes_and_removes_deleted_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository, cache = root / "repo", root / "cache"
            repository.mkdir()
            cache.mkdir()

            def git(*args):
                return subprocess.check_output(
                    ["git", *args], cwd=repository, text=True
                ).strip()

            git("init", "--quiet")
            git("config", "user.name", "Build Test")
            git("config", "user.email", "test@example.invalid")
            git("config", "commit.gpgsign", "false")
            git("config", "core.autocrlf", "false")
            (repository / "codex-rs").mkdir()
            (repository / "codex-rs/Cargo.toml").write_text("unstamped")
            (repository / "codex-rs/Cargo.lock").write_text("lock")
            (repository / "kept").write_text("committed")
            (repository / "removed").write_text("obsolete")
            git("add", ".")
            git("commit", "--quiet", "--message", "initial")
            commit = git("rev-parse", "HEAD")
            (repository / "kept").write_text("uncommitted")

            def stamp(path, revision):
                (path / "codex-rs/Cargo.toml").write_text("stamped")
                return {"version": "test"}

            with patch.object(build, "stamp_nightly_version", side_effect=stamp):
                source, version = build.snapshot(repository, cache, commit)
                self.assertEqual((source / "kept").read_text(), "committed")
                self.assertEqual(
                    (source / "codex-rs/Cargo.toml").read_text(), "stamped"
                )
                times = {
                    p.name: p.stat().st_mtime_ns
                    for p in source.rglob("*")
                    if p.is_file()
                }
                build.snapshot(repository, cache, commit)
                self.assertEqual(
                    times,
                    {
                        p.name: p.stat().st_mtime_ns
                        for p in source.rglob("*")
                        if p.is_file()
                    },
                )
                git("rm", "removed")
                git("commit", "--quiet", "--message", "remove obsolete")
                build.snapshot(repository, cache, git("rev-parse", "HEAD"))
                self.assertFalse((source / "removed").exists())
                self.assertEqual((repository / "kept").read_text(), "uncommitted")


if __name__ == "__main__":
    unittest.main()
