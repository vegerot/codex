"""Run-state failures must never authorize activation or restart."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.codex_package.nightly import initialize, record_stage, status
from scripts.codex_package.restart_nightly import require_published


class RunTests(unittest.TestCase):
    def test_failed_attempt_keeps_verified_run_and_snapshots_instructions(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "scripts.codex_package.nightly.subprocess.check_output",
                return_value="a" * 40,
            ),
        ):
            state = Path(temporary)
            first = initialize("devbox", state=state)
            record_stage(first, "verify", "success", package="/verified")
            second = initialize("devbox", state=state)
            record_stage(second, "verify", "failed", error="bad package")
            result = status("devbox", state)
            self.assertEqual(result["latest-verified"]["run_id"], first.name)
            self.assertEqual(result["latest-attempt"]["run_id"], second.name)
            self.assertIn("--verbatim", (first / "workflow.md").read_text())
            self.assertIn("SCM only", (first / "profile.md").read_text())

    def test_restart_requires_each_successful_stage(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "scripts.codex_package.nightly.subprocess.check_output",
                return_value="a" * 40,
            ),
        ):
            run = initialize("devbox", state=Path(temporary))
            for stage in ("build", "verify", "activate", "publish"):
                with self.assertRaisesRegex(RuntimeError, stage):
                    require_published(run)
                record_stage(run, stage, "success")
            self.assertEqual(require_published(run)["profile"], "devbox")

    def test_windows_does_not_request_activation_or_restart(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "scripts.codex_package.nightly.subprocess.check_output",
                return_value="a" * 40,
            ),
        ):
            run = initialize("windows", state=Path(temporary))
            record = json.loads((run / "run.json").read_text())
            self.assertEqual(record["stages"]["activate"], {"status": "not_requested"})
            with self.assertRaisesRegex(RuntimeError, "Windows"):
                require_published(run)


class BuildFailureTests(unittest.TestCase):
    def test_startup_failure_is_recorded_and_releases_cache_lock(self):
        from scripts.codex_package import source_snapshot

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "scripts.codex_package.nightly.subprocess.check_output",
                return_value="a" * 40,
            ),
        ):
            root = Path(temporary)
            run = initialize("windows", state=root / "state")
            with (
                patch.object(
                    source_snapshot, "snapshot_cache", return_value=root / "cache"
                ),
                patch.object(
                    source_snapshot,
                    "_dispatch",
                    side_effect=OSError("compiler launcher failed"),
                ),
            ):
                with self.assertRaisesRegex(OSError, "launcher failed"):
                    source_snapshot.dispatch(root, "a" * 40, run, "build.py", [])
            record = json.loads((run / "run.json").read_text())
            self.assertEqual(
                record["stages"]["build"],
                {"status": "failed", "error": "compiler launcher failed"},
            )
            self.assertFalse((root / "cache/build.lock").exists())
