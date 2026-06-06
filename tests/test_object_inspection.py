"""Unit tests for src/utils/object_inspection.py.

Covers the single-pass member walk, the C-extension signature guard, the
__doc__-based docstring read, and back-compat of the thin wrappers.
"""
import unittest

import src.utils.object_inspection as oi


class _Fake:
    """A fake Resolve-ish object."""

    attr_prop = 42

    def GetName(self):
        """Return the name."""
        return "x"

    def GetClipProperty(self, key):
        return key


class _CExtMethod:
    """Method-like object that is callable but not a function/method.

    Mimics a Resolve C-extension bound method: inspect.signature() raises and
    inspect.isfunction/ismethod are both False, so the signature guard must
    short-circuit to "()" without calling inspect.signature.
    """

    def __init__(self):
        self.signature_called = False

    def __call__(self, *args, **kwargs):  # pragma: no cover - never invoked
        return None


class _FakeWithCExt:
    def __init__(self, cext):
        self.NativeCall = cext
        self.value = 7


class GetObjectMembersTest(unittest.TestCase):
    def test_classifies_methods_and_properties_single_pass(self):
        m = oi.get_object_members(_Fake())
        self.assertIn("GetName", m["methods"])
        self.assertIn("GetClipProperty", m["methods"])
        self.assertIn("attr_prop", m["properties"])
        # private attrs skipped
        self.assertNotIn("__init__", m["methods"])

    def test_include_flags_limit_work(self):
        only_methods = oi.get_object_members(_Fake(), include_properties=False)
        self.assertIn("methods", only_methods)
        self.assertNotIn("properties", only_methods)

        only_props = oi.get_object_members(_Fake(), include_methods=False)
        self.assertIn("properties", only_props)
        self.assertNotIn("methods", only_props)

    def test_bound_method_signature_resolved(self):
        m = oi.get_object_members(_Fake())
        # GetName(self) -> "()" once self is bound; GetClipProperty(self, key) -> "(key)"
        self.assertEqual(m["methods"]["GetName"]["signature"], "()")
        self.assertEqual(m["methods"]["GetClipProperty"]["signature"], "(key)")
        self.assertEqual(m["methods"]["GetName"]["doc"], "Return the name.")

    def test_signature_guard_skips_inspect_signature_for_c_ext(self):
        # A callable that is neither a function nor a method must NOT trigger
        # inspect.signature (the slow/raising path) and must default to "()".
        import inspect as _inspect

        calls = {"n": 0}
        real_signature = _inspect.signature

        def counting_signature(x):
            calls["n"] += 1
            return real_signature(x)

        cext = _CExtMethod()
        obj = _FakeWithCExt(cext)
        try:
            _inspect.signature = counting_signature
            m = oi.get_object_members(obj)
        finally:
            _inspect.signature = real_signature

        self.assertIn("NativeCall", m["methods"])
        self.assertEqual(m["methods"]["NativeCall"]["signature"], "()")
        self.assertIn("value", m["properties"])
        # The C-ext callable must not have hit inspect.signature.
        self.assertEqual(calls["n"], 0)

    def test_none_returns_error(self):
        self.assertIn("error", oi.get_object_members(None))


class BackCompatWrapperTest(unittest.TestCase):
    def test_get_object_methods_wrapper(self):
        methods = oi.get_object_methods(_Fake())
        self.assertIn("GetName", methods)
        self.assertNotIn("attr_prop", methods)

    def test_get_object_properties_wrapper(self):
        props = oi.get_object_properties(_Fake())
        self.assertIn("attr_prop", props)
        self.assertNotIn("GetName", props)

    def test_wrappers_preserve_none_error(self):
        self.assertIn("error", oi.get_object_methods(None))
        self.assertIn("error", oi.get_object_properties(None))


class InspectObjectTest(unittest.TestCase):
    def test_shape(self):
        out = oi.inspect_object(_Fake())
        self.assertEqual(out["type"], "_Fake")
        self.assertIn("GetName", out["methods"])
        self.assertIn("attr_prop", out["properties"])
        self.assertIn("str", out)

    def test_none(self):
        self.assertIn("error", oi.inspect_object(None))


class PrintObjectHelpTest(unittest.TestCase):
    def test_renders_methods_and_properties(self):
        h = oi.print_object_help(_Fake())
        self.assertIn("GetName", h)
        self.assertIn("attr_prop", h)
        self.assertIn("Return the name.", h)

    def test_none(self):
        self.assertEqual(oi.print_object_help(None), "Cannot provide help for None object")


if __name__ == "__main__":
    unittest.main()
