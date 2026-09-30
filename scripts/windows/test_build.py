import importlib.util
import json
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
    def test_prune_keeps_latest_and_running_packages(self):
        with tempfile.TemporaryDirectory() as temporary:
            packages = Path(temporary)
            latest, running, old = [
                packages / name for name in ("latest", "running", "old")
            ]
            for package in (latest, running, old):
                (package / "bin").mkdir(parents=True)
                (package / "bin/codex.exe").write_text("binary")
            with patch.object(
                build.subprocess,
                "check_output",
                return_value=json.dumps([str(running / "bin/codex.exe")]),
            ):
                build.prune_packages(packages, latest)
            self.assertEqual(
                sorted(p.name for p in packages.iterdir()), ["latest", "running"]
            )

    def test_windows_migration_checksums_match_crlf_database(self):
        import hashlib
        import sqlite3

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            migration = source / "codex-rs/state/migrations/0001_threads.sql"
            migration.parent.mkdir(parents=True)
            migration.write_bytes(b"CREATE TABLE threads (id TEXT);\n")
            database = sqlite3.connect(":memory:")
            database.execute("CREATE TABLE _sqlx_migrations(checksum BLOB)")
            expected = hashlib.sha384(b"CREATE TABLE threads (id TEXT);\r\n").digest()
            database.execute("INSERT INTO _sqlx_migrations VALUES (?)", (expected,))
            self.assertNotEqual(
                hashlib.sha384(migration.read_bytes()).digest(), expected
            )
            build.prepare_migrations(source)
            self.assertEqual(
                hashlib.sha384(migration.read_bytes()).digest(),
                database.execute("SELECT checksum FROM _sqlx_migrations").fetchone()[0],
            )
            previous_mtime = migration.stat().st_mtime_ns
            build.prepare_migrations(source)
            self.assertEqual(migration.stat().st_mtime_ns, previous_mtime)
            database.close()

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


if __name__ == "__main__":
    unittest.main()
