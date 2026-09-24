#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["websockets==15.0.1"]
# ///
"""Load the announcement task, then enqueue a report without interrupting it."""

import argparse
import asyncio
import json
import os
import uuid
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
                "clientInfo": {"name": "devbox-rebuild", "version": "1"},
                "capabilities": {"experimentalApi": True},
            },
        )
        await socket.send(json.dumps({"method": "initialized"}))
        return socket
    except BaseException:
        await socket.close()
        raise


async def notify(thread_id, message):
    socket = await connect()
    try:
        await request(
            socket, 2, "thread/resume", {"threadId": thread_id, "excludeTurns": True}
        )
        receipt = await request(
            socket,
            3,
            "thread/queue/add",
            {
                "threadId": thread_id,
                "clientUserMessageId": str(uuid.uuid4()),
                "input": [{"type": "text", "text": message}],
            },
        )
        print(
            f"Queued announcement: {receipt['queuedSubmission']['id']} for task {thread_id}"
        )
    finally:
        await socket.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--thread", required=True)
    parser.add_argument("--message", required=True)
    args = parser.parse_args()
    asyncio.run(notify(args.thread, args.message))
