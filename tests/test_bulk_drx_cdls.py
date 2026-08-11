import tempfile
import unittest
from pathlib import Path
from unittest import mock

import src.server as s


class BulkDrxCdlsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.drx = str(Path(self.temp.name) / "look.drx")
        Path(self.drx).write_text("grade", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def _fixture(self):
        events = []
        graph = mock.Mock()
        graph.ApplyGradeFromDRX.side_effect = lambda path, mode: events.append(("drx", path, mode)) or True
        item = mock.Mock()
        item.GetUniqueId.return_value = "item-1"
        item.GetNodeGraph.return_value = graph
        item.SetCDL.side_effect = lambda cdl: events.append(("cdl", cdl)) or True
        timeline = mock.Mock()
        timeline.GetTrackCount.return_value = 1
        timeline.GetItemListInTrack.return_value = [item]
        return timeline, item, events

    def _params(self, **extra):
        return {
            "path": self.drx,
            "items": [{
                "timeline_item_id": "item-1",
                "cdl": {"NodeIndex": 1, "Slope": [1.1, 1.1, 1.1], "Offset": [0, 0, 0], "Power": [1, 1, 1], "Saturation": 1},
            }],
            **extra,
        }

    def test_defaults_to_dry_run(self):
        timeline, _, events = self._fixture()
        out = s._timeline_apply_drx_and_cdls_bulk(mock.Mock(), timeline, self._params())
        self.assertTrue(out["success"], out)
        self.assertTrue(out["dry_run"])
        self.assertEqual(events, [])

    def test_first_execute_call_issues_one_compound_confirmation(self):
        timeline, _, _ = self._fixture()
        with mock.patch.object(s, "_confirm_token_required", return_value=True), \
             mock.patch.object(s, "_issue_confirm_token", return_value={"confirm_token": "one-token"}) as issue:
            out = s._timeline_apply_drx_and_cdls_bulk(mock.Mock(), timeline, self._params(dry_run=False))
        self.assertEqual(out["confirm_token"], "one-token")
        self.assertEqual(issue.call_count, 1)

    def test_execution_applies_drx_before_item_cdl(self):
        timeline, _, events = self._fixture()
        with mock.patch.object(s, "_confirm_token_required", return_value=False):
            out = s._timeline_apply_drx_and_cdls_bulk(mock.Mock(), timeline, self._params(dry_run=False))
        self.assertTrue(out["success"], out)
        self.assertEqual([event[0] for event in events], ["drx", "cdl"])
        self.assertEqual(out["items"][0]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
