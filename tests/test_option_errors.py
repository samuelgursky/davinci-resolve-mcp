"""A refused option must say what was wrong, what arrived, and what was accepted.

Issue #232 reported that `timeline.normalize_audio_level` "rejects every documented
option schema". It never did — every `NormalizeAudioOptions` shape was accepted, as
the last test here pins. What failed was the refusal: one sentence covering two
unrelated causes, naming neither the offending key nor the received type, so a
report could not distinguish a client that had JSON-encoded the object from a typo.

These tests are about the message, because the message was the defect.
"""

import unittest

from src.utils.option_errors import reject_option_keys
from src.utils.resolve211_alignment import auto_align
from src.utils.resolve211_normalization import OPTION_KEYS, normalize_audio


class _Item:
    def __init__(self, uid):
        self._uid = uid

    def GetUniqueId(self):
        return self._uid


class _Timeline:
    def __init__(self):
        self.calls = []

    def GetTrackCount(self, _track_type):
        return 1

    def GetItemListInTrack(self, _track_type, _index):
        return [_Item("a1")]

    def NormalizeAudioLevel(self, items, options):
        self.calls.append(options)
        return True

    def AutoAlignClips(self, items, options):
        self.calls.append(options)
        return True


class _Resolve:
    NORMALIZE_AUDIO_SET_LEVEL_RELATIVE = 0
    NORMALIZE_AUDIO_SET_LEVEL_INDEPENDENT = 1
    AUTO_ALIGN_CLIPS_USING_WAVEFORM = 1


class RejectOptionKeysTest(unittest.TestCase):
    def test_a_json_string_is_named_as_such(self):
        """The one way to hit this while passing documented keys.

        Some MCP clients serialise nested objects, so the caller is looking at a
        payload that appears correct. The message has to say so or they are stuck.
        """
        message = reject_option_keys('{"targetLevel": -6}', OPTION_KEYS, "normalization")

        self.assertIn("received a string", message)
        self.assertIn("JSON string", message)

    def test_other_wrong_types_are_named_without_the_json_hint(self):
        self.assertIn("received a list", reject_option_keys([], OPTION_KEYS, "x"))
        self.assertIn("received a number", reject_option_keys(3, OPTION_KEYS, "x"))
        self.assertIn("received null", reject_option_keys(None, OPTION_KEYS, "x"))
        self.assertNotIn("JSON string", reject_option_keys([], OPTION_KEYS, "x"))

    def test_unknown_keys_are_named_and_the_accepted_set_listed(self):
        message = reject_option_keys({"normalisationMode": "x"}, OPTION_KEYS, "normalization")

        self.assertIn("'normalisationMode'", message)
        self.assertIn("normalizationMode", message)
        self.assertIn("option ", message)  # singular

    def test_several_unknown_keys_are_all_named(self):
        message = reject_option_keys({"a": 1, "b": 2}, OPTION_KEYS, "normalization")

        self.assertIn("'a'", message)
        self.assertIn("'b'", message)
        self.assertIn("options ", message)  # plural

    def test_a_usable_mapping_returns_none(self):
        self.assertIsNone(reject_option_keys({"targetLevel": -6}, OPTION_KEYS, "x"))
        self.assertIsNone(reject_option_keys({}, OPTION_KEYS, "x"))

    def test_empty_can_be_refused_where_a_caller_must_choose(self):
        self.assertIn("must not be empty",
                      reject_option_keys({}, OPTION_KEYS, "x", allow_empty=False))


class TheTwoFailuresAreDistinguishable(unittest.TestCase):
    """The defect in #232: one message for two causes with two different fixes."""

    def test_wrong_type_and_unknown_key_do_not_share_a_message(self):
        wrong_type = reject_option_keys("{}", OPTION_KEYS, "normalization")
        unknown_key = reject_option_keys({"nope": 1}, OPTION_KEYS, "normalization")

        self.assertNotEqual(wrong_type, unknown_key)
        self.assertNotIn("Unknown", wrong_type)
        self.assertNotIn("received", unknown_key)


class NormalizationStillAcceptsEveryDocumentedShape(unittest.TestCase):
    """The claim in #232, tested directly: none of these was ever rejected."""

    def setUp(self):
        self.tl = _Timeline()

    def _run(self, options):
        return normalize_audio(_Resolve(), self.tl, ["a1"], options)

    def test_every_documented_option_shape_reaches_the_native_call(self):
        shapes = [
            {"normalizationMode": "Sample Peak Program", "targetLevel": -6.0},
            {"normalizationMode": "True Peak", "targetLevel": -1.0},
            {"normalizationMode": "EBU R128", "targetLoudness": -23.0},
            {"setLevelMode": "NORMALIZE_AUDIO_SET_LEVEL_RELATIVE"},
            {"setLevelMode": "NORMALIZE_AUDIO_SET_LEVEL_INDEPENDENT"},
            {"normalizationMode": "True Peak", "targetLevel": -1,
             "targetLoudness": -23, "setLevelMode": 1},
            {},
        ]
        for options in shapes:
            with self.subTest(options=options):
                self.assertEqual(self._run(options), {"success": True})
        self.assertEqual(len(self.tl.calls), len(shapes))

    def test_a_json_encoded_payload_is_diagnosed_not_blamed_on_the_keys(self):
        message = self._run('{"normalizationMode": "True Peak"}')["error"]

        self.assertIn("JSON string", message)
        self.assertEqual(self.tl.calls, [])


class AlignmentSharesTheSameBuilder(unittest.TestCase):
    """The sibling validator carried the identical conflation."""

    def test_unknown_alignment_option_is_named(self):
        out = auto_align(_Resolve(), _Timeline(), ["a1"], {"SyncUsing": 1, "Nope": 2})

        self.assertIn("'Nope'", out["error"])
        self.assertIn("SyncUsing", out["error"])

    def test_json_encoded_alignment_options_are_diagnosed(self):
        out = auto_align(_Resolve(), _Timeline(), ["a1"], '{"SyncUsing": 1}')

        self.assertIn("JSON string", out["error"])


if __name__ == "__main__":
    unittest.main()
