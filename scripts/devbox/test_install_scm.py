"""Local tests: no network, real daemon, or installed launcher changes."""

import fcntl
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "install_scm", Path(__file__).with_name("install-scm.py")
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "nightly"
        (self.package / "bin").mkdir(parents=True)
        (self.package / "bin/codex").touch()
        self.cli = self.root / "codex"
        self.current = self.root / "current"
        self.cli.symlink_to("old-cli")
        self.current.symlink_to("old-package")
        self.settings = self.root / "settings.json"
        self.original = {
            "remoteControlEnabled": True,
            "featureOverrides": {"code_mode_host": True},
            "updater": {"updateIntervalMinutes": 120},
        }
        self.settings.write_text(json.dumps(self.original))

    def activate(self):
        return installer.activate(self.package, self.cli, self.current, self.settings)

    def test_both_launchers_select_same_package_and_preserve_settings(self):
        receipt = self.activate()
        self.assertEqual(self.cli.resolve(), (self.current / "bin/codex").resolve())
        self.assertEqual(self.cli.resolve(), self.package / "bin/codex")
        expected = self.original | {
            "updater": {"updateIntervalMinutes": 120, "autoUpdateEnabled": False}
        }
        self.assertEqual(json.loads(self.settings.read_text()), expected)
        self.assertEqual(receipt["previousCodexTarget"], "old-cli")
        self.assertEqual(receipt["previousDaemonTarget"], "old-package")
        self.assertTrue(receipt["daemonRestartRequired"])
        self.activate()  # Repeated installs are harmless.

    def test_non_symlink_is_not_overwritten(self):
        self.cli.unlink()
        self.cli.write_text("user-owned launcher")
        with self.assertRaisesRegex(RuntimeError, "non-symlink"):
            self.activate()
        self.assertEqual(self.cli.read_text(), "user-owned launcher")
        self.assertEqual(json.loads(self.settings.read_text()), self.original)
        self.assertEqual(self.current.readlink(), Path("old-package"))

    def test_busy_official_installer_prevents_changes(self):
        with (self.root / "install.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.activate()
        self.assertEqual(json.loads(self.settings.read_text()), self.original)
        self.assertEqual(self.current.readlink(), Path("old-package"))

    def test_wrong_commit_rejected_before_execution(self):
        (self.package / "build-info.json").write_text(
            json.dumps(
                {
                    "commit": "a" * 40,
                    "target": installer.TARGET,
                }
            )
        )
        (self.package / "codex-package.json").write_text(
            json.dumps(
                {
                    "target": installer.TARGET,
                }
            )
        )
        with self.assertRaisesRegex(RuntimeError, "requested source commit"):
            installer.verify_package(self.package, "b" * 40)

    def test_unstamped_or_mismatched_version_rejected_before_execution(self):
        for compiled_version, manifest_version in (
            ("0.0.0", "0.0.0"),
            ("0.156.1+dev.aaaaaaaaaaaa", "0.0.0"),
        ):
            with self.subTest(compiled_version=compiled_version):
                (self.package / "build-info.json").write_text(
                    json.dumps(
                        {
                            "commit": "a" * 40,
                            "target": installer.TARGET,
                            "version": compiled_version,
                        }
                    )
                )
                (self.package / "codex-package.json").write_text(
                    json.dumps(
                        {
                            "target": installer.TARGET,
                            "version": manifest_version,
                        }
                    )
                )
                with self.assertRaisesRegex(RuntimeError, "unstamped or inconsistent"):
                    installer.verify_package(self.package, "a" * 40)


if __name__ == "__main__":
    unittest.main()
