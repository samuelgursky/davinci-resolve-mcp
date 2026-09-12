"""Offline contract tests for the v2.5.0 script_plugin authoring tool.

Covers:
- Template-generator option validation (positive and negative)
- MCP-tool action dispatch (every documented action, every error path)
- Lua compilation of media_rules and scaffold templates (luac -p)
- Python compilation of media_rules and scaffold templates (compile())
- Filesystem round-trip (install → list → read → remove) on a temp directory
- Per-category install routing (Edit, Color, Deliver, Comp, Tool, Utility, Views)
- Per-language ext routing (.lua vs .py)
- list_templates symmetry
- DSL coverage spot-checks (engine functions are present in generated source)
"""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.modules.setdefault('DaVinciResolveScript', type(sys)('DaVinciResolveScript'))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils import script_templates  # noqa: E402
from src.server import script_plugin  # noqa: E402


def _luac_path():
    for cmd in ('luac', 'luac5.4', 'luac5.3', 'luac5.1'):
        try:
            subprocess.run([cmd, '-v'], capture_output=True, check=True, timeout=5)
            return cmd
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
    return None


LUAC = _luac_path()


# ─── Template generators ─────────────────────────────────────────────────────

class TestScriptTemplateGenerators(unittest.TestCase):

    def test_registry_has_2_kinds(self):
        self.assertEqual(set(script_templates.TEMPLATES.keys()),
                         {"scaffold", "media_rules"})

    def test_scaffold_lua(self):
        src = script_templates.scaffold("X", {"language": "lua"})
        self.assertIn("@mcp-script", src)
        self.assertIn("Resolve()", src)
        self.assertIn("function main()", src)

    def test_scaffold_python(self):
        src = script_templates.scaffold("X", {"language": "py"})
        self.assertIn("@mcp-script", src)
        self.assertIn("dvr_script.scriptapp", src)
        self.assertIn("def main()", src)

    def test_scaffold_rejects_unknown_language(self):
        with self.assertRaises(ValueError):
            script_templates.scaffold("X", {"language": "ruby"})

    def test_media_rules_lua_includes_engine(self):
        src = script_templates.media_rules("X", {"language": "lua"})
        self.assertIn("VARIABLES = {", src)
        self.assertIn("RULES = {", src)
        self.assertIn("function run_engine", src)
        # Engine elements
        self.assertIn("DRY_RUN", src)
        self.assertIn("EXTERNAL_DATA", src)
        self.assertIn("LOG_LEVEL", src)
        self.assertIn("DATE_PATTERN", src)
        self.assertIn("REEL_PATTERN", src)
        self.assertIn("SCENE_PATTERN", src)

    def test_media_rules_py_includes_engine(self):
        src = script_templates.media_rules("X", {"language": "py"})
        self.assertIn("VARIABLES = {", src)
        self.assertIn("RULES = [", src)
        self.assertIn("def run_engine", src)
        self.assertIn("DRY_RUN", src)
        self.assertIn("EXTERNAL_DATA", src)
        self.assertIn("LOG_LEVEL", src)
        self.assertIn("DATE_PATTERN", src)

    def test_media_rules_rejects_unknown_language(self):
        with self.assertRaises(ValueError):
            script_templates.media_rules("X", {"language": "ruby"})

    def test_media_rules_dry_run_flag(self):
        # Lua
        src = script_templates.media_rules("X", {"language": "lua", "dry_run": True})
        self.assertIn("local DRY_RUN            = true", src)
        # Python
        src = script_templates.media_rules("X", {"language": "py", "dry_run": True})
        self.assertIn("DRY_RUN           = True", src)


# ─── DSL coverage ─────────────────────────────────────────────────────────────

class TestDSLCoverage(unittest.TestCase):
    """Verify the embedded engine handles every documented source/action/target/transform."""

    @classmethod
    def setUpClass(cls):
        cls.lua = script_templates.media_rules("X", {"language": "lua"})
        cls.py = script_templates.media_rules("X", {"language": "py"})

    def _both(self, marker):
        return marker in self.lua and marker in self.py

    def test_sources_covered(self):
        for marker in ("file_path", "filename", "dirname", "parent_dir",
                       "grandparent_dir", "file_extension",
                       "clip_property:", "metadata:", "embedded_metadata:",
                       "camera_metadata:", "previous_capture:", "static_value",
                       "bin_name", "media_pool_path",
                       "clip_duration", "clip_resolution", "frame_rate", "codec",
                       "audio_channels", "audio_format",
                       "start_tc", "end_tc", "creation_time", "modification_time"):
            with self.subTest(source=marker):
                self.assertTrue(self._both(marker), f"{marker} not in both engines")

    def test_actions_covered(self):
        for marker in ("set_metadata", "set_clip_property", "rename_clip",
                       "move_to_bin", "set_clip_color", "flag_clip",
                       "add_keyword", "add_marker", "apply_lut", "set_in_out",
                       "tag_for_review"):
            with self.subTest(action=marker):
                self.assertTrue(self._both(f'"{marker}"'),
                                f"{marker} not in both engines")

    def test_targets_covered(self):
        for marker in ("media_pool_clips", "current_bin_clips", "bin_path:",
                       "selected_clips", "timeline_items",
                       "selected_timeline_items",
                       "timeline_items_in_track:"):
            with self.subTest(target=marker):
                self.assertTrue(self._both(marker), f"{marker} not in both engines")

    def test_transforms_covered(self):
        # The transform names appear in apply_pipe/_apply_pipe
        for marker in ("upper", "lower", "title", "slug", "pad",
                       "lookup", "add", "sub", "mul", "div"):
            with self.subTest(transform=marker):
                self.assertTrue(self._both(f'"{marker}"'),
                                f"transform {marker} not in both engines")

    def test_engine_globals_covered(self):
        for marker in ("DRY_RUN", "LOG_LEVEL", "LIMIT_TO_FIRST_N",
                       "EXTERNAL_DATA", "BACKUP_BEFORE_RUN"):
            with self.subTest(global_=marker):
                self.assertTrue(self._both(marker), f"{marker} not in both engines")

    def test_external_data_strategies(self):
        for strategy in ("exact", "regex", "fuzzy"):
            with self.subTest(strategy=strategy):
                self.assertTrue(self._both(f'"{strategy}"'),
                                f"strategy {strategy} not in both engines")

    def test_csv_and_json_loaders(self):
        # Lua engine has load_csv and load_json
        self.assertIn("load_csv", self.lua)
        self.assertIn("load_json", self.lua)
        # Python engine has _load_csv and _load_json
        self.assertIn("_load_csv", self.py)
        self.assertIn("_load_json", self.py)


# ─── Compile checks ──────────────────────────────────────────────────────────

class TestPythonCompiles(unittest.TestCase):
    """Every Python template must pass compile()."""

    def _compile(self, source):
        try:
            compile(source, "<test>", "exec")
            return True, None
        except SyntaxError as e:
            return False, f"line {e.lineno}: {e.msg}"

    def test_scaffold_compiles(self):
        src = script_templates.scaffold("X", {"language": "py"})
        ok, err = self._compile(src)
        self.assertTrue(ok, err)

    def test_media_rules_compiles(self):
        src = script_templates.media_rules("X", {"language": "py"})
        ok, err = self._compile(src)
        self.assertTrue(ok, err)

    def test_media_rules_with_dry_run_compiles(self):
        src = script_templates.media_rules("X", {"language": "py", "dry_run": True})
        ok, err = self._compile(src)
        self.assertTrue(ok, err)


@unittest.skipIf(LUAC is None, "luac not installed")
class TestLuaCompiles(unittest.TestCase):
    """Every Lua template must pass luac -p."""

    def _compile(self, source):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua',
                                          delete=False, encoding='utf-8') as f:
            f.write(source); tmp = f.name
        try:
            r = subprocess.run([LUAC, '-p', tmp], capture_output=True,
                               text=True, timeout=10)
            return r.returncode == 0, r.stderr
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def test_scaffold_compiles(self):
        src = script_templates.scaffold("X", {"language": "lua"})
        ok, err = self._compile(src)
        self.assertTrue(ok, err)

    def test_media_rules_compiles(self):
        src = script_templates.media_rules("X", {"language": "lua"})
        ok, err = self._compile(src)
        self.assertTrue(ok, err)

    def test_media_rules_with_dry_run_compiles(self):
        src = script_templates.media_rules("X", {"language": "lua", "dry_run": True})
        ok, err = self._compile(src)
        self.assertTrue(ok, err)


# ─── MCP tool surface ─────────────────────────────────────────────────────────

class TestScriptPluginAction(unittest.TestCase):

    def test_unknown_action(self):
        r = script_plugin('not-a-real-action')
        self.assertIn('error', r)
        self.assertIn('list_templates', (r["error"].get("message","") if isinstance(r["error"], dict) else r["error"]))

    def test_categories(self):
        r = script_plugin('categories')
        self.assertEqual(set(r['categories']),
                         {'Edit', 'Color', 'Deliver', 'Comp',
                          'Tool', 'Utility', 'Views'})

    def test_list_templates(self):
        r = script_plugin('list_templates')
        self.assertEqual(set(r['kinds']), {'scaffold', 'media_rules'})

    def test_path_each_category(self):
        for cat in ('Edit', 'Color', 'Deliver', 'Comp', 'Tool', 'Utility', 'Views'):
            with self.subTest(category=cat):
                r = script_plugin('path', {'category': cat})
                self.assertEqual(r['category'], cat)
                self.assertTrue(r['scripts_dir'].endswith(cat))

    def test_path_invalid_category(self):
        r = script_plugin('path', {'category': 'Nope'})
        self.assertIn('error', r)

    def test_path_missing_category(self):
        r = script_plugin('path')
        self.assertIn('error', r)

    def test_template_unknown_kind(self):
        r = script_plugin('template', {'kind': 'nope', 'name': 'X'})
        self.assertIn('error', r)

    def test_template_each_kind_each_language(self):
        for kind in ('scaffold', 'media_rules'):
            for lang in ('lua', 'py'):
                with self.subTest(kind=kind, language=lang):
                    r = script_plugin('template', {
                        'kind': kind, 'name': 'McpTest',
                        'options': {'language': lang},
                    })
                    self.assertIn('source', r)
                    self.assertEqual(r['language'], lang)
                    self.assertGreater(len(r['source']), 100)

    def test_template_invalid_language(self):
        r = script_plugin('template', {'kind': 'scaffold', 'name': 'X',
                                        'options': {'language': 'ruby'}})
        self.assertIn('error', r)

    def test_install_invalid_name(self):
        r = script_plugin('install', {'name': '../bad', 'source': 'x',
                                       'category': 'Edit'})
        self.assertIn('error', r)

    def test_install_empty_source(self):
        r = script_plugin('install', {'name': 'X', 'source': '',
                                       'category': 'Edit'})
        self.assertIn('error', r)

    def test_install_invalid_category(self):
        r = script_plugin('install', {'name': 'X', 'source': 'x',
                                       'category': 'Nope'})
        self.assertIn('error', r)

    def test_install_invalid_language(self):
        r = script_plugin('install', {'name': 'X', 'source': 'x',
                                       'category': 'Edit', 'language': 'ruby'})
        self.assertIn('error', r)

    def test_install_missing_category(self):
        r = script_plugin('install', {'name': 'X', 'source': 'x'})
        self.assertIn('error', r)

    def test_validate_python_good(self):
        r = script_plugin('validate', {'source': 'def f(): return 1',
                                        'language': 'py'})
        self.assertTrue(r['valid'])

    def test_validate_python_alias_good(self):
        r = script_plugin('validate', {'source': 'def f(): return 1',
                                        'language': 'python'})
        self.assertTrue(r['valid'])
        self.assertEqual(r['checker'], 'python-compile')

    def test_template_python_alias_normalizes_to_py(self):
        r = script_plugin('template', {'kind': 'scaffold',
                                       'name': 'AliasPy',
                                       'options': {'language': 'python'}})
        self.assertEqual(r['language'], 'py')
        self.assertIn('@mcp-script', r['source'])

    def test_validate_python_bad(self):
        r = script_plugin('validate', {'source': 'def f(:\n  pass',
                                        'language': 'py'})
        self.assertFalse(r['valid'])

    def test_validate_lua_good(self):
        r = script_plugin('validate', {'source': 'function f() return 1 end',
                                        'language': 'lua'})
        # If luac is available it returns valid=True; otherwise valid=True with
        # checker='unavailable'
        self.assertIn('valid', r)
        self.assertIn('checker', r)

    def test_validate_invalid_language(self):
        r = script_plugin('validate', {'source': 'x', 'language': 'ruby'})
        self.assertIn('error', r)


# ─── Filesystem round-trip ───────────────────────────────────────────────────

class TestRoundtripFilesystem(unittest.TestCase):
    """install → list → read → remove on a hermetic tempdir.

    Patches get_resolve_plugin_paths to point at a tempdir so the test
    leaves no traces in the user's real Resolve directories.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="mcp-script-test-")
        cls.fake_paths = {
            'fuses_dir': os.path.join(cls.tmpdir, 'Fuses'),
            'dctl_dir': os.path.join(cls.tmpdir, 'LUT'),
            'aces_idt_dir': os.path.join(cls.tmpdir, 'ACES', 'IDT'),
            'aces_odt_dir': os.path.join(cls.tmpdir, 'ACES', 'ODT'),
            'scripts_root': os.path.join(cls.tmpdir, 'Scripts'),
            'scripts_categories': ('Edit', 'Color', 'Deliver', 'Comp',
                                   'Tool', 'Utility', 'Views'),
        }
        cls._patcher = patch('src.server.get_resolve_plugin_paths',
                              return_value=cls.fake_paths)
        cls._patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls._patcher.stop()
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_lua_roundtrip_in_edit(self):
        gen = script_plugin('template', {'kind': 'media_rules',
                                          'name': 'RtLua',
                                          'options': {'language': 'lua'}})
        r = script_plugin('install', {
            'name': 'RtLua', 'source': gen['source'],
            'category': 'Edit', 'language': 'lua', 'overwrite': True,
        })
        self.assertTrue(r.get('success'))
        self.assertTrue(os.path.isfile(r['path']))
        self.assertTrue(r['path'].endswith('RtLua.lua'))

        rd = script_plugin('read', {'name': 'RtLua', 'category': 'Edit',
                                     'language': 'lua'})
        self.assertEqual(rd['source'], gen['source'])

        # overwrite=false errors
        r2 = script_plugin('install', {
            'name': 'RtLua', 'source': gen['source'],
            'category': 'Edit', 'language': 'lua',
        })
        self.assertIn('error', r2)

        rm = script_plugin('remove', {'name': 'RtLua', 'category': 'Edit',
                                       'language': 'lua'})
        self.assertTrue(rm.get('success'))

    def test_py_roundtrip_in_color(self):
        gen = script_plugin('template', {'kind': 'scaffold',
                                          'name': 'RtPy',
                                          'options': {'language': 'py'}})
        r = script_plugin('install', {
            'name': 'RtPy', 'source': gen['source'],
            'category': 'Color', 'language': 'py', 'overwrite': True,
        })
        self.assertTrue(r.get('success'))
        self.assertTrue(r['path'].endswith('RtPy.py'))
        rm = script_plugin('remove', {'name': 'RtPy', 'category': 'Color',
                                       'language': 'py'})
        self.assertTrue(rm.get('success'))

    def test_list_filters_to_mcp_managed(self):
        # Drop a non-MCP file; it should not appear in default list
        os.makedirs(self.fake_paths['scripts_root'], exist_ok=True)
        edit_dir = os.path.join(self.fake_paths['scripts_root'], 'Edit')
        os.makedirs(edit_dir, exist_ok=True)
        foreign = os.path.join(edit_dir, 'Foreign.lua')
        with open(foreign, 'w', encoding="utf-8") as f:
            f.write("-- not authored by MCP\nprint('hi')\n")

        try:
            default = script_plugin('list', {'category': 'Edit'})
            names = [s['name'] for s in default['scripts']]
            self.assertNotIn('Foreign', names)

            with_all = script_plugin('list', {'category': 'Edit', 'all': True})
            names_all = [s['name'] for s in with_all['scripts']]
            self.assertIn('Foreign', names_all)
        finally:
            os.unlink(foreign)

    def test_list_language_filter(self):
        # Install one .lua and one .py
        for lang, name in (('lua', 'FilterLua'), ('py', 'FilterPy')):
            gen = script_plugin('template', {
                'kind': 'scaffold', 'name': name,
                'options': {'language': lang},
            })
            script_plugin('install', {
                'name': name, 'source': gen['source'],
                'category': 'Utility', 'language': lang, 'overwrite': True,
            })

        try:
            r_lua = script_plugin('list', {'category': 'Utility', 'language': 'lua'})
            self.assertEqual(len(r_lua['scripts']), 1)
            self.assertEqual(r_lua['scripts'][0]['language'], 'lua')

            r_py = script_plugin('list', {'category': 'Utility', 'language': 'py'})
            self.assertEqual(len(r_py['scripts']), 1)
            self.assertEqual(r_py['scripts'][0]['language'], 'py')

            r_all = script_plugin('list', {'category': 'Utility'})
            self.assertEqual(len(r_all['scripts']), 2)
        finally:
            for lang, name in (('lua', 'FilterLua'), ('py', 'FilterPy')):
                script_plugin('remove', {'name': name, 'category': 'Utility',
                                          'language': lang})

    def test_list_all_categories(self):
        # Install in two categories, list with no category filter
        for cat in ('Edit', 'Color'):
            gen = script_plugin('template', {
                'kind': 'scaffold', 'name': f'Multi{cat}',
                'options': {'language': 'lua'},
            })
            script_plugin('install', {
                'name': f'Multi{cat}', 'source': gen['source'],
                'category': cat, 'language': 'lua', 'overwrite': True,
            })

        try:
            r = script_plugin('list')
            names = sorted(s['name'] for s in r['scripts']
                           if s['name'].startswith('Multi'))
            self.assertEqual(names, ['MultiColor', 'MultiEdit'])
        finally:
            for cat in ('Edit', 'Color'):
                script_plugin('remove', {'name': f'Multi{cat}', 'category': cat,
                                          'language': 'lua'})


if __name__ == '__main__':
    unittest.main()
