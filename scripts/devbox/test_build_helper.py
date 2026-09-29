import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo))
spec = importlib.util.spec_from_file_location("personal_build", repo / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class BuildTests(unittest.TestCase):
    def test_scm_route_uses_worker_build(self):
        with (
            patch.object(build, "build_scm") as scm,
            patch.object(build, "build_local") as local,
        ):
            build.main(scm=True)
            scm.assert_called_once_with()
            local.assert_not_called()

    def test_local_build_stages_complete_package_before_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("LICENSE", "NOTICE"):
                (root / name).write_text(name)
            run_dir = root / "run"
            run_dir.mkdir()
            with (
                patch.dict(
                    os.environ,
                    {
                        "CODEX_FROZEN_SOURCE": "a" * 40,
                        "CODEX_NIGHTLY_RUN_DIR": str(run_dir),
                        "CARGO_TARGET_DIR": str(root / "existing-target"),
                    },
                ),
                patch.object(build, "REPO_ROOT", root),
                patch.object(build.Path, "home", return_value=root),
                patch.object(
                    build,
                    "host_spec",
                    return_value=build.TARGET_SPECS["x86_64-unknown-linux-gnu"],
                ),
                patch.object(build, "resolve_codex_v8_cargo_env", return_value={}),
                patch.object(build, "resolve_rg_bin", return_value=root / "rg"),
                patch.object(build, "build_linux") as compile,
                patch.object(build, "build_package_dir") as stage,
                patch(
                    "scripts.codex_package.nightly_version.stamp_nightly_version",
                    return_value={"version": "1.0.0+dev.aaaaaaaaaaaa"},
                ),
                patch("scripts.codex_package.nightly.record_stage"),
                patch(
                    "scripts.codex_package.verify_nightly.verify_run", return_value={}
                ) as verify,
            ):
                build.build_local()
                compile.assert_called_once()
                package = stage.call_args.args[0]
                self.assertEqual(stage.call_args.args[4].bwrap_bin.name, "bwrap")
                self.assertEqual(
                    json.loads((package / "build-info.json").read_text())["commit"],
                    "a" * 40,
                )
                verify.assert_called_once_with(run_dir, package)

    def test_cargo_commands_share_release_targets(self):
        spec = build.TARGET_SPECS["x86_64-unknown-linux-gnu"]
        local = build.cargo_command(spec)
        scm = build.cargo_command(spec, "1.90.0")
        self.assertEqual(scm[:2], ["cargo", "+1.90.0"])
        self.assertEqual(scm[2:], local[1:])
        self.assertEqual(local.count("--bin"), 3)

    def test_memory_abort_retries_real_processes(self):
        # Abort sleeping jobs 6 and 4 using synthetic measurements, not real RAM pressure.
        # Job 2 exits successfully. Recording child PIDs verifies termination.
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / "children"
            child = (
                "import os,time; "
                'j=os.environ["CARGO_BUILD_JOBS"]; '
                f'open({str(record)!r}, "a").write(j+" "+str(os.getpid())+"\\n"); '
                'time.sleep(30 if j != "2" else 0)'
            )
            samples = iter([2, 2, 0.5, 2, 2, 0.5])
            with patch.object(
                build,
                "available_memory",
                side_effect=lambda: int(next(samples, 2) * 1024**3),
            ):
                build.build_linux([sys.executable, "-c", child], dict(os.environ))
            children = [line.split() for line in record.read_text().splitlines()]
            self.assertEqual([j for j, _ in children], ["6", "4", "2"])
            for _, pid in children:
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(pid), 0)

    def test_compiler_failure_does_not_retry(self):
        with patch.object(build, "available_memory", return_value=2 * 1024**3):
            with self.assertRaises(subprocess.CalledProcessError) as caught:
                build.build_linux(
                    [sys.executable, "-c", "raise SystemExit(7)"], dict(os.environ)
                )
            self.assertEqual(caught.exception.returncode, 7)


if __name__ == "__main__":
    unittest.main()
