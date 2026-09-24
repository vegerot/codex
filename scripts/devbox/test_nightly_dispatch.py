"""No real queues, builds, or restarts; verify orchestration boundaries."""

import importlib.util
import json
import subprocess
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
finisher = load("finish")


class DispatchTests(unittest.TestCase):
    def test_trigger_queues_snapshot_without_exec(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(runner.Path, "home", return_value=Path(temp)),
            patch("sys.argv", ["run.py"]),
            patch.object(runner.subprocess, "run") as call,
        ):
            runner.main()
            directory = (Path(temp) / ".local/state/codex-rebuild/latest").resolve()
            self.assertTrue((directory / "prompt.md").is_file())
            self.assertIn('fork_turns="none"', (directory / "request.md").read_text())
            self.assertIn("notify.py", call.call_args.args[0][3])
            self.assertNotIn("exec", call.call_args.args[0])
            self.assertEqual(call.call_count, 1)

    def test_finisher_waits_then_notifies_once(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "report.md").write_text("Build succeeded")
            responses = [
                subprocess.CompletedProcess([], 0, json.dumps(value), "")
                for value in [
                    {"status": "deferred", "reason": "Tasks are busy"},
                    {"status": "already-current"},
                    {},
                ]
            ]
            with (
                patch.object(finisher.subprocess, "run", side_effect=responses) as call,
                patch.object(finisher.time, "sleep") as sleep,
            ):
                finisher.finish(directory)
                sleep.assert_called_once_with(15)
                self.assertEqual(call.call_count, 3)
                self.assertIn("notify.py", call.call_args.args[0][3])
                finisher.finish(directory)
                self.assertEqual(call.call_count, 3)
            self.assertEqual(
                json.loads((directory / "restart.json").read_text())["status"],
                "already-current",
            )

    def test_no_finisher_before_report(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(finisher.subprocess, "run") as call,
        ):
            with self.assertRaises(RuntimeError):
                finisher.finish(Path(temp))
            call.assert_not_called()
