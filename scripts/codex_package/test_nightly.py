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


class RestartFailureTests(unittest.TestCase):
    @unittest.skipIf(__import__("sys").platform == "win32", "Unix restart adapter")
    def test_probe_error_is_saved_without_claiming_restart(self):
        from scripts.codex_package.restart_nightly import finish

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "scripts.codex_package.nightly.subprocess.check_output",
                return_value="a" * 40,
            ),
        ):
            run = initialize("macos", state=Path(temporary))
            for stage in ("build", "verify", "activate", "publish"):
                record_stage(run, stage, "success", package=temporary)
            with patch(
                "scripts.macos.restart_if_idle.restart",
                side_effect=OSError("control socket unavailable"),
            ):
                result = finish(run)
            self.assertEqual(
                result, {"status": "error", "reason": "control socket unavailable"}
            )
            self.assertEqual(json.loads((run / "restart.json").read_text()), result)
            self.assertEqual(
                json.loads((run / "run.json").read_text())["stages"]["restart"][
                    "status"
                ],
                "error",
            )

    @unittest.skipIf(__import__("sys").platform == "win32", "Unix restart adapter")
    def test_notification_retry_never_restarts_completed_run(self):
        from unittest.mock import AsyncMock
        from scripts.codex_package import rpc
        from scripts.codex_package.restart_nightly import finish

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "scripts.codex_package.nightly.subprocess.check_output",
                return_value="a" * 40,
            ),
        ):
            run = initialize("macos", state=Path(temporary))
            for stage in ("build", "verify", "activate", "publish"):
                record_stage(run, stage, "success", package=temporary)
            record = json.loads((run / "run.json").read_text())
            record["coordinator_thread"] = "test-task"
            (run / "run.json").write_text(json.dumps(record))
            result = {"status": "restarted", "version": "tested"}
            (run / "restart.json").write_text(json.dumps(result))
            with (
                patch.object(
                    rpc,
                    "notify",
                    new=AsyncMock(side_effect=[OSError("offline"), None, None]),
                ) as notify,
                patch("scripts.macos.restart_if_idle.restart") as restart,
            ):
                with self.assertRaisesRegex(OSError, "offline"):
                    finish(run)
                self.assertEqual(finish(run), result)
                self.assertEqual(finish(run), result)
                self.assertEqual(notify.await_count, 2)
                updated = {"status": "already-current", "version": "new-attempt"}
                (run / "restart.json").write_text(json.dumps(updated))
                self.assertEqual(finish(run), updated)
                self.assertEqual(notify.await_count, 3)
                restart.assert_not_called()


class OwnershipAndLaunchTests(unittest.TestCase):
    def test_status_preserves_unmanaged_server_versions_without_pid_file(self):
        info = {
            "status": "running",
            "managedCodexPath": "/selected/bin/codex",
            "managedCodexVersion": "new",
            "appServerVersion": "old",
        }
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "scripts.codex_package.nightly.subprocess.check_output",
                return_value=json.dumps(info),
            ),
        ):
            live = status("debian", Path(temporary))["live"]
        self.assertEqual(live["ownership"], "unmanaged")
        self.assertEqual(live["appServerVersion"], "old")
        self.assertTrue(live["restart_pending"])
        self.assertNotIn("error", live)

    def test_failed_worker_launch_is_recorded(self):
        import subprocess
        from scripts.codex_package import restart_nightly

        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "scripts.codex_package.nightly.subprocess.check_output",
                return_value="a" * 40,
            ),
        ):
            run = initialize("debian", state=Path(temporary))
            for stage in ("build", "verify", "activate", "publish"):
                record_stage(run, stage, "success")
            (run / "helpers").mkdir()
            with (
                patch.object(restart_nightly.sys, "platform", "linux"),
                patch.object(
                    restart_nightly.subprocess,
                    "run",
                    side_effect=subprocess.CalledProcessError(1, ["systemd-run"]),
                ),
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    restart_nightly.schedule(run)
            self.assertEqual(
                json.loads((run / "restart.json").read_text())["status"], "error"
            )
            self.assertEqual(
                json.loads((run / "run.json").read_text())["stages"]["restart"][
                    "status"
                ],
                "error",
            )
