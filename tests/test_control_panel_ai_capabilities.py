import unittest

from src.analysis_dashboard import HTML, _resolve_ai_features


class _Resolve:
    def __init__(self, project) -> None:
        self._project = project

    def GetProjectManager(self):
        return _ProjectManager(self._project)


class _ProjectManager:
    def __init__(self, project) -> None:
        self._project = project

    def GetCurrentProject(self):
        return self._project


class _Project:
    def __init__(self, folder) -> None:
        self._folder = folder

    def GetMediaPool(self):
        return _MediaPool(self._folder)


class _MediaPool:
    def __init__(self, folder) -> None:
        self._folder = folder

    def GetRootFolder(self):
        return self._folder


class _Resolve20Folder:
    def TranscribeAudio(self):
        return True

    def ClearTranscription(self):
        return True


class ControlPanelAiCapabilityTests(unittest.TestCase):
    def test_resolve_20_transcription_is_reported_without_resolve_21_methods(self) -> None:
        result = _resolve_ai_features(_Resolve(_Project(_Resolve20Folder())))

        self.assertTrue(result["features"]["transcribe_audio"])
        self.assertTrue(result["features"]["clear_transcription"])
        self.assertFalse(result["features"]["perform_audio_classification"])
        self.assertEqual(result["available_count"], 2)

    def test_panel_disables_actions_missing_from_current_build(self) -> None:
        self.assertIn("AI_OP_REQUIRES_21", HTML)
        self.assertIn("btn.disabled = !available", HTML)
        self.assertIn("Requires Resolve 21+", HTML)


if __name__ == "__main__":
    unittest.main()
