"""Offline contract tests for the v2.5.0 fuse_plugin and dctl authoring tools.

Covers:
- Template-generator option validation (positive and negative)
- MCP-tool action dispatch (every documented action, every error path)
- Lua compilation of every Fuse template across default and varied options
- DCTL minimal validation behavior
- Filesystem round-trip (install → list → read → remove) on a temp directory
- Subdir/path-traversal guards
- Per-template install-category routing for ACES vs. regular DCTL
- list_templates symmetry between both tools
"""

import os
import subprocess
import sys
import tempfile
import unittest
from typing import Optional
from unittest.mock import patch

# Stub the Resolve module so server.py imports without Resolve installed.
sys.modules.setdefault('DaVinciResolveScript', type(sys)('DaVinciResolveScript'))

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils import fuse_templates, dctl_templates  # noqa: E402
from src.server import fuse_plugin, dctl  # noqa: E402


def _luac_path() -> Optional[str]:
    for cmd in ('luac', 'luac5.4', 'luac5.3', 'luac5.1'):
        try:
            subprocess.run([cmd, '-v'], capture_output=True, check=True, timeout=5)
            return cmd
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
    return None


LUAC = _luac_path()


# ─── Fuse template generators ────────────────────────────────────────────────

class TestFuseTemplateGenerators(unittest.TestCase):
    """Direct tests of each generator function."""

    def test_registry_has_18_kinds(self):
        self.assertEqual(len(fuse_templates.TEMPLATES), 18)

    def test_every_kind_with_default_options_returns_string(self):
        for kind, gen in fuse_templates.TEMPLATES.items():
            with self.subTest(kind=kind):
                src = gen('McpTest', None)
                self.assertIsInstance(src, str)
                self.assertGreater(len(src), 100, f"{kind} produced trivially short source")
                self.assertIn('@mcp-fuse', src)

    def test_color_matrix_rejects_unknown_op(self):
        with self.assertRaises(ValueError):
            fuse_templates.color_matrix('X', {'ops': ['gamma']})

    def test_color_matrix_accepts_all_known_ops(self):
        ops = ['brightness', 'contrast', 'gain', 'saturation', 'invert']
        src = fuse_templates.color_matrix('X', {'ops': ops})
        for op in ops:
            self.assertIn(op.capitalize(), src)

    def test_per_pixel_rejects_invalid_input_count(self):
        with self.assertRaises(ValueError):
            fuse_templates.per_pixel('X', {'inputs': 3})
        with self.assertRaises(ValueError):
            fuse_templates.per_pixel('X', {'inputs': 0})

    def test_per_pixel_accepts_1_or_2_inputs(self):
        for n in (1, 2):
            src = fuse_templates.per_pixel('X', {'inputs': n})
            self.assertIn('MultiProcessPixels', src)

    def test_transform_rejects_unknown_edge_mode(self):
        with self.assertRaises(ValueError):
            fuse_templates.transform('X', {'edge_mode': 'Bouncy'})

    def test_text_overlay_rejects_unknown_justify(self):
        with self.assertRaises(ValueError):
            fuse_templates.text_overlay('X', {'justify': 'middle'})

    def test_modifier_rejects_unknown_kind(self):
        with self.assertRaises(ValueError):
            fuse_templates.modifier('X', {'kind': 'square'})

    def test_view_lut_rejects_unknown_param_type(self):
        with self.assertRaises(ValueError):
            fuse_templates.view_lut('X', {'params': [{'name': 'P', 'type': 'mat4'}]})

    def test_view_lut_supports_all_documented_param_types(self):
        for ptype in ('float', 'vec2', 'vec3_rgb', 'vec4_rgba'):
            with self.subTest(ptype=ptype):
                src = fuse_templates.view_lut('X', {
                    'params': [{'name': 'P', 'type': ptype, 'default': 1.0}]
                })
                self.assertIn('SetupShadeNode', src)

    def test_source_generator_rejects_unknown_kind(self):
        with self.assertRaises(ValueError):
            fuse_templates.source_generator('X', {'kind': 'fractal'})

    def test_channel_op_rejects_unknown_operation(self):
        with self.assertRaises(ValueError):
            fuse_templates.channel_op('X', {'operation': 'NotAnOp'})

    def test_spatial_warp_rejects_unknown_warp(self):
        with self.assertRaises(ValueError):
            fuse_templates.spatial_warp('X', {'warp': 'twist'})

    def test_spatial_warp_rejects_unknown_edge_mode(self):
        with self.assertRaises(ValueError):
            fuse_templates.spatial_warp('X', {'edge_mode': 'mirror'})

    def test_builtin_blur_rejects_unknown_default_type(self):
        with self.assertRaises(ValueError):
            fuse_templates.builtin_blur('X', {'default_type': 'NotAFilter'})

    def test_shape_generator_rejects_unknown_shape(self):
        with self.assertRaises(ValueError):
            fuse_templates.shape_generator('X', {'shape': 'hexagon'})

    def test_point_modifier_rejects_unknown_kind(self):
        with self.assertRaises(ValueError):
            fuse_templates.point_modifier('X', {'kind': 'pendulum'})

    def test_variable_blur_rejects_unknown_radius_source(self):
        with self.assertRaises(ValueError):
            fuse_templates.variable_blur('X', {'radius_source': 'green'})


# ─── DCTL template generators ────────────────────────────────────────────────

class TestDctlTemplateGenerators(unittest.TestCase):

    def test_registry_has_8_kinds(self):
        self.assertEqual(len(dctl_templates.TEMPLATES), 8)

    def test_kind_category_complete(self):
        self.assertEqual(set(dctl_templates.KIND_CATEGORY.keys()),
                         set(dctl_templates.TEMPLATES.keys()))

    def test_aces_kinds_have_correct_category(self):
        self.assertEqual(dctl_templates.KIND_CATEGORY['aces_idt'], 'aces_idt')
        self.assertEqual(dctl_templates.KIND_CATEGORY['aces_odt'], 'aces_odt')

    def test_lut_kinds_have_lut_category(self):
        for kind in ('transform', 'transform_alpha', 'transition',
                     'matrix', 'kernel', 'lut_apply'):
            self.assertEqual(dctl_templates.KIND_CATEGORY[kind], 'lut')

    def test_every_kind_produces_entry_point(self):
        for kind, gen in dctl_templates.TEMPLATES.items():
            with self.subTest(kind=kind):
                src = gen('McpTest', None)
                has_transform = '__DEVICE__' in src and 'transform(' in src
                has_transition = 'transition(' in src and 'TRANSITION_PROGRESS' in src
                self.assertTrue(has_transform or has_transition,
                                f"{kind} missing entry point")

    def test_transform_alpha_emits_alpha_mode_tag(self):
        src = dctl_templates.transform_alpha('X', {'alpha_mode': 'straight'})
        self.assertIn('DEFINE_DCTL_ALPHA_MODE_STRAIGHT', src)
        src = dctl_templates.transform_alpha('X', {'alpha_mode': 'premultiply'})
        self.assertIn('DEFINE_DCTL_ALPHA_MODE_PREMULTIPLY', src)

    def test_transform_alpha_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            dctl_templates.transform_alpha('X', {'alpha_mode': 'unpremultiplied'})

    def test_matrix_rejects_wrong_shape(self):
        with self.assertRaises(ValueError):
            dctl_templates.matrix('X', {'matrix': [[1, 0], [0, 1]]})
        with self.assertRaises(ValueError):
            dctl_templates.matrix('X', {'matrix': 'not-a-list'})

    def test_matrix_emits_f_suffix_on_constants(self):
        src = dctl_templates.matrix('X', {'matrix': [[0.299, 0.587, 0.114],
                                                     [0.299, 0.587, 0.114],
                                                     [0.299, 0.587, 0.114]]})
        self.assertIn('0.299f', src)

    def test_lut_apply_includes_define_lut(self):
        src = dctl_templates.lut_apply('X', {'lut_path': 'foo.cube'})
        self.assertIn('DEFINE_LUT', src)
        self.assertIn('foo.cube', src)

    def test_aces_idt_parametric_emits_aces_param(self):
        src = dctl_templates.aces_idt('X', {'parametric': True})
        self.assertIn('DEFINE_ACES_PARAM', src)
        self.assertIn('IS_PARAMETRIC_ACES_TRANSFORM: 1', src)

    def test_render_ui_params_rejects_invalid_type(self):
        with self.assertRaises(ValueError):
            dctl_templates._render_ui_params([{'name': 'X', 'type': 'banana'}])


# ─── Lua compilation of every Fuse template ──────────────────────────────────

@unittest.skipIf(LUAC is None, "luac not installed")
class TestFuseLuaCompiles(unittest.TestCase):
    """Run luac -p on every template in default and varied configurations."""

    def _compile(self, source: str) -> tuple:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua',
                                          delete=False) as f:
            f.write(source)
            tmp = f.name
        try:
            r = subprocess.run([LUAC, '-p', tmp], capture_output=True,
                               text=True, timeout=10)
            return r.returncode, r.stderr
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def test_every_template_default_compiles(self):
        for kind, gen in fuse_templates.TEMPLATES.items():
            with self.subTest(kind=kind):
                src = gen('McpTest', None)
                rc, err = self._compile(src)
                self.assertEqual(rc, 0,
                                 f"{kind} default failed luac:\n{err}")

    def test_color_matrix_all_ops_compile(self):
        all_ops = ['brightness', 'contrast', 'gain', 'saturation', 'invert']
        for op in all_ops:
            with self.subTest(op=op):
                src = fuse_templates.color_matrix('X', {'ops': [op]})
                rc, err = self._compile(src)
                self.assertEqual(rc, 0, err)

    def test_per_pixel_two_inputs_compiles(self):
        src = fuse_templates.per_pixel('X', {
            'inputs': 2,
            'expression': '    p1.R = p2.R; return p1',
        })
        rc, err = self._compile(src)
        self.assertEqual(rc, 0, err)

    def test_source_generator_all_kinds_compile(self):
        for kind in ('noise', 'gradient', 'checkerboard', 'solid'):
            with self.subTest(kind=kind):
                src = fuse_templates.source_generator('X', {'kind': kind})
                rc, err = self._compile(src)
                self.assertEqual(rc, 0, err)

    def test_spatial_warp_full_matrix_compiles(self):
        for warp in ('sine', 'scatter', 'pinch'):
            for edge in ('wrap', 'clamp', 'black'):
                with self.subTest(warp=warp, edge=edge):
                    src = fuse_templates.spatial_warp('X', {
                        'warp': warp, 'edge_mode': edge,
                    })
                    rc, err = self._compile(src)
                    self.assertEqual(rc, 0, err)

    def test_view_lut_each_param_type_compiles(self):
        for ptype in ('float', 'vec2', 'vec3_rgb', 'vec4_rgba'):
            with self.subTest(ptype=ptype):
                src = fuse_templates.view_lut('X', {
                    'params': [{'name': 'P', 'type': ptype, 'default': 1.0}],
                })
                rc, err = self._compile(src)
                self.assertEqual(rc, 0, err)

    def test_point_modifier_each_kind_compiles(self):
        for kind in ('orbit', 'figure_eight', 'spring'):
            with self.subTest(kind=kind):
                src = fuse_templates.point_modifier('X', {'kind': kind})
                rc, err = self._compile(src)
                self.assertEqual(rc, 0, err)

    def test_shape_generator_each_kind_compiles(self):
        for kind in ('circle', 'rect', 'star'):
            with self.subTest(kind=kind):
                src = fuse_templates.shape_generator('X', {'shape': kind})
                rc, err = self._compile(src)
                self.assertEqual(rc, 0, err)

    def test_variable_blur_each_radius_source_compiles(self):
        for src_kind in ('slider', 'red', 'alpha'):
            with self.subTest(radius_source=src_kind):
                src = fuse_templates.variable_blur('X', {
                    'radius_source': src_kind,
                })
                rc, err = self._compile(src)
                self.assertEqual(rc, 0, err)


# ─── MCP tool surface — fuse_plugin ──────────────────────────────────────────

class TestFusePluginAction(unittest.TestCase):

    def test_unknown_action_lists_valid(self):
        r = fuse_plugin('not-a-real-action')
        self.assertIn('error', r)
        self.assertIn('list_templates', (r["error"].get("message","") if isinstance(r["error"], dict) else r["error"]))

    def test_path_returns_string(self):
        r = fuse_plugin('path')
        self.assertIn('fuses_dir', r)
        self.assertTrue(r['fuses_dir'])

    def test_list_templates_returns_18(self):
        r = fuse_plugin('list_templates')
        self.assertEqual(len(r['kinds']), 18)
        self.assertIn('color_matrix', r['kinds'])
        self.assertIn('controls_demo', r['kinds'])

    def test_template_unknown_kind_errors(self):
        r = fuse_plugin('template', {'kind': 'nope', 'name': 'X'})
        self.assertIn('error', r)

    def test_template_returns_source_for_every_kind(self):
        for kind in fuse_templates.TEMPLATES:
            with self.subTest(kind=kind):
                r = fuse_plugin('template', {'kind': kind, 'name': 'McpTest'})
                self.assertIn('source', r)
                self.assertGreater(len(r['source']), 100)

    def test_install_rejects_invalid_name(self):
        # leading digit
        r = fuse_plugin('install', {'name': '1bad', 'source': '-- x'})
        self.assertIn('error', r)
        # path traversal
        r = fuse_plugin('install', {'name': '../bad', 'source': '-- x'})
        self.assertIn('error', r)
        # empty
        r = fuse_plugin('install', {'name': '', 'source': '-- x'})
        self.assertIn('error', r)

    def test_install_rejects_empty_source(self):
        r = fuse_plugin('install', {'name': 'GoodName', 'source': ''})
        self.assertIn('error', r)
        r = fuse_plugin('install', {'name': 'GoodName', 'source': '   '})
        self.assertIn('error', r)
        r = fuse_plugin('install', {'name': 'GoodName'})
        self.assertIn('error', r)

    def test_remove_rejects_invalid_name(self):
        r = fuse_plugin('remove', {'name': '../bad'})
        self.assertIn('error', r)

    def test_validate_lua_good(self):
        r = fuse_plugin('validate', {'source': 'function f() return 1 end'})
        # If luac unavailable, the validator returns valid=True with checker=unavailable
        self.assertIn('valid', r)
        self.assertIn('checker', r)

    def test_validate_lua_bad(self):
        if LUAC is None:
            self.skipTest("luac not installed")
        r = fuse_plugin('validate', {'source': 'function( syntax error ='})
        self.assertFalse(r['valid'])
        self.assertIsNotNone(r['errors'])

    def test_validate_glsl_minimal_missing_shadepixel(self):
        r = fuse_plugin('validate', {'source': 'void other() {}', 'type': 'glsl'})
        self.assertFalse(r['valid'])

    def test_validate_glsl_minimal_unbalanced_braces(self):
        r = fuse_plugin('validate', {
            'source': 'void ShadePixel(inout FuPixel f) { {',
            'type': 'glsl',
        })
        self.assertFalse(r['valid'])

    def test_validate_glsl_minimal_good(self):
        r = fuse_plugin('validate', {
            'source': 'void ShadePixel(inout FuPixel f) { f.Color = f.Color; }',
            'type': 'glsl',
        })
        self.assertTrue(r['valid'])


# ─── MCP tool surface — dctl ─────────────────────────────────────────────────

class TestDctlAction(unittest.TestCase):

    def test_unknown_action_lists_valid(self):
        r = dctl('not-a-real-action')
        self.assertIn('error', r)
        self.assertIn('list_templates', (r["error"].get("message","") if isinstance(r["error"], dict) else r["error"]))

    def test_path_each_category(self):
        for cat in ('lut', 'aces_idt', 'aces_odt'):
            with self.subTest(category=cat):
                r = dctl('path', {'category': cat})
                self.assertEqual(r['category'], cat)
                self.assertTrue(r['dctl_dir'])

    def test_path_invalid_category(self):
        r = dctl('path', {'category': 'nope'})
        self.assertIn('error', r)

    def test_list_templates_returns_8(self):
        r = dctl('list_templates')
        self.assertEqual(len(r['kinds']), 8)
        self.assertIn('aces_idt', r['kinds'])
        self.assertIn('lut_apply', r['kinds'])

    def test_list_templates_includes_kind_categories(self):
        r = dctl('list_templates')
        self.assertEqual(r['kind_categories']['aces_idt'], 'aces_idt')
        self.assertEqual(r['kind_categories']['transform'], 'lut')

    def test_template_returns_suggested_category(self):
        r = dctl('template', {'kind': 'aces_idt', 'name': 'X'})
        self.assertEqual(r['suggested_category'], 'aces_idt')
        r = dctl('template', {'kind': 'transform', 'name': 'X'})
        self.assertEqual(r['suggested_category'], 'lut')

    def test_template_each_kind(self):
        for kind in dctl_templates.TEMPLATES:
            with self.subTest(kind=kind):
                r = dctl('template', {'kind': kind, 'name': 'McpTest'})
                self.assertIn('source', r)
                self.assertGreater(len(r['source']), 50)

    def test_install_rejects_invalid_name(self):
        r = dctl('install', {'name': '../bad', 'source': '__DEVICE__ x'})
        self.assertIn('error', r)

    def test_install_rejects_invalid_ext(self):
        r = dctl('install', {'name': 'X', 'source': '__DEVICE__ x', 'ext': '.txt'})
        self.assertIn('error', r)

    def test_subdir_traversal_rejected(self):
        r = dctl('path', {'subdir': '../../etc'})
        self.assertIn('error', r)

    def test_subdir_hidden_rejected(self):
        r = dctl('path', {'subdir': '.hidden'})
        self.assertIn('error', r)

    def test_subdir_backslash_normalized(self):
        # On POSIX, backslashes in a subdir path should be treated as separators
        # so attackers can't bypass traversal checks via Windows-style paths.
        r = dctl('path', {'subdir': 'a\\..\\b'})
        self.assertIn('error', r)

    def test_validate_good_dctl(self):
        src = dctl('template', {'kind': 'transform', 'name': 'X'})['source']
        r = dctl('validate', {'source': src})
        self.assertTrue(r['valid'])

    def test_validate_missing_entry_point(self):
        r = dctl('validate', {'source': '// nothing here'})
        self.assertFalse(r['valid'])

    def test_validate_unbalanced_braces(self):
        r = dctl('validate', {
            'source': '__DEVICE__ float3 transform(int x) { { return; }',
        })
        self.assertFalse(r['valid'])

    def test_validate_warns_about_missing_f_suffix(self):
        bad = '''__DEVICE__ float3 transform(int p_Width, int p_Height,
                                              int p_X, int p_Y,
                                              float p_R, float p_G, float p_B)
{
    float c = 1.5;
    return make_float3(p_R * c, p_G * c, p_B * c);
}'''
        r = dctl('validate', {'source': bad})
        self.assertTrue(r['valid'])
        self.assertTrue(any('1.5' in w for w in r['warnings']))


# ─── Filesystem round-trip on a temp directory ───────────────────────────────

class TestRoundtripFilesystem(unittest.TestCase):
    """Install/list/read/remove cycle against a fully-temp install root.

    Patches `get_resolve_plugin_paths` to point at a tempdir so the test
    leaves no traces in the user's real Resolve directories.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="mcp-fuse-dctl-test-")
        cls.fake_paths = {
            'fuses_dir': os.path.join(cls.tmpdir, 'Fuses'),
            'dctl_dir': os.path.join(cls.tmpdir, 'LUT'),
            'aces_idt_dir': os.path.join(cls.tmpdir, 'ACES', 'IDT'),
            'aces_odt_dir': os.path.join(cls.tmpdir, 'ACES', 'ODT'),
        }
        cls._patcher = patch('src.server.get_resolve_plugin_paths',
                              return_value=cls.fake_paths)
        cls._patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls._patcher.stop()
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_fuse_roundtrip(self):
        gen = fuse_plugin('template', {'kind': 'color_matrix', 'name': 'RtFuse'})
        r = fuse_plugin('install', {'name': 'RtFuse', 'source': gen['source'],
                                     'overwrite': True})
        self.assertTrue(r.get('success'))
        self.assertTrue(os.path.isfile(r['path']))

        lst = fuse_plugin('list')
        names = [f['name'] for f in lst['fuses']]
        self.assertIn('RtFuse', names)
        for f in lst['fuses']:
            if f['name'] == 'RtFuse':
                self.assertTrue(f['mcp_managed'])

        rd = fuse_plugin('read', {'name': 'RtFuse'})
        self.assertEqual(rd['source'], gen['source'])

        # overwrite=false without flag must error
        r2 = fuse_plugin('install', {'name': 'RtFuse', 'source': gen['source']})
        self.assertIn('error', r2)

        rm = fuse_plugin('remove', {'name': 'RtFuse'})
        self.assertTrue(rm.get('success'))
        self.assertFalse(os.path.isfile(r['path']))

    def test_dctl_roundtrip_lut(self):
        gen = dctl('template', {'kind': 'transform', 'name': 'RtDctl'})
        r = dctl('install', {'name': 'RtDctl', 'source': gen['source'],
                              'subdir': 'MCP', 'overwrite': True})
        self.assertTrue(r.get('success'))
        self.assertEqual(r['category'], 'lut')

        lst = dctl('list', {'subdir': 'MCP'})
        names = [f['name'] for f in lst['files']]
        self.assertIn('RtDctl', names)

        rd = dctl('read', {'name': 'RtDctl', 'subdir': 'MCP'})
        self.assertEqual(rd['source'], gen['source'])
        self.assertFalse(rd['encrypted'])

        rm = dctl('remove', {'name': 'RtDctl', 'subdir': 'MCP'})
        self.assertTrue(rm.get('success'))

    def test_dctl_roundtrip_aces_idt(self):
        gen = dctl('template', {'kind': 'aces_idt', 'name': 'RtAcesIdt'})
        self.assertEqual(gen['suggested_category'], 'aces_idt')
        r = dctl('install', {'name': 'RtAcesIdt', 'source': gen['source'],
                              'category': 'aces_idt', 'overwrite': True})
        self.assertTrue(r.get('success'))
        self.assertEqual(r['category'], 'aces_idt')
        self.assertIn('Restart Resolve', r['note'])

        lst = dctl('list', {'category': 'aces_idt'})
        self.assertTrue(any(f['name'] == 'RtAcesIdt' for f in lst['files']))

        rm = dctl('remove', {'name': 'RtAcesIdt', 'category': 'aces_idt'})
        self.assertTrue(rm.get('success'))

    def test_dctl_roundtrip_aces_odt(self):
        gen = dctl('template', {'kind': 'aces_odt', 'name': 'RtAcesOdt'})
        self.assertEqual(gen['suggested_category'], 'aces_odt')
        r = dctl('install', {'name': 'RtAcesOdt', 'source': gen['source'],
                              'category': 'aces_odt', 'overwrite': True})
        self.assertTrue(r.get('success'))
        rm = dctl('remove', {'name': 'RtAcesOdt', 'category': 'aces_odt'})
        self.assertTrue(rm.get('success'))

    def test_list_filters_to_mcp_managed_by_default(self):
        # Drop a non-MCP file in the Fuses dir; default list should hide it.
        os.makedirs(self.fake_paths['fuses_dir'], exist_ok=True)
        non_mcp_path = os.path.join(self.fake_paths['fuses_dir'], 'Foreign.fuse')
        with open(non_mcp_path, 'w') as f:
            f.write("-- not authored by MCP\nFuRegisterClass()\n")

        try:
            default_lst = fuse_plugin('list')
            names = [f['name'] for f in default_lst['fuses']]
            self.assertNotIn('Foreign', names)

            all_lst = fuse_plugin('list', {'all': True})
            names_all = [f['name'] for f in all_lst['fuses']]
            self.assertIn('Foreign', names_all)
        finally:
            os.unlink(non_mcp_path)


if __name__ == '__main__':
    unittest.main()
