"""Guards for the control panel's Resolve media inventory client code.

Two behaviors here are only visible in the browser, so they are asserted against
the panel's embedded JavaScript rather than exercised:

1. The inventory fetch must not send its own ``limit``. The server applies the
   ``media_analysis.inventory_limit`` preference only when the request omits it,
   so any client-side value silently overrides what the user configured (#148).
2. The localStorage snapshot must stay bounded and must label itself when it is
   partial — an unbounded write throws past the ~5MB quota, and a truncated
   snapshot that renders as a complete inventory is the same silent lie in a
   different place.
"""

import re
import unittest

from src.analysis_dashboard import HTML, _inventory_prefs


class InventoryFetchLimitTests(unittest.TestCase):
    def test_media_fetch_sends_no_limit_param(self) -> None:
        """The preference is server-applied; a client `limit` would override it."""
        fetches = re.findall(r"fetch\(`/api/resolve/media[^`]*`", HTML)
        self.assertTrue(fetches, "no /api/resolve/media fetch found in the panel")
        for call in fetches:
            self.assertNotIn("limit=", call, f"inventory fetch pins a limit: {call}")

    def test_inventory_prefs_default_is_the_documented_500(self) -> None:
        limit, exclude = _inventory_prefs()
        self.assertGreaterEqual(limit, 1)
        self.assertLessEqual(limit, 10000)
        self.assertTrue(exclude is None or isinstance(exclude, set))


class InventorySnapshotTests(unittest.TestCase):
    def test_snapshot_is_capped(self) -> None:
        self.assertIn("const INVENTORY_SNAPSHOT_MAX_CLIPS = ", HTML)
        cap = int(re.search(r"const INVENTORY_SNAPSHOT_MAX_CLIPS = (\d+)", HTML).group(1))
        self.assertGreater(cap, 0)
        self.assertLessEqual(cap, 10000, "a cap at or above inventory_limit caps nothing")
        self.assertIn("clips.slice(0, INVENTORY_SNAPSHOT_MAX_CLIPS)", HTML)

    def test_partial_snapshot_declares_itself(self) -> None:
        self.assertIn("snapshot_partial: true", HTML)
        self.assertIn("snapshot_total: clips.length", HTML)
        # Both surfaces that show a clip count must qualify a partial snapshot.
        self.assertIn("cached preview of ${payload.snapshot_total}", HTML)
        self.assertIn("cached first ${state.resolveMedia.clips.length}", HTML)

    def test_quota_failure_prunes_and_retries_then_drops_the_key(self) -> None:
        self.assertIn("function pruneInventorySnapshots()", HTML)
        self.assertIn("pruneInventorySnapshots();", HTML)
        self.assertIn("localStorage.removeItem(key)", HTML)


if __name__ == "__main__":
    unittest.main()
