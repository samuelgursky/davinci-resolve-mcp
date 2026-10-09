import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch
from src.utils.title_library import list_title_presets, find_subtitle_preset
from src.utils.subtitle_live import _capture_installed_preset


class TitleLibraryTests(unittest.TestCase):
    def test_catalog_keeps_categories_and_unambiguous_template_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'Templates.drfx'
            with zipfile.ZipFile(path, 'w') as z:
                for name in ['Edit/Titles/Statement.setting', 'Edit/Titles/Subtitles/Animated/Statement.setting',
                             'Edit/Titles/Subtitles/Simple White.setting', 'Edit/Transitions/Dissolve.setting',
                             'Edit/Titles/Sample.png']:
                    z.writestr(name, '{}')
            catalog = list_title_presets(path)
            self.assertEqual(catalog['count'], 3)
            self.assertEqual(catalog['verification'], 'installed_inventory_only')
            preset = find_subtitle_preset('Statement', path)
            self.assertEqual(preset['template_id'], 'Templates/Edit/Titles/Subtitles/Animated/Statement')
            with self.assertRaises(ValueError):
                find_subtitle_preset('Missing', path)

    def test_native_capture_restores_and_cleans_its_own_timeline_on_wrong_template(self):
        project, resolve, original, capture = Mock(), Mock(), Mock(), Mock()
        pool = project.GetMediaPool.return_value
        pool.CreateEmptyTimeline.return_value = capture
        project.GetCurrentTimeline.return_value = original
        capture.InsertFusionTitleIntoTimeline.return_value.GetFusionCompByIndex.return_value.GetData.return_value = 'wrong'
        with patch('src.utils.subtitle_live.set_current_timeline', return_value=(True, {})) as switch:
            with self.assertRaisesRegex(RuntimeError, 'different template'):
                _capture_installed_preset(resolve, project, {'template_id':'expected'}, Path('unused.drt'))
            self.assertEqual(switch.call_args_list[-1].args, (project, original))
        pool.DeleteTimelines.assert_called_once_with([capture])

    def test_capture_does_not_delete_when_context_restoration_fails(self):
        project, resolve, capture = Mock(), Mock(), Mock()
        project.GetMediaPool.return_value.CreateEmptyTimeline.return_value = capture
        capture.InsertFusionTitleIntoTimeline.return_value.GetFusionCompByIndex.return_value.GetData.return_value = 'expected'
        with patch('src.utils.subtitle_live.set_current_timeline', side_effect=[(True, {}),(False, {})]):
            with self.assertRaises(RuntimeError):
                _capture_installed_preset(resolve, project, {'template_id':'expected'}, Path('unused.drt'))
        project.GetMediaPool.return_value.DeleteTimelines.assert_not_called()


if __name__ == '__main__':
    unittest.main()
