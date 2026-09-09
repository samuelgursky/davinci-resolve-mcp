"""Native editing contracts: reject malformed options and preserve Resolve failures."""
import unittest
from unittest.mock import patch
from tests.test_resolve211_read_controls import NativeStub, ReadControlTests
from src.granular import resolve_211 as g


class EditControlTests(unittest.TestCase):
    def invoke(self, action, options, native):
        harness = ReadControlTests()
        return (
            harness.run_compound('timeline_item', action, {'options': options}, native),
            harness.run_granular('set_timeline_item_' + action[4:], {'options': options}, native),
        )

    def test_native_options_forwarded_without_added_defaults(self):
        for action, method, options in (
            ('set_speed', 'SetSpeed', {'Percentage': 0, 'PitchCorrection': False}),
            ('set_speed', 'SetSpeed', {'Percentage': -50.5, 'RippleTimeline': True, 'StretchKeyframesToFit': False}),
            ('set_fades', 'SetFades', {'FadeIn': 0, 'FadeOut': 12}),
            ('set_fades', 'SetFades', {'FadeIn': 24}),
        ):
            with self.subTest(action=action, options=options):
                native = NativeStub(method, True)
                results = self.invoke(action, options, native)
                self.assertTrue(all(r['success'] for r in results))
                self.assertEqual(native.calls, [(method, (options,))] * 2)

    def test_invalid_options_never_write(self):
        for action, method, invalids in (
            ('set_speed', 'SetSpeed', [None, {}, [], {'Percentage': True}, {'Percentage': float('nan')}, {'Percentage': float('inf')}, {'Percentage': 10**400}, {'RippleTimeline': 1}, {'Speed': 50}]),
            ('set_fades', 'SetFades', [None, {}, [], {'FadeIn': -1}, {'FadeOut': 1.5}, {'FadeIn': True}, {'FadeIn': '12'}, {'Fade': 1}]),
        ):
            for options in invalids:
                with self.subTest(action=action, options=options):
                    native = NativeStub(method, True)
                    self.assertTrue(all('error' in r for r in self.invoke(action, options, native)))
                    self.assertEqual(native.calls, [])

    def test_missing_method_and_native_failure_are_not_success(self):
        for action, method, options in [('set_speed', 'SetSpeed', {'Percentage': 50}), ('set_fades', 'SetFades', {'FadeIn': 12})]:
            native = NativeStub(method, False)
            self.assertTrue(all(r['success'] is False for r in self.invoke(action, options, native)))
            native = NativeStub(method, True, available=False)
            self.assertTrue(all(method in str(r['error']) for r in self.invoke(action, options, native)))
            self.assertEqual(native.calls, [])

    def test_invalid_granular_location_never_looks_up_item(self):
        with patch.object(g, '_get_timeline_item') as lookup:
            self.assertIn('error', g.set_timeline_item_speed({'Percentage': 50}, item_index=-1))
            self.assertIn('error', g.set_timeline_item_fades({'FadeIn': 12}, track_type='subtitle'))
            lookup.assert_not_called()
