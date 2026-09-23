"""Smoke-test the actual packaged V8 host over its framed stdio protocol."""

import asyncio
import json
import struct
import sys


async def main():
    host = await asyncio.create_subprocess_exec(
        sys.argv[1], stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE
    )

    async def send(message):
        data = json.dumps(message).encode()
        host.stdin.write(struct.pack("<I", len(data)) + data)
        await host.stdin.drain()

    async def receive():
        prefix = await asyncio.wait_for(host.stdout.readexactly(4), timeout=20)
        size = struct.unpack("<I", prefix)[0]
        return json.loads(
            await asyncio.wait_for(host.stdout.readexactly(size), timeout=20)
        )

    try:
        await send(
            {
                "type": "connection/hello",
                "supportedVersions": [1],
                "requiredCapabilities": [],
                "optionalCapabilities": [],
            }
        )
        hello = await receive()
        assert hello["type"] == "connection/ready", hello
        await send(
            {
                "type": "operation/request",
                "id": 1,
                "request": {"method": "session/open", "sessionId": "scm-pilot"},
            }
        )
        ready = await receive()
        assert ready["result"]["status"] == "ok", ready
        await send(
            {
                "type": "operation/request",
                "id": 2,
                "request": {
                    "method": "session/execute",
                    "sessionId": "scm-pilot",
                    "request": {
                        "tool_call_id": "scm-pilot-test",
                        "enabled_tools": [],
                        "source": "text(6 * 7)",
                        "yield_time_ms": 10000,
                        "max_output_tokens": 100,
                    },
                },
            }
        )
        while True:
            response = await receive()
            print(json.dumps(response), flush=True)
            if response["type"] == "execute/initialResponse":
                assert response["result"]["status"] == "ok", response
                assert '"42"' in json.dumps(response["result"]["value"]), response
                break
        await send(
            {
                "type": "operation/request",
                "id": 3,
                "request": {"method": "session/shutdown", "sessionId": "scm-pilot"},
            }
        )
        host.stdin.close()
        await asyncio.wait_for(host.wait(), timeout=20)
        assert host.returncode == 0, host.returncode
        print("V8 host executed text(6 * 7) successfully")
    finally:
        if host.returncode is None:
            host.kill()
            await host.wait()


asyncio.run(main())
