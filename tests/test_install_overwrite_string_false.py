"""A string "false" must not unlock the overwrite guard on an extension install.

fuse_plugin, dctl, script_plugin and lut all refuse to replace an existing file
unless the caller passes overwrite, and every one of them says so in the same
words: "Pass overwrite=true to replace it." They read the flag with bare
truthiness, so overwrite="false" -- the spelling a client that stringifies its
JSON scalars sends -- is truthy and the guard opens. The file the caller asked
the server to protect is gone.

Same flaw and same fix as ripple="false" on timeline.delete_clips: read the
parameter through src.utils.bool_params.coerce_bool.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# Stub the Resolve module so server.py imports without Resolve installed.
sys.modules.setdefault('DaVinciResolveScript', type(sys)('DaVinciResolveScript'))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.server import dctl, fuse_plugin, lut, script_plugin  # noqa: E402
from src.utils import lut_files  # noqa: E402

FALSE_SPELLINGS = ("false", "False", "FALSE", "no", "off", "0")

IDENTITY_CUBE = """TITLE "test"
LUT_3D_SIZE 2
DOMAIN_MIN 0.0 0.0 0.0
DOMAIN_MAX 1.0 1.0 1.0
0.0 0.0 0.0
1.0 0.0 0.0
0.0 1.0 0.0
1.0 1.0 0.0
0.0 0.0 1.0
1.0 0.0 1.0
0.0 1.0 1.0
1.0 1.0 1.0
"""


class ExtensionOverwriteGuardTests(unittest.TestCase):
    """fuse, dctl and script installs share one guard and one temp plugin root."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = tmp.name
        fake_paths = {
            'fusion_dir': os.path.join(self.root, 'Fusion'),
            'fuses_dir': os.path.join(self.root, 'Fuses'),
            'scripts_root': os.path.join(self.root, 'Scripts'),
            'scripts_categories': ('Edit', 'Color', 'Deliver', 'Comp',
                                   'Tool', 'Utility', 'Views'),
            'dctl_dir': os.path.join(self.root, 'LUT'),
            'aces_idt_dir': os.path.join(self.root, 'ACES', 'IDT'),
            'aces_odt_dir': os.path.join(self.root, 'ACES', 'ODT'),
        }
        patcher = patch('src.server.get_resolve_plugin_paths', return_value=fake_paths)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _read(path):
        with open(path, 'r', encoding='utf-8') as handle:
            return handle.read()

    def test_fuse_install_keeps_the_file_when_overwrite_is_the_string_false(self):
        mine = fuse_plugin('template', {'kind': 'color_matrix', 'name': 'KeepFuse'})['source']
        theirs = fuse_plugin('template', {'kind': 'color_matrix', 'name': 'OtherFuse'})['source']
        first = fuse_plugin('install', {'name': 'KeepFuse', 'source': mine, 'overwrite': True})
        self.assertTrue(first.get('success'), first)
        path = first['path']

        for spelling in FALSE_SPELLINGS:
            with self.subTest(overwrite=spelling):
                result = fuse_plugin('install', {'name': 'KeepFuse', 'source': theirs,
                                                 'overwrite': spelling})
                self.assertIn('error', result)
                self.assertEqual(self._read(path), mine)

    def test_dctl_install_keeps_the_file_when_overwrite_is_the_string_false(self):
        mine = dctl('template', {'kind': 'transform', 'name': 'KeepDctl'})['source']
        theirs = dctl('template', {'kind': 'matrix', 'name': 'OtherDctl'})['source']
        first = dctl('install', {'name': 'KeepDctl', 'source': mine,
                                 'category': 'lut', 'overwrite': True})
        self.assertTrue(first.get('success'), first)
        path = first['path']

        for spelling in FALSE_SPELLINGS:
            with self.subTest(overwrite=spelling):
                result = dctl('install', {'name': 'KeepDctl', 'source': theirs,
                                          'category': 'lut', 'overwrite': spelling})
                self.assertIn('error', result)
                self.assertEqual(self._read(path), mine)

    def test_script_install_keeps_the_file_when_overwrite_is_the_string_false(self):
        mine = script_plugin('template', {'kind': 'media_rules', 'name': 'KeepLua',
                                          'options': {'language': 'lua'}})['source']
        theirs = script_plugin('template', {'kind': 'media_rules', 'name': 'OtherLua',
                                            'options': {'language': 'lua'}})['source']
        first = script_plugin('install', {'name': 'KeepLua', 'source': mine,
                                          'category': 'Edit', 'language': 'lua',
                                          'overwrite': True})
        self.assertTrue(first.get('success'), first)
        path = first['path']

        for spelling in FALSE_SPELLINGS:
            with self.subTest(overwrite=spelling):
                result = script_plugin('install', {'name': 'KeepLua', 'source': theirs,
                                                   'category': 'Edit', 'language': 'lua',
                                                   'overwrite': spelling})
                self.assertIn('error', result)
                self.assertEqual(self._read(path), mine)

    def test_safe_install_extension_keeps_the_file_when_overwrite_is_the_string_false(self):
        mine = fuse_plugin('template', {'kind': 'color_matrix', 'name': '_mcp_KeepSafe'})['source']
        theirs = fuse_plugin('template', {'kind': 'color_matrix', 'name': '_mcp_OtherSafe'})['source']
        first = script_plugin('safe_install_extension', {
            'extension_type': 'fuse', 'name': '_mcp_KeepSafe', 'source': mine, 'overwrite': True})
        self.assertTrue(first.get('success'), first)
        path = first['path']

        result = script_plugin('safe_install_extension', {
            'extension_type': 'fuse', 'name': '_mcp_KeepSafe', 'source': theirs,
            'overwrite': 'false'})
        self.assertIn('error', result)
        self.assertEqual(self._read(path), mine)


class LutOverwriteGuardTests(unittest.TestCase):
    """The lut tool guards the same way, through lut_files.install_lut."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = patch.object(lut_files, 'master_lut_dir', return_value=tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_lut_install_keeps_the_file_when_overwrite_is_the_string_false(self):
        first = lut('install', {'name': 'keep.cube', 'source': IDENTITY_CUBE})
        self.assertTrue(first.get('success'), first)
        path = first['path']
        replacement = IDENTITY_CUBE.replace('TITLE "test"', 'TITLE "theirs"')

        for spelling in FALSE_SPELLINGS:
            with self.subTest(overwrite=spelling):
                result = lut('install', {'name': 'keep.cube', 'source': replacement,
                                         'overwrite': spelling})
                self.assertIn('error', result)
                with open(path, 'r', encoding='utf-8') as handle:
                    self.assertEqual(handle.read(), IDENTITY_CUBE)


if __name__ == '__main__':
    unittest.main()
