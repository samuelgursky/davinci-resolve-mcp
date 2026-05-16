import math
import os
import shutil
import struct
import tempfile
import unittest
import wave

from src.utils.sync_detection import (
    analyze_samples_for_sync_events,
    detect_sync_event_capabilities,
    detect_sync_events_for_records,
)
from src.server import _apply_sync_event_markers


def _synthetic_sync_samples(sample_rate=16000, duration_seconds=6.0):
    samples = [0.0] * int(sample_rate * duration_seconds)

    # One-frame 1 kHz 2-pop at 24 fps.
    pop_start = int(2.0 * sample_rate)
    pop_length = int((1.0 / 24.0) * sample_rate)
    for index in range(pop_length):
        samples[pop_start + index] = 0.75 * math.sin(2.0 * math.pi * 1000.0 * (index / sample_rate))

    # Sharp slate-style impulse later in the file.
    clap_start = int(4.0 * sample_rate)
    samples[clap_start] = 0.95
    samples[clap_start + 1] = -0.85
    samples[clap_start + 3] = 0.55
    return samples


def _write_wav(path, samples, sample_rate=16000):
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for sample in samples:
            clipped = max(-1.0, min(1.0, sample))
            frames.extend(struct.pack("<h", int(clipped * 32767)))
        handle.writeframes(bytes(frames))


class MarkerClipStub:
    def __init__(self, clip_id, name):
        self.clip_id = clip_id
        self.name = name
        self.markers = {}

    def GetUniqueId(self):
        return self.clip_id

    def GetName(self):
        return self.name

    def AddMarker(self, frame, color, name, note, duration, custom_data=""):
        self.markers[frame] = {
            "color": color,
            "name": name,
            "note": note,
            "duration": duration,
            "customData": custom_data,
        }
        return True

    def GetMarkerByCustomData(self, custom_data):
        for marker in self.markers.values():
            if marker.get("customData") == custom_data:
                return marker
        return {}

    def DeleteMarkerByCustomData(self, custom_data):
        for frame, marker in list(self.markers.items()):
            if marker.get("customData") == custom_data:
                del self.markers[frame]
                return True
        return False


class FolderStub:
    def __init__(self, clips=None, subfolders=None):
        self.clips = clips or []
        self.subfolders = subfolders or []

    def GetClipList(self):
        return self.clips

    def GetSubFolderList(self):
        return self.subfolders


class MediaPoolStub:
    def __init__(self, root):
        self.root = root

    def GetRootFolder(self):
        return self.root


class ProjectStub:
    def __init__(self, media_pool):
        self.media_pool = media_pool

    def GetMediaPool(self):
        return self.media_pool


class SyncDetectionTests(unittest.TestCase):
    def test_sample_detector_classifies_two_pop_and_slate_clap(self):
        samples = _synthetic_sync_samples()
        events = analyze_samples_for_sync_events(samples, 16000, fps=24.0)

        two_pops = [event for event in events if event["type"] == "two_pop"]
        claps = [event for event in events if event["type"] == "slate_clap"]

        self.assertTrue(two_pops, events)
        self.assertTrue(claps, events)
        self.assertAlmostEqual(two_pops[0]["time_seconds"], 2.0, delta=0.04)
        self.assertAlmostEqual(claps[0]["time_seconds"], 4.0, delta=0.04)
        self.assertEqual(two_pops[0]["frame"], 48)

    def test_capability_detection_never_installs(self):
        caps = detect_sync_event_capabilities()

        self.assertTrue(caps["success"])
        self.assertTrue(caps["no_auto_install"])
        self.assertIn("two_pop", caps["event_types"])
        self.assertIn("slate_clap", caps["event_types"])

    def test_events_include_marker_suggestions_requiring_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "camera_a.wav")
            _write_wav(path, _synthetic_sync_samples())

            result = detect_sync_events_for_records(
                [{"clip_id": "clip-a", "clip_name": "camera_a.wav", "file_path": path, "fps": "24"}],
                {"fps": 24, "scan_start_seconds": 6, "scan_tail_seconds": 0},
            )

        self.assertTrue(result["success"], result)
        suggestions = result["files"][0]["marker_suggestions"]
        self.assertTrue(suggestions)
        self.assertTrue(suggestions[0]["requires_confirmation"])
        self.assertTrue(suggestions[0]["eligible"])
        self.assertEqual(suggestions[0]["scope"], "media_pool_item")
        self.assertIn("mcp.sync_event", suggestions[0]["marker"]["custom_data"])

    def test_marker_application_requires_confirmation(self):
        detection = {
            "files": [
                {
                    "marker_suggestions": [
                        {
                            "eligible": True,
                            "clip_id": "clip-a",
                            "clip_name": "camera_a.wav",
                            "marker": {
                                "frame": 48,
                                "color": "Cyan",
                                "name": "Sync: 2-pop",
                                "note": "Detected 2-pop",
                                "duration": 1,
                                "custom_data": "mcp.sync_event:clip-a:two_pop:48",
                            },
                        }
                    ]
                }
            ]
        }
        project = ProjectStub(MediaPoolStub(FolderStub([MarkerClipStub("clip-a", "camera_a.wav")])))

        preview = _apply_sync_event_markers(project, detection, {})
        self.assertFalse(preview["success"])
        self.assertTrue(preview["confirmation_required"])

        applied = _apply_sync_event_markers(project, detection, {"confirm": True})
        self.assertTrue(applied["success"], applied)
        self.assertEqual(applied["added"], 1)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg suite not installed")
    def test_file_detector_returns_alignment_offsets(self):
        with tempfile.TemporaryDirectory() as tmp:
            samples_a = _synthetic_sync_samples()
            samples_b = [0.0] * int(0.25 * 16000) + samples_a
            path_a = os.path.join(tmp, "camera_a.wav")
            path_b = os.path.join(tmp, "camera_b.wav")
            _write_wav(path_a, samples_a)
            _write_wav(path_b, samples_b)

            result = detect_sync_events_for_records(
                [
                    {"clip_name": "camera_a.wav", "file_path": path_a, "fps": "24"},
                    {"clip_name": "camera_b.wav", "file_path": path_b, "fps": "24"},
                ],
                {
                    "fps": 24,
                    "scan_start_seconds": 6,
                    "scan_tail_seconds": 0,
                    "prefer_event_type": "two_pop",
                },
            )

        self.assertTrue(result["success"], result)
        suggestions = result["alignment"]["suggestions"]
        self.assertEqual(len(suggestions), 2)
        self.assertEqual(suggestions[0]["suggested_record_offset_frames"], 0)
        self.assertEqual(suggestions[1]["suggested_record_offset_frames"], -6)


if __name__ == "__main__":
    unittest.main()
