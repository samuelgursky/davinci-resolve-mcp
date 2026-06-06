"""Tests for the bridge-call counting instrumentation."""
import unittest

from src.utils.bridge_metrics import CountingProxy, measure


class Inner:
    def Val(self):
        return 7


class Outer:
    prop = 5

    def GetInner(self):
        return Inner()

    def GetList(self):
        return [Inner(), Inner()]


class CountingProxyTest(unittest.TestCase):
    def test_counts_attr_access_and_calls(self):
        c = {}
        p = CountingProxy(Outer(), c)
        self.assertEqual(p.prop, 5)            # attr_access
        inner = p.GetInner()                   # attr_access + call, wrapped
        self.assertEqual(inner.Val(), 7)       # attr_access + call -> primitive
        self.assertEqual(c["attr_access"], 3)
        self.assertEqual(c["calls"], 2)

    def test_wraps_list_elements(self):
        c = {}
        p = CountingProxy(Outer(), c)
        items = p.GetList()                    # attr_access + call
        for it in items:
            it.Val()                           # 2x (attr_access + call) each
        self.assertEqual(c["calls"], 3)        # GetList + 2 Val
        self.assertEqual(c["attr_access"], 3)  # GetList + 2 Val

    def test_primitives_not_wrapped(self):
        c = {}
        p = CountingProxy(Outer(), c)
        self.assertIsInstance(p.prop, int)

    def test_measure_helper(self):
        counts = measure(lambda px: px.GetInner().Val(), Outer())
        self.assertEqual(counts["calls"], 2)


if __name__ == "__main__":
    unittest.main()
