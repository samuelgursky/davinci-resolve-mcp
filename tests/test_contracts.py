"""Tests for the declarative parameter-contract validator and safe subprocess wrappers."""
import subprocess
import unittest

from src.utils.contracts import validate
from src.utils import proc


class ValidateTest(unittest.TestCase):
    def test_required_missing(self):
        err, clean = validate({}, {"x": {"type": int, "required": True}})
        self.assertIn("'x' is required", err)
        self.assertIsNone(clean)

    def test_default_applied(self):
        err, clean = validate({}, {"k": {"enum": ["a", "b"], "default": "a"}})
        self.assertIsNone(err)
        self.assertEqual(clean["k"], "a")

    def test_int_coercion(self):
        err, clean = validate({"n": "42"}, {"n": {"type": int}})
        self.assertIsNone(err)
        self.assertEqual(clean["n"], 42)

    def test_int_bad(self):
        err, _ = validate({"n": "x"}, {"n": {"type": int}})
        self.assertIn("must be an integer", err)

    def test_enum_reject(self):
        err, _ = validate({"k": "z"}, {"k": {"enum": ["a", "b"]}})
        self.assertIn("must be one of: a, b", err)

    def test_non_empty(self):
        err, _ = validate({"s": "   "}, {"s": {"type": str, "non_empty": True}})
        self.assertIn("must be non-empty", err)

    def test_min_max(self):
        self.assertIn("must be >= 0", validate({"n": -1}, {"n": {"type": int, "min": 0}})[0])
        self.assertIn("must be <= 10", validate({"n": 11}, {"n": {"type": int, "max": 10}})[0])

    def test_parent_dir_exists(self):
        err, _ = validate({"p": "/no/such/dir/x.png"}, {"p": {"type": str, "parent_dir_exists": True}})
        self.assertIn("target directory does not exist", err)
        err2, clean = validate({"p": "/tmp/x.png"}, {"p": {"type": str, "parent_dir_exists": True}})
        self.assertIsNone(err2)
        self.assertEqual(clean["p"], "/tmp/x.png")

    def test_invariant(self):
        err, _ = validate(
            {"a": 5, "b": 3},
            {"a": {"type": int}, "b": {"type": int}},
            invariants=[lambda c: "a must be <= b" if c["a"] > c["b"] else None],
        )
        self.assertEqual(err, "a must be <= b")

    def test_invariant_passes(self):
        err, clean = validate(
            {"a": 1, "b": 3},
            {"a": {"type": int}, "b": {"type": int}},
            invariants=[lambda c: "a must be <= b" if c["a"] > c["b"] else None],
        )
        self.assertIsNone(err)
        self.assertEqual(clean["a"], 1)


class SafeRunTest(unittest.TestCase):
    def test_safe_run_defaults_stdin_devnull(self):
        # echo via python; the point is stdin is DEVNULL and it doesn't hang/inherit.
        r = proc.safe_run(["python3", "-c", "print('ok')"], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0)
        self.assertIn("ok", r.stdout)

    def test_safe_run_allows_input(self):
        # input= and stdin are mutually exclusive in subprocess; safe_run must
        # not inject DEVNULL when input is provided.
        r = proc.safe_run(["cat"], input="hello", capture_output=True, text=True, timeout=10)
        self.assertEqual(r.stdout, "hello")


if __name__ == "__main__":
    unittest.main()
