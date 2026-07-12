"""Sync tool bodies are moved off the event loop into a worker thread so a
blocking call cannot freeze the transport."""
import threading
import unittest

import anyio

from src.server import _install_threaded_tool_dispatch


class FakeTool:
    def __init__(self, fn, is_async=False, name="t"):
        self.fn = fn
        self.is_async = is_async
        self.name = name


class FakeManager:
    def __init__(self, tools):
        self._tools = tools


class FakeMCP:
    def __init__(self, tools):
        self._tool_manager = FakeManager(tools)


class ThreadedToolDispatchTest(unittest.TestCase):
    def test_wraps_sync_tools_and_skips_async(self):
        sync_tool = FakeTool(lambda **kw: {"ok": True}, is_async=False, name="sync")
        async_fn = sync_tool  # placeholder
        async_tool = FakeTool(async_fn, is_async=True, name="async")
        mcp = FakeMCP({"sync": sync_tool, "async": async_tool})

        wrapped = _install_threaded_tool_dispatch(mcp)
        self.assertEqual(wrapped, 1)
        self.assertTrue(sync_tool.is_async)   # now presented as async
        self.assertTrue(async_tool.is_async)  # untouched

    def test_wrapped_tool_runs_off_thread_and_returns_result(self):
        main_thread = threading.current_thread().name

        def body(**kwargs):
            return {"value": kwargs["x"], "thread": threading.current_thread().name}

        tool = FakeTool(body, is_async=False, name="body")
        _install_threaded_tool_dispatch(FakeMCP({"body": tool}))

        result = anyio.run(lambda: tool.fn(x=42))
        self.assertEqual(result["value"], 42)
        self.assertNotEqual(result["thread"], main_thread)  # ran off the event-loop thread

    def test_missing_tool_manager_is_a_noop(self):
        self.assertEqual(_install_threaded_tool_dispatch(object()), 0)

    def test_non_mapping_tools_is_a_noop(self):
        # A future SDK shape that isn't a dict must degrade to inline, not crash.
        self.assertEqual(_install_threaded_tool_dispatch(FakeMCP(["not", "a", "map"])), 0)


if __name__ == "__main__":
    unittest.main()
