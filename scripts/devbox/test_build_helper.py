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
    def test_macos_route(self):
        with (
            patch.object(build.platform, "system", return_value="Darwin"),
            patch.object(build.platform, "machine", return_value="arm64"),
            patch.object(build, "validate_existing_package"),
            patch.object(build, "resolve_codex_v8_cargo_env", return_value={}),
            patch.object(build, "install_release_binaries") as install,
            patch.object(build, "build_linux") as linux,
            patch.object(build.subprocess, "run") as run,
        ):
            build.main()
            command = run.call_args.args[0]
            self.assertEqual(
                command[command.index("--target") + 1], "aarch64-apple-darwin"
            )
            self.assertEqual(command.count("--bin"), 2)
            linux.assert_not_called()
            install.assert_called_once_with(build.TARGET_SPECS["aarch64-apple-darwin"])

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

    def test_linux_package_install_includes_bwrap_and_preserves_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "package"
            output = root / "output"
            output.mkdir()
            (package / "bin").mkdir(parents=True)
            (package / "codex-path").mkdir()
            (package / "codex-resources").mkdir()
            metadata = {
                "layoutVersion": 1,
                "target": "x86_64-unknown-linux-gnu",
                "variant": "codex",
                "entrypoint": "bin/codex",
                "resourcesDir": "codex-resources",
                "pathDir": "codex-path",
            }
            (package / "codex-package.json").write_text(json.dumps(metadata))
            rg = root / "rg"
            rg.write_text("resource")
            rg.chmod(0o755)
            (package / "codex-path/rg").symlink_to(rg)
            (output / "bwrap").write_text("newbwrap")
            (output / "bwrap").chmod(0o755)
            for name in ("codex", "codex-code-mode-host"):
                for folder, contents in ((package / "bin", "old"), (output, "new")):
                    (folder / name).write_text(contents + name)
                    (folder / name).chmod(0o755)
            with (
                patch.object(build, "PACKAGE_DIR", package),
                patch.object(build, "cargo_profile_output_dir", return_value=output),
            ):
                build.install_release_binaries(build.TARGET_SPECS[metadata["target"]])
                metadata["target"] = "aarch64-apple-darwin"
                (package / "codex-package.json").write_text(json.dumps(metadata))
                with self.assertRaisesRegex(RuntimeError, "target"):
                    build.validate_existing_package(
                        build.TARGET_SPECS["x86_64-unknown-linux-gnu"]
                    )
            self.assertTrue((package / "codex-path/rg").is_symlink())
            self.assertEqual(
                (package / "codex-resources/bwrap").read_text(), "newbwrap"
            )
            for name in ("codex", "codex-code-mode-host"):
                self.assertEqual((package / "bin" / name).read_text(), "new" + name)


if __name__ == "__main__":
    unittest.main()
