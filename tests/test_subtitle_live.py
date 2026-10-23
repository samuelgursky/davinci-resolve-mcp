"""Live preset orchestration must retain the original and reject lossy imports."""
import json
from pathlib import Path
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
        # The codec-dep check reads this checkout. Tests that mock Node must
        # not fail when resolve-advanced/node_modules is absent.
        self.gap = patch.object(live, 'subtitle_codec_gap', return_value=None)
        self.gap.start()
        self.addCleanup(self.gap.stop)

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
        self.assertFalse(result['staging_retained'])
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
        self.assertNotIn('original_export', result)
        self.assertIn('audio_content', result['unverified_components'])

    def test_lossy_import_restores_original_and_reports_failure(self):
        result = self.call(inventories=[{'subtitles': 7}, {'subtitles': 0}])
        self.assertFalse(result['success'])
        self.assertIn('differs', result['error'])
        self.p.SetCurrentTimeline.assert_called_once_with(self.t)
        self.assertEqual(result['failed_revision'], 'Revision')
        self.assertTrue(result['staging_retained'])
        self.assertTrue(Path(result['staging_directory']).is_dir())

    def test_preview_never_imports(self):
        result = self.call({'inputs': {'size': 0.1}, 'dry_run': True})
        self.assertTrue(result['dry_run'])
        self.p.GetMediaPool.assert_not_called()
        self.p.SetCurrentTimeline.assert_called_once_with(self.t)
        self.assertFalse(result['staging_retained'])
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

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

    def test_literal_readback_mismatch_restores_original(self):
        responses = [
            Mock(returncode=0, stdout=json.dumps({'templateId': 'Word Highlight', 'after': {}, 'literalAfter': {'Size': 0.09}})),
            Mock(returncode=0, stdout=json.dumps({'templateId': 'Word Highlight', 'inputs': {}, 'literalInputs': [{'name': 'Size', 'value': 0.08}]})),
        ]
        with patch.object(live.shutil, 'which', return_value='node'), \
             patch.object(live.subprocess, 'run', side_effect=responses), \
             patch.object(live, '_inventory', return_value={'edit': 1}):
            result = live.set_subtitle_preset(self.r, self.p, self.t,
                                             {'literal_inputs': {'Size': 0.09}, 'revision_name': 'Revision'}, lambda _: self.tmp.name)
        self.assertFalse(result['success'])
        self.assertIn('literal', result['error'])
        self.p.SetCurrentTimeline.assert_called_once_with(self.t)

    def test_input_listing_exports_without_import_or_timeline_switch(self):
        with patch.object(live.shutil, 'which', return_value='node'), \
             patch.object(live.subprocess, 'run', return_value=Mock(returncode=0, stdout=json.dumps({
                 'templateId': 'Word Highlight', 'literalInputs': [{'name': 'Size', 'value': 0.08, 'writable': True}]}))):
            result = live.list_subtitle_preset_inputs(self.r, self.t, {}, lambda _: self.tmp.name)
        self.assertTrue(result['success'])
        self.t.Export.assert_called_once()
        self.p.GetMediaPool.assert_not_called()
        self.p.SetCurrentTimeline.assert_not_called()
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_input_listing_reports_cleanup_failure_and_invalid_track(self):
        for track in (0, True, 2):
            with self.subTest(track=track):
                result = live.list_subtitle_preset_inputs(self.r, self.t, {'track': track}, lambda _: self.tmp.name)
                self.assertFalse(result['success'])
                self.t.Export.assert_not_called()
        with patch.object(live.shutil, 'which', return_value='node'), \
             patch.object(live.subprocess, 'run', return_value=Mock(returncode=0, stdout='{}')), \
             patch.object(live.shutil, 'rmtree', side_effect=OSError('cleanup refused')):
            result = live.list_subtitle_preset_inputs(self.r, self.t, {}, lambda _: self.tmp.name)
        self.assertTrue(result['success'])
        self.assertTrue(result['staging_retained'])
        self.assertTrue(Path(result['staging_directory']).is_dir())
        self.assertIn('cleanup refused', result['warnings'][0])

    def test_bad_literal_container_refuses_before_export(self):
        result = self.call({'literal_inputs': []})
        self.assertFalse(result['success'])
        self.t.Export.assert_not_called()

    def test_missing_node_deps_fail_before_node_is_spawned(self):
        with patch.object(live.shutil, 'which', return_value='node'), \
             patch.object(live, 'subtitle_codec_gap', return_value='missing jszip'), \
             patch.object(live.subprocess, 'run') as run:
            result = live.set_subtitle_preset(
                self.r, self.p, self.t, {'inputs': {'textRed': 0}}, lambda _: self.tmp.name)
        self.assertFalse(result['success'])
        self.assertIn('jszip', result['error'])
        run.assert_not_called()
        self.t.Export.assert_not_called()

    def test_codec_gap_names_the_install_command(self):
        root = Path(self.tmp.name) / 'tree'
        advanced = root / 'resolve-advanced'
        advanced.mkdir(parents=True)
        (advanced / 'package.json').write_text(
            json.dumps({'dependencies': {'jszip': '^3.10.1'}}), encoding='utf-8')
        real = self.gap.temp_original
        with patch.object(live, 'ROOT', root), patch.object(live, '_ADVANCED', advanced):
            gap = real()
        self.assertIn('jszip', gap)
        self.assertIn('npm install --omit=dev --omit=optional', gap)
        (advanced / 'node_modules' / 'jszip').mkdir(parents=True)
        with patch.object(live, 'ROOT', root), patch.object(live, '_ADVANCED', advanced):
            self.assertIsNone(real())

    def test_uncoerced_helper_input_refuses_before_export_or_import(self):
        result = self.call({'dry_run': 'true'})
        self.assertFalse(result['success'])
        self.t.Export.assert_not_called()
        self.p.GetMediaPool.assert_not_called()

    def test_cleanup_failure_reports_retained_staging(self):
        with patch.object(live.shutil, 'rmtree', side_effect=OSError('cleanup refused')):
            result = self.call()
        self.assertTrue(result['success'])
        self.assertTrue(result['staging_retained'])
        self.assertTrue(Path(result['staging_directory']).is_dir())
        self.assertIn('cleanup refused', result['warnings'][0])

    def test_dispatch_string_preview_in_safe_mode_never_imports_or_captures(self):
        from src import server
        from src.utils import destructive_hook as hook
        preferences = lambda key: True if key == 'destructive.safe_mode' else False
        for key in ('dry_run', 'dryRun'):
            for value in ('true', 'yes', '1', 'on', True):
                with self.subTest(key=key, value=value), \
                     patch.object(hook, '_PREFERENCE_PROVIDER', preferences), \
                     patch.object(hook, '_PROVIDER', side_effect=AssertionError('must not archive')), \
                     patch.object(server, '_get_tl', return_value=(self.p, self.t, None)), \
                     patch.object(server, 'get_resolve', return_value=self.r), \
                     patch.object(server, '_resolve_safe_dir', return_value=self.tmp.name), \
                     patch.object(live.shutil, 'which', return_value='node'), \
                     patch.object(live, '_inventory', return_value={}), \
                     patch.object(live, '_capture_installed_preset') as capture, \
                     patch.object(live.subprocess, 'run', return_value=Mock(returncode=0, stdout='{}')):
                    result = server.timeline_ai('set_subtitle_preset', {key: value})
                    self.assertTrue(result['success'], result)
                    self.assertTrue(result['dry_run'])
                    self.p.GetMediaPool.assert_not_called()
                    capture.assert_not_called()

    def test_dispatch_false_string_is_a_real_mutation(self):
        from src import server
        from src.utils import destructive_hook as hook
        preferences = lambda key: True if key == 'destructive.safe_mode' else False
        with patch.object(hook, '_PREFERENCE_PROVIDER', preferences), \
             patch.object(hook, '_PROVIDER', return_value=None) as context, \
             patch.object(server, '_get_tl', return_value=(self.p, self.t, None)), \
             patch.object(server, 'get_resolve', return_value=self.r), \
             patch.object(server, '_set_live_subtitle_preset', return_value={'success': True}) as helper:
            result = server.timeline_ai('set_subtitle_preset', {'dry_run': 'false'})
        self.assertTrue(result['success'])
        self.assertIs(helper.call_args.args[3]['dry_run'], False)
        context.assert_called_once()

    def test_string_preview_refuses_uncached_capture(self):
        from src import server
        with patch.object(server, '_get_tl', return_value=(self.p, self.t, None)), \
             patch.object(server, 'get_resolve', return_value=self.r), \
             patch.object(live.shutil, 'which', return_value='node'), \
             patch.object(live, 'find_subtitle_preset', return_value={'template_id': 'Uncached'}), \
             patch.object(live, '_capture_installed_preset') as capture:
            result = server.timeline_ai('set_subtitle_preset', {'dry_run': 'true', 'preset': 'Uncached'})
        self.assertFalse(result['success'])
        self.assertIn('mutation-free dry run', result['error'])
        self.t.Export.assert_not_called()
        self.p.GetMediaPool.assert_not_called()
        capture.assert_not_called()


if __name__ == '__main__':
    unittest.main()
