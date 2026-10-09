import json
import re
import unittest
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

from src.utils.qa_privacy import WORKSPACE, anonymize_host_paths, qa_artifact_path


class QAPrivacyTests(unittest.TestCase):
    def test_saved_records_mask_plain_and_json_escaped_host_paths(self):
        path = str(WORKSPACE / 'logs' / 'example.json')
        saved = anonymize_host_paths({'path': path, 'nested': json.dumps({'path': path}),
                                     'project': 'Private project', 'timeline': 'Private timeline'})
        self.assertNotIn(str(WORKSPACE), json.dumps(saved))
        self.assertTrue(saved['path'].startswith('[workspace]'))
        self.assertEqual(qa_artifact_path(saved['path']), Path(path))
        self.assertIn('[workspace]', saved['nested'])
        self.assertEqual(saved['project'], '[project]')
        self.assertEqual(saved['timeline'], '[timeline]')

    def test_bundled_presets_have_no_host_paths_or_source_media_references(self):
        for path in (WORKSPACE / 'resolve-advanced' / 'assets').glob('*.xml'):
            with self.subTest(asset=path.name):
                root = ET.fromstring(path.read_text(encoding='utf8'))
                for node in root.iter('MediaFilePath'):
                    self.assertFalse(node.text)
                for node in root.iter('CompositionBA'):
                    outer = zlib.decompress(bytes.fromhex(node.text)[4:])
                    start = outer.index(b'Composition {')
                    marker = outer.index(b'Compressed = true, }', start)
                    end = outer.index(b'\0', marker)
                    inner = zlib.decompress(outer[end + 5:])
                    text = (outer[start:end] + inner).decode('utf8')
                    self.assertIsNone(re.search(r'(?<![A-Za-z])[A-Z]:[/\\]|/Users/|/home/|file:///|ResolveCaches:', text, re.I))


if __name__ == '__main__':
    unittest.main()
