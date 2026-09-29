"""No real queues, builds, or restarts; verify orchestration boundaries."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load("run")


class DispatchTests(unittest.TestCase):
    def test_trigger_queues_snapshot_without_exec(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(runner.Path, "home", return_value=Path(temp)),
            patch("sys.argv", ["run.py"]),
            patch.object(runner.subprocess, "run") as call,
            patch.object(runner.subprocess, "check_output", return_value="a" * 40),
        ):
            runner.main()
            directory = (Path(temp) / ".local/state/codex-rebuild/latest").resolve()
            self.assertTrue((directory / "prompt.md").is_file())
            self.assertIn('fork_turns="none"', (directory / "request.md").read_text())
            self.assertIn("notify.py", call.call_args.args[0][3])
            self.assertNotIn("exec", call.call_args.args[0])
            self.assertEqual(call.call_count, 1)
