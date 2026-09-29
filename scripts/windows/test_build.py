import importlib.util
import sys
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


if __name__ == "__main__":
    unittest.main()
