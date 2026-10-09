"""Source review uses existing correction persistence and analyzed frames."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from src import analysis_dashboard as panel
from src.utils import analysis_store


class SourceReviewTest(unittest.TestCase):
    def test_selection_and_rating_survive_reload_without_changing_notes(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'clips' / 'sample'
            folder.mkdir(parents=True)
            report = {'clip': {'clip_id': 'sample', 'clip_name': 'Sample',
                               'file_path': str(Path(temp) / 'sample.jpg')}}
            (folder / 'analysis.json').write_text(json.dumps(report), encoding='utf-8')
            analysis_store.ingest_report(temp, report, clip_dir=str(folder))
            for field, value in [('user.notes', 'Keep the opening moment'),
                                 ('user.selection', 'Include'), ('user.rating', 5),
                                 ('user.selection', 'Exclude'), ('user.rating', 0),
                                 ('user.selection', 'Unreviewed')]:
                result = panel.apply_clip_correction(temp, 'sample', {
                    'entity_type': 'clip', 'entity_uuid': 'sample',
                    'field_path': field, 'new_value': value, 'author': 'test'})
                self.assertTrue(result['success'], result)
                self.assertTrue(result['db']['success'], result)
                reloaded = panel.get_analyzed_clip(temp, 'sample')
                self.assertEqual(reloaded['corrections']['current'][f'clip:sample:{field}']['value'], value)
                if field == 'user.selection':
                    self.assertEqual(panel.list_analyzed_clips(temp)['clips'][0]['user_selection'], value)
            self.assertEqual(reloaded['corrections']['current']['clip:sample:user.notes']['value'], 'Keep the opening moment')
            for field, invalid in [('user.selection', 'invalid'), ('user.selection', []),
                                   ('user.rating', True), ('user.rating', -1),
                                   ('user.rating', 6), ('user.rating', '5')]:
                result = panel.apply_clip_correction(temp, 'sample', {
                    'entity_type': 'clip', 'entity_uuid': 'sample',
                    'field_path': field, 'new_value': invalid})
                self.assertFalse(result['success'], result)

    def test_serial_review_behaviors(self):
        result = subprocess.run(['node', str(Path(__file__).with_suffix('.cjs'))],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS: persisted readback', result.stdout)
