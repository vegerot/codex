import tempfile
import unittest
from pathlib import Path

import tomllib

from scripts.codex_package.nightly_version import latest_stable_version, stamp_workspace


class NightlyVersionTests(unittest.TestCase):
    def test_stable_tags_sort_numerically_and_ignore_alpha(self):
        refs = (
            "abc refs/tags/rust-v0.99.0\n"
            "def refs/tags/rust-v0.156.1\n"
            "123 refs/tags/rust-v0.157.0-alpha.9\n"
        )
        self.assertEqual(latest_stable_version(refs), "0.156.1")
        with self.assertRaises(RuntimeError):
            latest_stable_version("abc refs/tags/rust-v0.157.0-alpha.9")

    def test_stamp_preserves_external_dependencies_and_updates_local_refs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "Cargo.toml"
            lock = root / "Cargo.lock"
            manifest.write_text(
                '[workspace.package]\nversion = "0.0.0"\nedition = "2024"\n'
            )
            lock.write_text("""version = 4
[[package]]
name = "codex-cli"
version = "0.0.0"
dependencies = ["codex-core 0.0.0", "external"]
[[package]]
name = "codex-core"
version = "0.0.0"
[[package]]
name = "external"
version = "1.2.3"
source = "registry+https://example.com"
checksum = "unchanged"
""")
            version = stamp_workspace(root, "0.156.1", "a" * 40)
            self.assertEqual(version, "0.156.1+dev.aaaaaaaaaaaa")
            self.assertEqual(
                tomllib.loads(manifest.read_text()),
                {"workspace": {"package": {"version": version, "edition": "2024"}}},
            )
            self.assertEqual(
                tomllib.loads(lock.read_text()),
                {
                    "version": 4,
                    "package": [
                        {
                            "name": "codex-cli",
                            "version": version,
                            "dependencies": [f"codex-core {version}", "external"],
                        },
                        {"name": "codex-core", "version": version},
                        {
                            "name": "external",
                            "version": "1.2.3",
                            "source": "registry+https://example.com",
                            "checksum": "unchanged",
                        },
                    ],
                },
            )


if __name__ == "__main__":
    unittest.main()
