"""Contract tests for the Resolve 21.0 scripting-API additions.

Covers the consolidated-server actions added in v2.29.0:
  - folder / media_pool_item: perform_audio_classification, clear_audio_classification,
    analyze_for_intellisearch, analyze_for_slate, remove_motion_blur (confirm-gated),
    transcribe_audio use_speaker_detection passthrough
  - resolve_control: disable_background_tasks_for_current_session
  - project_settings: generate_speech (confirm-gated)
  - capability detection (_transcription_capabilities) reports the new method flags
  - version guarding: legacy objects (no 21.0 method) return a "requires 21.0" error
"""
import tempfile
import unittest

import src.server as compound
from src.utils import resolve_ai_ledger as _ledger


# ── Stubs ────────────────────────────────────────────────────────────────────


class Clip21:
    """A MediaPoolItem exposing the Resolve 21.0 methods."""

    def __init__(self, name="clip.mov", cid="c1"):
        self._name = name
        self._id = cid
        self.calls = []

    def GetName(self):
        return self._name

    def GetUniqueId(self):
        return self._id

    def TranscribeAudio(self, *args):
        self.calls.append(("TranscribeAudio", args))
        return True

    def ClearTranscription(self):
        return True

    def PerformAudioClassification(self):
        self.calls.append(("PerformAudioClassification", ()))
        return True

    def ClearAudioClassification(self):
        self.calls.append(("ClearAudioClassification", ()))
        return True

    def AnalyzeForIntellisearch(self, identify_faces, is_better_mode):
        self.calls.append(("AnalyzeForIntellisearch", (identify_faces, is_better_mode)))
        return True

    def AnalyzeForSlate(self, marker_color):
        self.calls.append(("AnalyzeForSlate", (marker_color,)))
        return True

    def RemoveMotionBlur(self, deblur_option):
        self.calls.append(("RemoveMotionBlur", (deblur_option,)))
        return Clip21(name="clip_deblurred.mov", cid="c1-deblur")


class LegacyClip:
    """A MediaPoolItem from a pre-21 Resolve build (no 21.0 methods)."""

    def __init__(self, name="legacy.mov", cid="L1"):
        self._name = name
        self._id = cid

    def GetName(self):
        return self._name

    def GetUniqueId(self):
        return self._id

    def TranscribeAudio(self, *args):
        return True

    def ClearTranscription(self):
        return True


class Folder21:
    def __init__(self, name="Master"):
        self._name = name
        self.calls = []

    def GetName(self):
        return self._name

    def TranscribeAudio(self, *args):
        self.calls.append(("TranscribeAudio", args))
        return True

    def ClearTranscription(self):
        return True

    def PerformAudioClassification(self):
        self.calls.append(("PerformAudioClassification", ()))
        return True

    def ClearAudioClassification(self):
        return True

    def AnalyzeForIntellisearch(self, identify_faces, is_better_mode):
        self.calls.append(("AnalyzeForIntellisearch", (identify_faces, is_better_mode)))
        return True

    def AnalyzeForSlate(self, marker_color):
        self.calls.append(("AnalyzeForSlate", (marker_color,)))
        return True

    def RemoveMotionBlur(self, deblur_option):
        self.calls.append(("RemoveMotionBlur", (deblur_option,)))
        orig = Clip21(name="a.mov", cid="a")
        new = Clip21(name="a_deblurred.mov", cid="a-deblur")
        return [[orig, new]]


class MediaPoolStub:
    def __init__(self, folder=None, clip=None):
        self._folder = folder or Folder21()
        self._clip = clip or Clip21()

    def GetRootFolder(self):
        return self._folder

    def GetCurrentFolder(self):
        return self._folder

    def GetSelectedClips(self):
        return [self._clip]


class Project21:
    def __init__(self):
        self.calls = []

    def GetName(self):
        return "Proj"

    def GenerateSpeech(self, settings, timecode):
        self.calls.append((settings, timecode))
        return Clip21(name="speech.wav", cid="vo-1")


class LegacyProject:
    def GetName(self):
        return "Proj"


class Resolve21:
    def __init__(self):
        self.disabled = False

    def DisableBackgroundTasksForCurrentResolveSession(self):
        self.disabled = True


class LegacyResolve:
    pass


# ── Tests ────────────────────────────────────────────────────────────────────


class Resolve21FolderActionsTest(unittest.TestCase):
    def setUp(self):
        compound._CONFIRM_TOKENS.clear()
        self.folder = Folder21()
        self.mp = MediaPoolStub(folder=self.folder)
        self._orig_get_mp = compound._get_mp
        compound._get_mp = lambda: (None, None, self.mp, None)
        # Isolate the AI-ops ledger to a temp project root (also avoids the real
        # _destructive_versioning_provider hitting a live Resolve during tests).
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = compound._ai_ledger_root
        compound._ai_ledger_root = lambda: self._tmp.name

    def tearDown(self):
        compound._get_mp = self._orig_get_mp
        compound._ai_ledger_root = self._orig_root
        self._tmp.cleanup()

    def test_op_is_recorded_in_ledger(self):
        compound.folder("analyze_for_slate", {"marker_color": "Sky"})
        rows = _ledger.get_usage(project_root=self._tmp.name)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["op"], "analyze_for_slate")
        self.assertEqual(rows[0]["success"], 1)

    def test_perform_audio_classification(self):
        out = compound.folder("perform_audio_classification", {})
        self.assertTrue(out["success"])
        self.assertIn(("PerformAudioClassification", ()), self.folder.calls)

    def test_analyze_for_intellisearch_passes_flags(self):
        out = compound.folder("analyze_for_intellisearch", {"identify_faces": True, "is_better_mode": True})
        self.assertTrue(out["success"])
        self.assertIn(("AnalyzeForIntellisearch", (True, True)), self.folder.calls)

    def test_analyze_for_slate_valid_color(self):
        out = compound.folder("analyze_for_slate", {"marker_color": "Lavender"})
        self.assertTrue(out["success"])
        self.assertIn(("AnalyzeForSlate", ("Lavender",)), self.folder.calls)

    def test_analyze_for_slate_invalid_color_rejected(self):
        out = compound.folder("analyze_for_slate", {"marker_color": "Chartreuse"})
        self.assertIn("error", out)
        self.assertEqual(self.folder.calls, [])

    def test_analyze_for_slate_default_color(self):
        out = compound.folder("analyze_for_slate", {})
        self.assertTrue(out["success"])
        self.assertIn(("AnalyzeForSlate", ("Blue",)), self.folder.calls)

    def test_transcribe_audio_speaker_detection_passthrough(self):
        compound.folder("transcribe_audio", {"use_speaker_detection": True})
        self.assertIn(("TranscribeAudio", (True,)), self.folder.calls)

    def test_transcribe_audio_no_arg_when_unset(self):
        compound.folder("transcribe_audio", {})
        self.assertIn(("TranscribeAudio", ()), self.folder.calls)

    def test_remove_motion_blur_requires_confirm_then_runs(self):
        # First call (no token) → confirmation required, nothing rendered.
        pending = compound.folder("remove_motion_blur", {"deblur_option": {"UseExtremeMode": True}})
        self.assertEqual(pending.get("status"), "confirmation_required")
        self.assertEqual(self.folder.calls, [])
        token = pending["confirm_token"]
        # Second call (with token) → runs and reports created pairs.
        out = compound.folder("remove_motion_blur", {"deblur_option": {"UseExtremeMode": True}, "confirm_token": token})
        self.assertTrue(out["success"])
        self.assertEqual(len(out["created"]), 1)
        self.assertEqual(out["created"][0]["new"], "a_deblurred.mov")

    def test_unknown_action_lists_new_actions(self):
        out = compound.folder("bogus", {})
        self.assertIn("analyze_for_slate", str(out))


class Resolve21ClipActionsTest(unittest.TestCase):
    def setUp(self):
        compound._CONFIRM_TOKENS.clear()
        self.clip = Clip21()
        self.mp = MediaPoolStub(clip=self.clip)
        self._orig_get_mp = compound._get_mp
        self._orig_find_clip = compound._find_clip
        compound._get_mp = lambda: (None, None, self.mp, None)
        compound._find_clip = lambda root, cid: self.clip
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = compound._ai_ledger_root
        compound._ai_ledger_root = lambda: self._tmp.name

    def tearDown(self):
        compound._get_mp = self._orig_get_mp
        compound._find_clip = self._orig_find_clip
        compound._ai_ledger_root = self._orig_root
        self._tmp.cleanup()

    def test_remove_motion_blur_records_clip_id_in_ledger(self):
        pending = compound.media_pool_item("remove_motion_blur", {"clip_id": "c1"})
        out = compound.media_pool_item("remove_motion_blur", {"clip_id": "c1", "confirm_token": pending["confirm_token"]})
        self.assertTrue(out["success"])
        rows = _ledger.get_usage(project_root=self._tmp.name, op="remove_motion_blur")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["clip_id"], "c1")
        self.assertEqual(rows[0]["op_class"], "render")

    def test_perform_audio_classification(self):
        out = compound.media_pool_item("perform_audio_classification", {"clip_id": "c1"})
        self.assertTrue(out["success"])
        self.assertIn(("PerformAudioClassification", ()), self.clip.calls)

    def test_analyze_for_slate_invalid_color_rejected(self):
        out = compound.media_pool_item("analyze_for_slate", {"clip_id": "c1", "marker_color": "Neon"})
        self.assertIn("error", out)
        self.assertEqual(self.clip.calls, [])

    def test_remove_motion_blur_confirm_flow(self):
        pending = compound.media_pool_item("remove_motion_blur", {"clip_id": "c1"})
        self.assertEqual(pending.get("status"), "confirmation_required")
        token = pending["confirm_token"]
        out = compound.media_pool_item("remove_motion_blur", {"clip_id": "c1", "confirm_token": token})
        self.assertTrue(out["success"])
        self.assertEqual(out["new_id"], "c1-deblur")

    def test_speaker_detection_passthrough(self):
        compound.media_pool_item("transcribe_audio", {"clip_id": "c1", "use_speaker_detection": False})
        self.assertIn(("TranscribeAudio", (False,)), self.clip.calls)

    def test_legacy_clip_version_guarded(self):
        self.clip = LegacyClip()
        compound._find_clip = lambda root, cid: self.clip
        out = compound.media_pool_item("perform_audio_classification", {"clip_id": "L1"})
        self.assertIn("error", out)
        self.assertIn("21.0", str(out))


class Resolve21ResolveControlTest(unittest.TestCase):
    def setUp(self):
        self._orig = compound.get_resolve

    def tearDown(self):
        compound.get_resolve = self._orig

    def test_disable_background_tasks(self):
        r = Resolve21()
        compound.get_resolve = lambda: r
        out = compound.resolve_control("disable_background_tasks_for_current_session", {})
        self.assertTrue(out["success"])
        self.assertTrue(r.disabled)

    def test_disable_background_tasks_legacy_guarded(self):
        compound.get_resolve = lambda: LegacyResolve()
        out = compound.resolve_control("disable_background_tasks_for_current_session", {})
        self.assertIn("error", out)
        self.assertIn("21.0", str(out))


class Resolve21GenerateSpeechTest(unittest.TestCase):
    def setUp(self):
        compound._CONFIRM_TOKENS.clear()
        self.proj = Project21()
        self._orig_check = compound._check
        compound._check = lambda: (None, self.proj, None)
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = compound._ai_ledger_root
        compound._ai_ledger_root = lambda: self._tmp.name

    def tearDown(self):
        compound._check = self._orig_check
        compound._ai_ledger_root = self._orig_root
        self._tmp.cleanup()

    def test_requires_text_input(self):
        out = compound.project_settings("generate_speech", {"speech_generation_settings": {"VoiceModel": "Female 1"}})
        self.assertIn("error", out)
        self.assertEqual(self.proj.calls, [])

    def test_confirm_flow_and_settings_passthrough(self):
        params = {"speech_generation_settings": {"TextInput": "Hello world", "AddToTimeline": True}, "timecode": "01:00:00:00"}
        pending = compound.project_settings("generate_speech", params)
        self.assertEqual(pending.get("status"), "confirmation_required")
        self.assertTrue(pending["preview"]["add_to_timeline"])
        self.assertEqual(self.proj.calls, [])
        params_with_token = dict(params, confirm_token=pending["confirm_token"])
        out = compound.project_settings("generate_speech", params_with_token)
        self.assertTrue(out["success"])
        self.assertEqual(out["new_id"], "vo-1")
        self.assertEqual(self.proj.calls[0][0]["TextInput"], "Hello world")
        self.assertEqual(self.proj.calls[0][1], "01:00:00:00")

    def test_legacy_project_guarded(self):
        compound._check = lambda: (None, LegacyProject(), None)
        out = compound.project_settings("generate_speech", {"speech_generation_settings": {"TextInput": "x"}})
        self.assertIn("error", out)
        self.assertIn("21.0", str(out))


class Resolve21CapabilityDetectionTest(unittest.TestCase):
    def test_capability_block_reports_new_flags(self):
        clip = Clip21()
        folder = Folder21()
        mp = MediaPoolStub(folder=folder, clip=clip)
        caps = compound._transcription_capabilities(mp, {"selected": True})
        cm = caps["clip_methods"][0]
        for key in ("perform_audio_classification", "clear_audio_classification",
                    "analyze_for_intellisearch", "analyze_for_slate", "remove_motion_blur"):
            self.assertTrue(cm[key], msg=f"clip flag {key} should be True")
            self.assertTrue(caps["folder"][key], msg=f"folder flag {key} should be True")

    def test_capability_block_false_for_legacy(self):
        clip = LegacyClip()
        # Folder21 has the methods; use a legacy-style folder by reusing LegacyClip shape.
        folder = LegacyClip(name="Legacy")
        mp = MediaPoolStub(folder=folder, clip=clip)
        caps = compound._transcription_capabilities(mp, {"selected": True})
        cm = caps["clip_methods"][0]
        self.assertFalse(cm["perform_audio_classification"])
        self.assertTrue(cm["transcribe_audio"])  # legacy still has transcription


class MissingExtrasStringReturnTest(unittest.TestCase):
    """Resolve reports a missing AI Extras pack as an error STRING, not False.

    Verified live on Studio 21.0.2.4 with only AI Motion Deblur installed:
    AnalyzeForIntellisearch returned "Required package 'AI Intellisearch -
    Faster' is not installed." and GenerateSpeech returned "Required Package,
    'AI Speech Generator' is not Installed.". Both are truthy, so a bare
    bool() reported success for work that never ran, and GenerateSpeech's
    string reached .GetName() and raised AttributeError.
    """

    INTELLISEARCH_MSG = "Required package 'AI Intellisearch - Faster' is not installed."
    SPEECH_MSG = "Required Package, 'AI Speech Generator' is not Installed."

    def setUp(self):
        self.clip = Clip21()
        self.mp = MediaPoolStub(folder=Folder21(), clip=self.clip)
        self._orig_get_mp = compound._get_mp
        self._orig_find_clip = compound._find_clip
        compound._get_mp = lambda: (None, None, self.mp, None)
        compound._find_clip = lambda root, cid: self.clip
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = compound._ai_ledger_root
        compound._ai_ledger_root = lambda: self._tmp.name

    def tearDown(self):
        compound._get_mp = self._orig_get_mp
        compound._find_clip = self._orig_find_clip
        compound._ai_ledger_root = self._orig_root
        self._tmp.cleanup()

    def test_ai_result_treats_string_as_failure(self):
        self.assertEqual(compound._ai_result(self.INTELLISEARCH_MSG),
                         (False, self.INTELLISEARCH_MSG))
        self.assertEqual(compound._ai_result(True), (True, None))
        self.assertEqual(compound._ai_result(False), (False, None))
        self.assertEqual(compound._ai_result(None), (False, None))

    def test_ai_result_payload_surfaces_the_reason(self):
        payload = compound._ai_result_payload(self.INTELLISEARCH_MSG)
        self.assertFalse(payload["success"])
        self.assertEqual(payload["error"], self.INTELLISEARCH_MSG)
        self.assertNotIn("error", compound._ai_result_payload(True))

    def test_intellisearch_string_return_is_not_reported_as_success(self):
        self.clip.AnalyzeForIntellisearch = lambda *a: self.INTELLISEARCH_MSG
        out = compound.media_pool_item("analyze_for_intellisearch", {"clip_id": "c1"})
        self.assertFalse(out.get("success"),
                         msg="a missing-Extras string must not read as success")
        self.assertEqual(out.get("error"), self.INTELLISEARCH_MSG)

    def test_generate_speech_string_return_does_not_raise(self):
        """The string must not reach .GetName() — that raised AttributeError."""
        ok, message = compound._ai_result(self.SPEECH_MSG)
        self.assertFalse(ok)
        self.assertEqual(message, self.SPEECH_MSG)


class RemoveMotionBlurStringReturnTest(unittest.TestCase):
    """RemoveMotionBlur is in the same family and fails both ways.

    It needs the AI Motion Deblur Extra like its siblings need theirs, so absent
    the pack its return can be an error string rather than the documented
    MediaPoolItem / list of pairs. That reproduced BOTH bugs this PR fixes, in
    the one action that renders new media:

      - media_pool_item: `if new_clip:` passed, `_clip_file_size` swallowed its
        own AttributeError, and the string reached `.GetName()` and raised —
        `generate_speech`'s crash verbatim.
      - folder: iterating a string yields characters, the pair-unpack raised,
        `except Exception: continue` ate it, and the action returned
        `{"success": True, "created": []}` with a true success in the ledger.

    Both were live-tested with the Extra INSTALLED, so the absent-pack return
    was never observed — which is exactly why they were missed.
    """

    DEBLUR_MSG = "Required Package, 'AI Motion Deblur' is not Installed."

    def setUp(self):
        self.clip = Clip21()
        self.folder = Folder21()
        self.mp = MediaPoolStub(folder=self.folder, clip=self.clip)
        self._orig_get_mp = compound._get_mp
        self._orig_find_clip = compound._find_clip
        compound._get_mp = lambda: (None, None, self.mp, None)
        compound._find_clip = lambda root, cid: self.clip
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_root = compound._ai_ledger_root
        compound._ai_ledger_root = lambda: self._tmp.name
        compound._CONFIRM_TOKENS.clear()

    def tearDown(self):
        compound._get_mp = self._orig_get_mp
        compound._find_clip = self._orig_find_clip
        compound._ai_ledger_root = self._orig_root
        compound._CONFIRM_TOKENS.clear()
        self._tmp.cleanup()

    def _confirmed(self, tool, action, params):
        pending = tool(action, params)
        return tool(action, dict(params, confirm_token=pending["confirm_token"]))

    def test_clip_string_return_does_not_raise_attributeerror(self):
        self.clip.RemoveMotionBlur = lambda *a: self.DEBLUR_MSG
        out = self._confirmed(compound.media_pool_item, "remove_motion_blur", {"clip_id": "c1"})
        self.assertFalse(out.get("success"))
        self.assertEqual(out.get("error"), self.DEBLUR_MSG)

    def test_folder_string_return_is_not_reported_as_success(self):
        self.folder.RemoveMotionBlur = lambda *a: self.DEBLUR_MSG
        out = self._confirmed(compound.folder, "remove_motion_blur",
                              {"deblur_option": {"UseExtremeMode": True}})
        self.assertFalse(out.get("success"),
                         msg="created:[] alongside success:true was the silent lie")
        self.assertEqual(out.get("created"), [])
        self.assertEqual(out.get("error"), self.DEBLUR_MSG)

    def test_a_working_extra_is_unaffected(self):
        # The installed-pack path must behave exactly as before.
        out = self._confirmed(compound.folder, "remove_motion_blur",
                              {"deblur_option": {"UseExtremeMode": True}})
        self.assertTrue(out["success"])
        self.assertEqual(len(out["created"]), 1)
        self.assertNotIn("error", out)

        compound._CONFIRM_TOKENS.clear()
        out = self._confirmed(compound.media_pool_item, "remove_motion_blur", {"clip_id": "c1"})
        self.assertTrue(out["success"])
        self.assertNotIn("error", out)


if __name__ == "__main__":
    unittest.main()
