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
