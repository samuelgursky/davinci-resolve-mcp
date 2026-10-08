"""Live preset orchestration must retain the original and reject lossy imports."""
import json
import tempfile
import unittest
from unittest.mock import Mock, patch
from src.utils import subtitle_live as live


class SubtitleLiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.r, self.p, self.t, self.imported = Mock(), Mock(), Mock(), Mock()
        self.t.GetName.return_value = 'Original'
        self.t.GetTrackCount.return_value = 1
        self.t.GetUniqueId.return_value = 'original'
        self.t.GetCurrentTimecode.return_value = '01:00:01:00'
        self.p.GetTimelineCount.return_value = 0
        self.p.GetCurrentTimeline.return_value = self.t
        self.p.GetMediaPool.return_value.ImportTimelineFromFile.return_value = self.imported
        self.imported.GetName.return_value = 'Revision'
        self.imported.GetUniqueId.return_value = 'revision'
        self.imported.GetCurrentTimecode.return_value = '01:00:01:00'
        self.p.SetCurrentTimeline.side_effect = lambda timeline: setattr(self.p.GetCurrentTimeline, 'return_value', timeline) or True

    def call(self, params=None, inventories=None):
        with patch.object(live.shutil, 'which', return_value='node'), \
             patch.object(live.subprocess, 'run', side_effect=[
                 Mock(returncode=0, stdout=json.dumps({'templateId': 'Word Highlight', 'after': {'textRed': 0}})),
                 Mock(returncode=0, stdout=json.dumps({'templateId': 'Word Highlight', 'inputs': {'textRed': 0}}))]), \
             patch.object(live, '_inventory', side_effect=inventories or [{'edit': 1}, {'edit': 1}]):
            return live.set_subtitle_preset(self.r, self.p, self.t,
                                           params or {'inputs': {'textRed': 0}, 'revision_name': 'Revision'},
                                           lambda _: self.tmp.name)

    def test_success_selects_revision_and_keeps_original(self):
        result = self.call()
        self.assertTrue(result['success'])
        self.assertFalse(result['restart_required'])
        self.assertFalse(result['render_verified'])
        self.p.SetCurrentTimeline.assert_called_once_with(self.imported)
        self.p.GetMediaPool.return_value.DeleteTimelines.assert_not_called()
        self.imported.SetCurrentTimecode.assert_called_once_with('01:00:01:00')

    def test_lossy_import_restores_original_and_reports_failure(self):
        result = self.call(inventories=[{'subtitles': 7}, {'subtitles': 0}])
        self.assertFalse(result['success'])
        self.assertIn('differs', result['error'])
        self.p.SetCurrentTimeline.assert_called_once_with(self.t)
        self.assertEqual(result['failed_revision'], 'Revision')

    def test_preview_never_imports(self):
        result = self.call({'inputs': {'size': 0.1}, 'dry_run': True})
        self.assertTrue(result['dry_run'])
        self.p.GetMediaPool.assert_not_called()
        self.p.SetCurrentTimeline.assert_called_once_with(self.t)

    def test_resolve_reexport_cannot_silently_lose_requested_controls(self):
        responses = [
            Mock(returncode=0, stdout=json.dumps({'templateId': 'Word Highlight', 'after': {'textRed': 0}})),
            Mock(returncode=0, stdout=json.dumps({'templateId': 'Word Highlight', 'inputs': {'textRed': 1}})),
        ]
        with patch.object(live.shutil, 'which', return_value='node'), \
             patch.object(live.subprocess, 'run', side_effect=responses), \
             patch.object(live, '_inventory', return_value={'edit': 1}):
            result = live.set_subtitle_preset(self.r, self.p, self.t,
                                             {'inputs': {'textRed': 0}, 'revision_name': 'Revision'},
                                             lambda _: self.tmp.name)
        self.assertFalse(result['success'])
        self.assertIn('did not retain', result['error'])
        self.p.SetCurrentTimeline.assert_called_once_with(self.t)

    def test_granular_connection_failure_cannot_launch_second_instance(self):
        from src.granular import common
        for running in (True, None):
            with patch.object(common, 'resolve', None), patch.object(common, '_try_connect', return_value=None), \
                 patch.object(common.resolve_runtime, 'runtime_mode', return_value={'running': running}), \
                 patch.object(common, '_launch_resolve') as launch:
                self.assertIsNone(common.get_resolve())
                launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
