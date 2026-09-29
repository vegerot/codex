"""Exercise idle decisions without signaling the real daemon."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.codex_package import idle_tasks as idle


class IdleTests(unittest.IsolatedAsyncioTestCase):
    async def test_ephemeral_tasks_still_block_when_active_without_queue_query(self):
        async def rpc(method, params):
            if method == "thread/loaded/list":
                return {"data": ["idle", "active"], "nextCursor": None}
            if method == "thread/read":
                return {
                    "thread": {
                        "ephemeral": True,
                        "status": {"type": params["threadId"]},
                    }
                }
            self.fail("Ephemeral tasks must not query submission queues")

        self.assertEqual(
            await idle.busy_threads(rpc), [{"threadId": "active", "status": "active"}]
        )

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


class OwnershipTests(unittest.TestCase):
    def test_unmanaged_server_does_not_require_a_pid_record(self):
        import importlib.util
        import json
        from unittest.mock import patch

        spec = importlib.util.spec_from_file_location(
            "linux_idle", Path(__file__).with_name("restart-if-idle.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(
            module.subprocess,
            "check_output",
            return_value=json.dumps({"status": "running"}),
        ):
            self.assertEqual(
                module.restart(package=Path("/unused")),
                {
                    "status": "deferred",
                    "reason": "Running App Server is not managed by codex app-server daemon",
                },
            )
