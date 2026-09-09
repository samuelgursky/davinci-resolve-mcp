"""Both public layers must preserve native read results and refuse absent APIs."""
import unittest
from unittest.mock import patch

import src.server as compound
from src.granular import resolve_211 as granular


CASES = [
    ('resolve_control', 'is_studio', 'IsStudio', 'is_studio', 'is_resolve_studio', {}, False),
    ('resolve_control', 'get_keyboard_presets', 'GetKeyboardPresetList', 'presets', 'get_keyboard_presets', {}, []),
    ('resolve_control', 'get_current_keyboard_preset', 'GetCurrentKeyboardPreset', 'name', 'get_current_keyboard_preset', {}, 'Default'),
    ('project_settings', 'get_project_settings_presets', 'GetProjectSettingsPresetList', 'presets', 'get_project_settings_presets', {}, [{'Name': 'HD', 'Width': 1920, 'Height': 1080}]),
    ('render', 'get_audio_formats', 'GetAudioRenderFormats', 'formats', 'get_audio_render_formats', {}, {'Wave': 'wav'}),
    ('render', 'get_audio_codecs', 'GetAudioRenderCodecs', 'codecs', 'get_audio_render_codecs', {'format': 'wav'}, {'Linear PCM': 'lpcm'}),
    ('timeline', 'get_normalize_audio_modes', 'GetNormalizeAudioModes', 'modes', 'get_normalize_audio_modes', {}, ['EBU R128']),
    ('timeline', 'get_output_blanking', 'GetOutputBlanking', 'blanking', 'get_timeline_output_blanking', {}, {'Top': 0, 'Bottom': 1080, 'Left': 0, 'Right': 1920}),
    ('timeline_item', 'get_speed', 'GetSpeed', 'speed', 'get_timeline_item_speed', {}, {'Percentage': 50.0, 'PitchCorrection': True}),
    ('timeline_item', 'get_fades', 'GetFades', 'fades', 'get_timeline_item_fades', {}, {'FadeIn': 12.5, 'FadeOut': 0.0}),
    ('timeline_item', 'get_output_blanking', 'GetOutputBlanking', 'blanking', 'get_timeline_item_output_blanking', {}, {}),
    ('timeline_item', 'get_use_timeline_for_output_blanking', 'GetUseTimelineForOutputBlanking', 'use_timeline', 'get_timeline_item_use_timeline_for_output_blanking', {}, False),
]


class NativeStub:
    def __init__(self, method, value, available=True):
        self.calls = []
        self.GetProjectManager = lambda: self
        self.GetCurrentProject = lambda: self
        self.GetCurrentTimeline = lambda: self
        if available:
            def invoke(*args):
                self.calls.append((method, args))
                return value
            setattr(self, method, invoke)
        else:
            setattr(self, method, None)


class ReadControlTests(unittest.TestCase):
    def run_compound(self, tool, action, params, native):
        with patch.object(compound, 'get_resolve', return_value=native), \
             patch.object(compound, '_check', return_value=(native, native, None)), \
             patch.object(compound, '_get_item', return_value=(native, native, None)):
            return getattr(compound, tool)(action, params)

    def run_granular(self, name, params, native):
        with patch.object(granular, 'get_resolve', return_value=native), \
             patch.object(granular, 'get_current_project', return_value=(native, native)), \
             patch.object(granular, '_get_timeline', return_value=(native, native, None)), \
             patch.object(granular, '_get_timeline_item', return_value=(native, None)):
            return getattr(granular, name)(**params)

    def test_both_layers_preserve_values_and_forward_only_expected_arguments(self):
        for tool, action, method, key, name, params, value in CASES:
            with self.subTest(tool=tool, action=action):
                native = NativeStub(method, value)
                self.assertEqual(self.run_compound(tool, action, params, native)[key], value)
                self.assertEqual(self.run_granular(name, params, native)[key], value)
                arguments = tuple(params.values())
                self.assertEqual(native.calls, [(method, arguments), (method, arguments)])

    def test_missing_methods_refuse_in_both_layers(self):
        for tool, action, method, key, name, params, value in CASES:
            with self.subTest(tool=tool, action=action):
                native = NativeStub(method, value, available=False)
                for result in (self.run_compound(tool, action, params, native), self.run_granular(name, params, native)):
                    self.assertIn(method, str(result.get('error')))
                    self.assertNotIn(key, result)
                self.assertEqual(native.calls, [])

    def test_required_string_arguments_are_validated_before_native_call(self):
        for tool, action, method, key, name, params, value in CASES:
            if not params:
                continue
            parameter = next(iter(params))
            for invalid in ('', ' ', 3, None):
                with self.subTest(action=action, invalid=invalid):
                    native = NativeStub(method, value)
                    invalid_params = {parameter: invalid}
                    self.assertIn('error', self.run_compound(tool, action, invalid_params, native))
                    self.assertIn('error', self.run_granular(name, invalid_params, native))
                    self.assertEqual(native.calls, [])

    def test_disconnected_granular_read_is_an_error(self):
        with patch.object(granular, 'get_resolve', return_value=None):
            self.assertIn('error', granular.get_keyboard_presets())

    def test_granular_item_locator_rejects_negative_indexes(self):
        with patch.object(granular, '_get_timeline_item') as lookup:
            self.assertIn('error', granular.get_timeline_item_speed(item_index=-1))
            self.assertIn('error', granular.get_timeline_item_fades(track_index=0))
            self.assertIn('error', granular.get_timeline_item_fades(track_type='invalid'))
            lookup.assert_not_called()


if __name__ == '__main__':
    unittest.main()
