"""Shared idle checks for nightly daemon restarts on Linux and macOS."""

from scripts.codex_package.rpc import connect, request


async def busy_threads(rpc):
    busy = []
    cursor = None
    while True:
        page = await rpc("thread/loaded/list", {"cursor": cursor, "limit": 100})
        for thread_id in page["data"]:
            thread = (
                await rpc("thread/read", {"threadId": thread_id, "includeTurns": False})
            )["thread"]
            status = thread["status"]["type"]
            # Waiting on approval/input is still active work. Unknown/error states
            # cannot establish idleness. Never exclude the nightly's own task.
            if status not in ("idle", "notLoaded"):
                busy.append({"threadId": thread_id, "status": status})
            elif not thread.get("ephemeral", False):
                # Idle ephemeral tasks have no submission queue.
                queue = await rpc(
                    "thread/queue/list", {"threadId": thread_id, "limit": 1}
                )
                if queue["data"]:
                    busy.append({"threadId": thread_id, "status": "queued"})
        cursor = page["nextCursor"]
        if cursor is None:
            return busy


async def inspect_tasks():
    socket = await connect()
    request_id = 1

    async def rpc(method, params):
        nonlocal request_id
        request_id += 1
        return await request(socket, request_id, method, params)

    try:
        return await busy_threads(rpc)
    finally:
        await socket.close()
