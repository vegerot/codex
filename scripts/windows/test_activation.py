import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.codex_package.activation import activate_verified
from scripts.codex_package.verify_nightly import hashes
from scripts.windows import activation


@unittest.skipUnless(sys.platform == "win32", "Native Windows selection")
class WindowsActivationTests(unittest.TestCase):
    def test_verified_selection_preserves_desktop_and_keeps_full_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "package"
            (package / "bin").mkdir(parents=True)
            (package / "bin/codex.exe").write_bytes(b"source-cli")
            (package / "bin/codex-code-mode-host.exe").write_bytes(b"source-host")
            desktop = root / "AppData/Local/OpenAI/Codex/bin/official/codex.exe"
            desktop.parent.mkdir(parents=True)
            desktop.write_bytes(b"desktop-official")
            home = root / ".codex"
            settings = home / "app-server-daemon/settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                '{"remoteControlEnabled":false,"updater":{"autoUpdateEnabled":false}}'
            )
            settings_before = settings.read_bytes()
            run = root / "runs/test"
            run.mkdir(parents=True)
            record = {
                "profile": "windows",
                "stages": {
                    "verify": {
                        "status": "success",
                        "package": str(package),
                        "hashes": hashes(package),
                    }
                },
            }
            (run / "run.json").write_text(json.dumps(record))
            with (
                patch.object(activation.Path, "home", return_value=root),
                patch.dict(os.environ, {"CODEX_HOME": str(home)}),
                patch.object(activation, "ensure_user_path"),
            ):
                result = activate_verified(run)
            self.assertEqual(
                (home / "packages/app-server-daemon/current").resolve(),
                package.resolve(),
            )
            self.assertEqual(
                (root / ".local/share/codex-windows-build/current").resolve(),
                package.resolve(),
            )
            self.assertIn("%*", (root / ".local/bin/codex.cmd").read_text())
            self.assertEqual(desktop.read_bytes(), b"desktop-official")
            self.assertEqual(settings.read_bytes(), settings_before)
            self.assertEqual(result["restart"], "pending")

    def test_changed_package_cannot_activate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "package"
            package.mkdir()
            (package / "binary").write_bytes(b"changed")
            (root / "run.json").write_text(
                json.dumps(
                    {
                        "profile": "windows",
                        "stages": {
                            "verify": {
                                "status": "success",
                                "package": str(package),
                                "hashes": {},
                            }
                        },
                    }
                )
            )
            with self.assertRaisesRegex(RuntimeError, "changed"):
                activate_verified(root)
            self.assertFalse((root / ".local").exists())

    def test_busy_daemon_is_not_signaled(self):
        package = Path("C:/verified")
        info = {
            "status": "running",
            "backend": "pid",
            "managedCodexPath": str(package / "bin/codex.exe"),
            "appServerVersion": "old",
        }
        identity = {"pid": 7, "processStartTime": "123"}

        def read(path):
            return json.dumps(
                {"version": "new"} if path.name == "codex-package.json" else identity
            )

        from unittest.mock import AsyncMock, MagicMock

        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.recv.return_value = '{"id":1,"result":{}}'
        with (
            patch.object(
                activation.subprocess, "check_output", return_value=json.dumps(info)
            ),
            patch.object(activation.Path, "read_text", read),
            patch.object(
                activation,
                "process_identity",
                return_value={"start": "123", "executable": "C:/old/bin/codex.exe"},
            ),
            patch.object(
                activation, "connect_socket", return_value=connection
            ) as connect,
            patch(
                "scripts.codex_package.idle_tasks.busy_threads",
                new=AsyncMock(return_value=[{"threadId": "busy", "status": "active"}]),
            ),
        ):
            result = activation.restart(package)
        self.assertEqual(result["reason"], "Tasks are busy")
        self.assertEqual(connect.call_count, 1)
        self.assertEqual(connect.call_args.args[1], "ws://localhost/rpc")


if __name__ == "__main__":
    unittest.main()
