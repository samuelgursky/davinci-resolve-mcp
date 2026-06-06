"""Tests for the page-switch serialization lock."""
import threading
import time
import unittest
from unittest import mock

from src.utils import page_lock
from src.utils.page_lock import page_lock as plock, open_page_serialized


class PageLockTest(unittest.TestCase):
    def test_reentrant_no_deadlock(self):
        # Nested page_lock() in the same thread must not deadlock (the fcntl
        # lock is only taken at the outermost level).
        with plock():
            with plock():
                self.assertEqual(page_lock._depth, 2)
        self.assertEqual(page_lock._depth, 0)

    def test_open_page_serialized_calls_openpage(self):
        r = mock.Mock()
        r.OpenPage.return_value = True
        self.assertTrue(open_page_serialized(r, "color"))
        r.OpenPage.assert_called_once_with("color")

    def test_serializes_across_threads(self):
        order = []

        def worker():
            with plock():
                order.append("worker")

        with plock():
            t = threading.Thread(target=worker)
            t.start()
            time.sleep(0.05)  # give the worker a chance to (try to) acquire
            order.append("main")
        t.join()
        # The worker must have waited until main released the lock.
        self.assertEqual(order, ["main", "worker"])

    def test_depth_resets_on_exception(self):
        try:
            with plock():
                raise ValueError("boom")
        except ValueError:
            pass
        self.assertEqual(page_lock._depth, 0)


if __name__ == "__main__":
    unittest.main()
