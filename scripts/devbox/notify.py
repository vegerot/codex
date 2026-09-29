#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["websockets==15.0.1"]
# ///
"""Load the announcement task, then enqueue a report without interrupting it."""

import argparse
import asyncio
import uuid
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.codex_package.rpc import connect, request


async def notify(thread_id, message=None, check=False):
    socket = await connect()
    try:
        if check:
            await request(
                socket, 2, "thread/read", {"threadId": thread_id, "includeTurns": False}
            )
            print(f"Coordinator task is accessible: {thread_id}")
            return
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
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--message")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args()
    asyncio.run(notify(args.thread, args.message, args.check))
