"""Managed App Server JSON-RPC transport shared by nightly operations."""

import asyncio
import json
import os
from pathlib import Path

from websockets.asyncio.client import unix_connect


async def request(socket, request_id, method, params):
    await socket.send(
        json.dumps({"id": request_id, "method": method, "params": params})
    )
    while line := await asyncio.wait_for(socket.recv(), timeout=60):
        response = json.loads(line)
        if response.get("id") == request_id:
            if "error" in response:
                raise RuntimeError(response["error"])
            return response["result"]
    raise RuntimeError("App Server closed before acknowledging the request")


async def connect():
    socket = await unix_connect(
        str(
            Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
            / "app-server-control/app-server-control.sock"
        ),
        uri="ws://localhost/rpc",
        # The current App Server rejects permessage-deflate negotiation.
        compression=None,
        max_size=8 * 1024 * 1024,
    )

    try:
        await request(
            socket,
            1,
            "initialize",
            {
                "clientInfo": {"name": "codex-nightly", "version": "1"},
                "capabilities": {"experimentalApi": True},
            },
        )
        await socket.send(json.dumps({"method": "initialized"}))
        return socket
    except BaseException:
        await socket.close()
        raise
