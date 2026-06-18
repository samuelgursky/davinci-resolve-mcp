"""Institutional guard for the issue-#70 bug class.

Every catalogued Resolve API whose failure mode is "enum-keyed settings/args are
silently rejected when handed plain strings" (tag ``enum``) must declare a
``mitigation`` — the resolver/wrapper(s) that translate human-readable input into
live enum constants. This test asserts:

  1. every ``enum``-tagged API_TRUTH entry has a non-empty ``mitigation`` list, and
  2. each named mitigation is a real callable in src.server.

So the next time someone documents an enum-keyed silent-failure symbol, they must
also wire a concrete resolver (or this fails), and renaming/removing a resolver
without updating the catalog fails too. Catches raw-passthrough regressions like
the v2.54.1 timeline.export fix before they ship.
"""
import unittest

import src.server as s
from src.utils.api_truth import API_TRUTH


class ApiTruthMitigationGuard(unittest.TestCase):
    def test_enum_tagged_entries_declare_existing_mitigations(self):
        enum_entries = [e for e in API_TRUTH if "enum" in e.get("tags", [])]
        # Sanity: the catalog should actually contain enum-class entries.
        self.assertGreaterEqual(len(enum_entries), 4, "expected the known enum-class entries")
        for entry in enum_entries:
            symbol = entry.get("symbol", "<unknown>")
            mitigation = entry.get("mitigation")
            self.assertTrue(
                isinstance(mitigation, list) and mitigation,
                f"enum-tagged api_truth entry {symbol!r} must declare a non-empty "
                f"'mitigation' list of resolver function names",
            )
            for name in mitigation:
                fn = getattr(s, name, None)
                self.assertTrue(
                    callable(fn),
                    f"api_truth entry {symbol!r} names mitigation {name!r}, but "
                    f"src.server has no such callable (renamed or removed?)",
                )


if __name__ == "__main__":
    unittest.main()
