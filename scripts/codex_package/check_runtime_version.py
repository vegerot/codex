"""Verify the version clients receive from an actual packaged App Server."""

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile


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
