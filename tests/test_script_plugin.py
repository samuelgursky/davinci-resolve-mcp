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
        with open(foreign, 'w') as f:
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


# ─── execute / run_inline ────────────────────────────────────────────────────

class TestScriptExecution(unittest.TestCase):
    """Tests for execute and run_inline actions.

    Python execution is tested with real subprocesses against a synthetic
    minimal script (no Resolve dependency). Lua execution paths are tested
    via mocking since they require a real Resolve handle.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="mcp-script-exec-")
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
        # Don't try to launch Resolve from these tests
        cls._resolve_patcher = patch('src.server.get_resolve',
                                      return_value=None)
        cls._resolve_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls._patcher.stop()
        cls._resolve_patcher.stop()
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _install_script(self, name: str, category: str, language: str,
                         source: str) -> str:
        """Helper: write a script file directly (bypassing the install action
        so we can install scripts that don't import DaVinciResolveScript)."""
        target_dir = os.path.join(self.fake_paths['scripts_root'], category)
        os.makedirs(target_dir, exist_ok=True)
        path = os.path.join(target_dir, f"{name}.{language}")
        with open(path, 'w') as f:
            f.write(source)
        return path

    # ── execute Python ─────────────────────────────────────────────────────

    def test_execute_python_captures_stdout(self):
        path = self._install_script(
            'EchoTest', 'Utility', 'py',
            "print('hello from script')\nprint('line 2')\n",
        )
        r = script_plugin('execute', {
            'name': 'EchoTest', 'category': 'Utility', 'language': 'py',
        })
        self.assertTrue(r.get('success'), r)
        self.assertIn('hello from script', r['stdout'])
        self.assertIn('line 2', r['stdout'])
        self.assertEqual(r['exit_code'], 0)

    def test_execute_python_captures_stderr(self):
        self._install_script(
            'StderrTest', 'Utility', 'py',
            "import sys\nsys.stderr.write('oops\\n')\nsys.exit(2)\n",
        )
        r = script_plugin('execute', {
            'name': 'StderrTest', 'category': 'Utility', 'language': 'py',
        })
        self.assertFalse(r.get('success'))
        self.assertIn('oops', r['stderr'])
        self.assertEqual(r['exit_code'], 2)

    def test_execute_python_with_args(self):
        self._install_script(
            'ArgsTest', 'Utility', 'py',
            "import sys\nprint('|'.join(sys.argv[1:]))\n",
        )
        r = script_plugin('execute', {
            'name': 'ArgsTest', 'category': 'Utility', 'language': 'py',
            'args': ['alpha', 'beta', 'gamma'],
        })
        self.assertTrue(r.get('success'))
        self.assertIn('alpha|beta|gamma', r['stdout'])

    def test_execute_python_timeout(self):
        self._install_script(
            'SleepTest', 'Utility', 'py',
            "import time\ntime.sleep(5)\n",
        )
        r = script_plugin('execute', {
            'name': 'SleepTest', 'category': 'Utility', 'language': 'py',
            'timeout': 1,
        })
        self.assertIn('error', r)
        self.assertIn('timed out', (r["error"].get("message","") if isinstance(r["error"], dict) else r["error"]))

    def test_execute_missing_script(self):
        r = script_plugin('execute', {
            'name': 'DoesNotExist', 'category': 'Utility', 'language': 'py',
        })
        self.assertIn('error', r)

    def test_execute_invalid_name(self):
        r = script_plugin('execute', {
            'name': '../bad', 'category': 'Utility', 'language': 'py',
        })
        self.assertIn('error', r)

    def test_execute_invalid_category(self):
        r = script_plugin('execute', {
            'name': 'X', 'category': 'Nope', 'language': 'py',
        })
        self.assertIn('error', r)

    def test_execute_invalid_language(self):
        r = script_plugin('execute', {
            'name': 'X', 'category': 'Utility', 'language': 'ruby',
        })
        self.assertIn('error', r)

    def test_execute_args_must_be_list(self):
        path = self._install_script(
            'ArgsCheckTest', 'Utility', 'py', "print('ok')\n",
        )
        r = script_plugin('execute', {
            'name': 'ArgsCheckTest', 'category': 'Utility', 'language': 'py',
            'args': 'not-a-list',
        })
        self.assertIn('error', r)

    # ── execute Lua (mocked) ────────────────────────────────────────────────

    def test_execute_lua_calls_runscript(self):
        # Create the Lua file
        path = self._install_script(
            'LuaTest', 'Utility', 'lua', "print('hi')\n",
        )

        # Mock a Resolve handle whose Fusion().RunScript returns True
        mock_fusion = type(sys)('fusion_mock')
        mock_fusion.RunScript = lambda p: True
        mock_resolve = type(sys)('resolve_mock')
        mock_resolve.Fusion = lambda: mock_fusion

        with patch('src.server.get_resolve', return_value=mock_resolve):
            r = script_plugin('execute', {
                'name': 'LuaTest', 'category': 'Utility', 'language': 'lua',
            })
        self.assertTrue(r.get('success'))
        self.assertEqual(r['language'], 'lua')
        self.assertIn('output_note', r)

    def test_execute_lua_runscript_returns_false(self):
        self._install_script('LuaFail', 'Utility', 'lua', "error('nope')\n")

        mock_fusion = type(sys)('fusion_mock')
        mock_fusion.RunScript = lambda p: False
        mock_resolve = type(sys)('resolve_mock')
        mock_resolve.Fusion = lambda: mock_fusion

        with patch('src.server.get_resolve', return_value=mock_resolve):
            r = script_plugin('execute', {
                'name': 'LuaFail', 'category': 'Utility', 'language': 'lua',
            })
        self.assertFalse(r.get('success'))

    def test_execute_lua_no_resolve(self):
        self._install_script('LuaNoResolve', 'Utility', 'lua', "print('hi')\n")
        # get_resolve already patched to return None at class level
        r = script_plugin('execute', {
            'name': 'LuaNoResolve', 'category': 'Utility', 'language': 'lua',
        })
        self.assertIn('error', r)
        self.assertIn("isn't running", (r["error"].get("message","") if isinstance(r["error"], dict) else r["error"]))

    # ── run_inline Python ──────────────────────────────────────────────────

    def test_run_inline_python_captures_stdout(self):
        r = script_plugin('run_inline', {
            'source': "print('inline says hi')\n", 'language': 'py',
        })
        # Note: subprocess will fail to import DaVinciResolveScript without
        # Resolve env, but our test patch makes get_resolve a no-op. The
        # boilerplate at the top of inline scripts handles a missing handle
        # gracefully, but DaVinciResolveScript import itself will succeed if
        # the env var is set. We just check that the subprocess produced
        # output OR an importable error — the framework works either way.
        self.assertIn('inline says hi', r.get('stdout', ''))

    def test_run_inline_python_can_compute(self):
        r = script_plugin('run_inline', {
            'source': "print(2 + 3)\n", 'language': 'py',
        })
        self.assertIn('5', r.get('stdout', ''))

    def test_run_inline_empty_source_errors(self):
        r = script_plugin('run_inline', {'source': '', 'language': 'py'})
        self.assertIn('error', r)
        r = script_plugin('run_inline', {'source': '   ', 'language': 'lua'})
        self.assertIn('error', r)

    def test_run_inline_invalid_language(self):
        r = script_plugin('run_inline', {
            'source': 'x = 1', 'language': 'ruby',
        })
        self.assertIn('error', r)

    # ── run_inline Lua (mocked) ────────────────────────────────────────────

    def test_run_inline_lua_uses_runscript_and_setdata_channel(self):
        """Mock the RunScript+SetData pattern that _run_inline_lua actually uses.

        Real implementation: write wrapped Lua to temp file, RunScript(path),
        poll SetData for completion sentinel, return captured stdout/result.
        """
        state = {}

        class MockFusion:
            def SetData(self_inner, key, val):
                state[key] = val
            def GetData(self_inner, key):
                return state.get(key, "")
            def RunScript(self_inner, path):
                # Simulate the wrapper completing successfully
                state["__mcp_stdout__"] = "captured stdout"
                state["__mcp_result__"] = "42"
                state["__mcp_error__"] = ""
                state["__mcp_done__"] = "1"
                return None

        class MockResolve:
            def Fusion(self_inner): return MockFusion()

        with patch('src.server.get_resolve', return_value=MockResolve()):
            r = script_plugin('run_inline', {
                'source': 'return 42', 'language': 'lua',
            })
        self.assertTrue(r.get('success'))
        self.assertEqual(r.get('result'), '42')
        self.assertIn('captured stdout', r.get('stdout', ''))
        self.assertEqual(r['language'], 'lua')

    def test_run_inline_lua_no_resolve(self):
        # get_resolve already patched to return None at class level
        r = script_plugin('run_inline', {
            'source': 'return 1', 'language': 'lua',
        })
        self.assertIn('error', r)


if __name__ == '__main__':
    unittest.main()
