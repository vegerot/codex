"""Exercise idle decisions without signaling the real daemon."""

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
spec = importlib.util.spec_from_file_location(
    "idle_restart", Path(__file__).with_name("restart-if-idle.py")
)
idle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(idle)


class IdleTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_pages_and_all_activity_sources_block(self):
        statuses = {
            "nightly": "idle",
            "thinking": "active",
            "approval": "active",
            "input": "active",
            "error": "systemError",
            "queued": "idle",
            "unknown": "futureStatus",
        }

        async def rpc(method, params):
            if method == "thread/loaded/list":
                if params["cursor"] is None:
                    return {
                        "data": ["nightly", "thinking", "approval"],
                        "nextCursor": "page2",
                    }
                return {
                    "data": ["input", "error", "queued", "unknown"],
                    "nextCursor": None,
                }
            thread_id = params["threadId"]
            if method == "thread/read":
                return {"thread": {"status": {"type": statuses[thread_id]}}}
            if method == "thread/queue/list":
                return {
                    "data": [{}] if thread_id == "queued" else [],
                    "nextCursor": None,
                }
            self.fail(method)

        busy = await idle.busy_threads(rpc)
        self.assertEqual(
            [item["threadId"] for item in busy],
            ["thinking", "approval", "input", "error", "queued", "unknown"],
        )

    async def test_completed_task_is_idle_but_active_nightly_is_not_excluded(self):
        status = "idle"

        async def rpc(method, params):
            if method == "thread/loaded/list":
                return {"data": ["nightly"], "nextCursor": None}
            if method == "thread/read":
                return {"thread": {"status": {"type": status}}}
            return {"data": [], "nextCursor": None}

        self.assertEqual(await idle.busy_threads(rpc), [])
        status = "active"
        self.assertEqual(
            await idle.busy_threads(rpc), [{"threadId": "nightly", "status": "active"}]
        )

    async def test_rpc_failure_does_not_report_idle(self):
        async def rpc(method, params):
            raise RuntimeError("unavailable")

        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            await idle.busy_threads(rpc)
