"""Verify the version clients receive from an actual packaged App Server."""

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path


async def main():
    binary = Path(sys.argv[1]).resolve()
    manifest = json.loads((binary.parent.parent / "codex-package.json").read_text())
    expected = manifest["version"]
    with tempfile.TemporaryDirectory(prefix="codex-version-check-") as directory:
        # Initialize only: no login, relay enrollment, tasks, or user configuration.
        process = await asyncio.create_subprocess_exec(
            str(binary),
            "app-server",
            "--listen",
            "stdio://",
            env={
                **os.environ,
                "CODEX_HOME": directory,
                "CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED": "1",
            },
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            request = {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "codex_version_check", "version": "1.0"}
                },
            }
            process.stdin.write((json.dumps(request) + "\n").encode())
            await process.stdin.drain()
            async with asyncio.timeout(20):
                while True:
                    line = await process.stdout.readline()
                    if not line:
                        raise RuntimeError("App Server exited before initialization")
                    response = json.loads(line)
                    if response.get("id") == 1:
                        break
            if "error" in response:
                raise RuntimeError(f"Initialization failed: {response['error']}")
            user_agent = response["result"]["userAgent"]
            actual = user_agent.split(" (", 1)[0].rsplit("/", 1)[-1]
            if actual != expected:
                raise RuntimeError(
                    f"App Server advertises {actual!r}, package specifies {expected!r}"
                )
            if manifest["target"].endswith("windows-msvc"):
                # Golden checksum from official Windows migration 1. Fresh-home
                # initialization alone cannot detect compatibility with older DBs.
                expected_checksum = bytes.fromhex(
                    "54bbd6f47905a4e4c674034575963d82da7b534e66e9a37a81ec2afb6a4b56ce6"
                    "de9b3ecf3032796a800f650239847d4"
                )
                database = sqlite3.connect(next(Path(directory).glob("state_*.sqlite")))
                try:
                    checksum = database.execute(
                        "SELECT checksum FROM _sqlx_migrations WHERE version = 1"
                    ).fetchone()[0]
                finally:
                    database.close()
                if checksum != expected_checksum:
                    raise RuntimeError(
                        "Windows migration checksum differs from official CRLF builds"
                    )
            print(f"App Server initialization verified package version {actual}")
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=10)
                except TimeoutError:
                    process.kill()
                    await process.wait()


if __name__ == "__main__":
    asyncio.run(main())
