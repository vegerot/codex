"""Test nightly selection and idle restart without touching installed packages."""

import fcntl
import json
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.codex_package.activation import select_package, activate_verified
from scripts.macos import restart_if_idle as idle


class ActivationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.current = self.home / "packages/standalone/current"
        self.current.parent.mkdir(parents=True)
        self.current.symlink_to("old-package")
        self.package = self.home / "nightly"
        self.launchers = self.home / "bin"
        self.settings = self.home / "app-server-daemon/settings.json"

    def activate(self):
        return select_package(self.package, self.current, self.launchers, self.settings)

    def test_selection_disables_updater_with_initially_absent_settings(self):
        marker = self.current.parent / "auto-update-version"
        marker.write_text("stock")
        self.activate()
        self.assertFalse(marker.exists())
        self.assertEqual(self.current.resolve(), self.package)
        for name in ("codex", "codex-code-mode-host"):
            self.assertEqual(
                (self.launchers / name).resolve(), self.package / "bin" / name
            )
        self.assertEqual(
            json.loads(self.settings.read_text()),
            {"updater": {"autoUpdateEnabled": False}},
        )

    def test_every_unix_profile_selects_source_backend_as_well_as_cli(self):
        for profile in ("macos", "devbox", "debian"):
            with self.subTest(profile=profile):
                run = self.home / profile
                run.mkdir()
                (run / "run.json").write_text(
                    json.dumps(
                        {
                            "profile": profile,
                            "stages": {
                                "verify": {
                                    "status": "success",
                                    "package": str(self.package),
                                    "hashes": {"codex": "verified"},
                                }
                            },
                        }
                    )
                )
                with (
                    patch("pathlib.Path.home", return_value=self.home),
                    patch.dict("os.environ", {"CODEX_HOME": str(self.home)}),
                    patch(
                        "scripts.codex_package.verify_nightly.hashes",
                        return_value={"codex": "verified"},
                    ),
                    patch(
                        "scripts.codex_package.activation.subprocess.check_output",
                        return_value=json.dumps(
                            {"managedCodexPath": str(self.current / "bin/codex")}
                        ),
                    ),
                ):
                    result = activate_verified(run)
                self.assertEqual(self.current.resolve(), self.package)
                self.assertEqual(
                    (self.home / ".local/bin/codex").resolve(),
                    self.current.resolve() / "bin/codex",
                )
                self.assertEqual(result["restart"], "pending")
                self.assertFalse(
                    json.loads(self.settings.read_text())["updater"][
                        "autoUpdateEnabled"
                    ]
                )

    def test_preserves_other_settings(self):
        self.settings.parent.mkdir()
        original = {
            "remoteControlEnabled": True,
            "featureOverrides": {"example": True},
            "updater": {"updateIntervalMinutes": 120},
        }
        self.settings.write_text(json.dumps(original))
        self.activate()
        original["updater"]["autoUpdateEnabled"] = False
        self.assertEqual(json.loads(self.settings.read_text()), original)

    def test_inflight_installer_blocks_selection(self):
        with (self.current.parent / "install.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.activate()
        self.assertEqual(self.current.readlink(), Path("old-package"))
        self.assertFalse(self.settings.exists())

    def test_busy_tasks_never_receive_signal(self):
        self.activate()
        self.package.mkdir()
        (self.package / "codex-package.json").write_text('{"version":"nightly"}')
        (self.settings.parent / "app-server.pid").write_text(
            json.dumps({"pid": 123, "processStartTime": "start"})
        )
        info = {
            "managedCodexPath": str(self.current / "bin/codex"),
            "status": "running",
            "backend": "pid",
            "appServerVersion": "stock",
        }
        with (
            patch.dict("os.environ", {"CODEX_HOME": str(self.home)}),
            patch.object(idle, "version", return_value=info),
            patch.object(idle, "process_start", return_value="start"),
            patch(
                "scripts.codex_package.idle_tasks.inspect_tasks",
                new=AsyncMock(return_value=[{"status": "active"}]),
            ),
            patch.object(idle.os, "kill") as kill,
        ):
            self.assertEqual(idle.restart(self.package)["reason"], "Tasks are busy")
            kill.assert_not_called()

    def test_idle_restart_drains_then_starts_and_verifies_nightly(self):
        self.activate()
        self.package.mkdir()
        (self.package / "codex-package.json").write_text('{"version":"nightly"}')
        (self.settings.parent / "app-server.pid").write_text(
            json.dumps({"pid": 123, "processStartTime": "start"})
        )
        info = {
            "managedCodexPath": str(self.current / "bin/codex"),
            "status": "running",
            "backend": "pid",
            "appServerVersion": "stock",
        }
        with (
            patch.dict("os.environ", {"CODEX_HOME": str(self.home)}),
            patch.object(
                idle,
                "version",
                side_effect=[info, info | {"appServerVersion": "nightly"}],
            ),
            patch.object(idle, "process_start", side_effect=["start", "start", "gone"]),
            patch.object(
                idle, "running_executable", return_value=self.package / "bin/codex"
            ),
            patch(
                "scripts.codex_package.idle_tasks.inspect_tasks",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(idle.os, "kill") as kill,
            patch.object(idle.subprocess, "run") as run,
        ):
            self.assertEqual(
                idle.restart(self.package),
                {"status": "restarted", "version": "nightly"},
            )
            kill.assert_called_once_with(123, signal.SIGHUP)
            run.assert_called_once_with(
                [str(self.package / "bin/codex"), "app-server", "daemon", "start"],
                check=True,
            )

    def test_unmanaged_server_is_not_signaled_or_treated_as_missing_pid(self):
        self.activate()
        info = {
            "status": "running",
            "managedCodexPath": str(self.current / "bin/codex"),
        }
        with (
            patch.object(idle, "version", return_value=info),
            patch.object(idle.os, "kill") as kill,
        ):
            self.assertEqual(
                idle.restart(self.package),
                {
                    "status": "deferred",
                    "reason": "Running App Server is not managed by codex app-server daemon",
                },
            )
            kill.assert_not_called()
