"""Tests for strata analyzers (prosody / beat grid / motion) + take_diff.

Pure compute functions are tested on synthetic numpy signals; the end-to-end
runners on ffmpeg-generated media in a temp dir. Skips honestly when numpy
or ffmpeg is unavailable rather than faking results.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
import unittest
import wave

from src.utils import analysis_store, strata, strata_queries, timeline_brain_db
from tests.test_analysis_store import make_report

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

if np is not None:
    from src.utils import strata_analyzers as sa

FFMPEG = shutil.which("ffmpeg")

SR = 16000


def synth_speech_like(bursts, duration, f0=140.0, amp=0.4):
    """Sine 'speech' bursts at f0 with silence between: [(start, end), ...]."""
    t = np.arange(int(duration * SR)) / SR
    signal = np.zeros_like(t, dtype=np.float64)
    for start, end in bursts:
        mask = (t >= start) & (t < end)
        signal[mask] = amp * np.sin(2 * math.pi * f0 * t[mask])
    return signal.astype(np.float32)


def write_wav(path, samples, sample_rate=SR):
    pcm = np.clip(samples * 32767.0, -32768, 32767).astype("<i2").tobytes()
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)


def word(text, start, end):
    return {"word": text, "start": start, "end": end, "probability": 0.9}


@unittest.skipIf(np is None, "numpy not available")
class ProsodyComputeTests(unittest.TestCase):
    def test_energy_curve_tracks_bursts(self) -> None:
        samples = synth_speech_like([(0.5, 1.5), (2.5, 3.5)], duration=4.0)
        energy = sa.compute_energy_curve(samples)
        rate = sa.CURVE_RATE

        def at(t):
            return energy[int(t * rate)]

        self.assertGreater(at(1.0), 0.5)
        self.assertGreater(at(3.0), 0.5)
        self.assertLess(at(2.0), 0.1)
        self.assertLess(at(0.2), 0.1)

    def test_pitch_curve_finds_f0_and_nans_silence(self) -> None:
        samples = synth_speech_like([(0.5, 1.5)], duration=2.0, f0=140.0)
        energy = sa.compute_energy_curve(samples)
        pitch = sa.compute_pitch_curve(samples, energy=energy)
        rate = sa.CURVE_RATE
        voiced = [pitch[i] for i in range(int(0.7 * rate), int(1.3 * rate)) if not math.isnan(pitch[i])]
        self.assertGreater(len(voiced), 10)
        mean_f0 = sum(voiced) / len(voiced)
        self.assertAlmostEqual(mean_f0, 140.0, delta=8.0)
        self.assertTrue(math.isnan(pitch[int(0.1 * rate)]))

    def test_detect_pauses_from_word_gaps(self) -> None:
        words = [
            {"word": "so", "start_seconds": 0.5, "end_seconds": 0.8},
            {"word": "then", "start_seconds": 0.9, "end_seconds": 1.2},   # 0.1 gap: no pause
            {"word": "everything", "start_seconds": 2.4, "end_seconds": 3.0},  # 1.2 gap: pause
        ]
        pauses = sa.detect_pauses(words)
        self.assertEqual(len(pauses), 1)
        self.assertAlmostEqual(pauses[0]["time_seconds"], 1.2)
        self.assertAlmostEqual(pauses[0]["duration_seconds"], 1.2)
        self.assertEqual(pauses[0]["payload"]["after_word"], "everything")

    def test_detect_hesitations(self) -> None:
        words = [
            {"word": "Um,", "start_seconds": 0.1, "end_seconds": 0.3},
            {"word": "well", "start_seconds": 0.5, "end_seconds": 0.9},
            {"word": "uh", "start_seconds": 1.4, "end_seconds": 1.6},
        ]
        hits = sa.detect_hesitations(words)
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0]["payload"]["word"], "Um,")

    def test_detect_breaths_finds_bump_in_gap(self) -> None:
        rate = sa.CURVE_RATE
        energy = [0.0] * int(4.0 * rate)
        for i in range(int(0.5 * rate), int(1.5 * rate)):
            energy[i] = 1.0  # speech
        for i in range(int(2.5 * rate), int(3.5 * rate)):
            energy[i] = 1.0  # speech
        for i in range(int(1.9 * rate), int(2.1 * rate)):
            energy[i] = 0.25  # inhale bump in the gap
        pauses = [{"time_seconds": 1.5, "duration_seconds": 1.0}]
        breaths = sa.detect_breaths(energy, pauses)
        self.assertEqual(len(breaths), 1)
        self.assertAlmostEqual(breaths[0]["time_seconds"], 1.9, delta=0.15)
        self.assertEqual(breaths[0]["payload"]["confidence"], "low")

    def test_speech_rate_curve(self) -> None:
        words = [
            {"word": f"w{i}", "start_seconds": 1.0 + i * 0.25, "end_seconds": 1.2 + i * 0.25}
            for i in range(8)
        ]  # 4 words/sec between 1.0 and 3.0
        curve = sa.compute_speech_rate_curve(words, duration_seconds=5.0)
        self.assertEqual(len(curve), 50)
        self.assertAlmostEqual(curve[20], 4.0, delta=1.0)  # t=2.0, mid-speech
        self.assertEqual(curve[45], 0.0)  # t=4.5, silence


@unittest.skipIf(np is None, "numpy not available")
class BeatGridComputeTests(unittest.TestCase):
    def test_click_track_tempo_and_beats(self) -> None:
        # 120 BPM click track: a click every 0.5 s for 8 s.
        duration, interval = 8.0, 0.5
        t = np.arange(int(duration * SR)) / SR
        signal = np.zeros_like(t, dtype=np.float64)
        click = np.exp(-np.arange(int(0.02 * SR)) / (0.002 * SR))
        for k in range(int(duration / interval)):
            start = int(k * interval * SR)
            signal[start:start + len(click)] += click
        grid = sa.compute_beat_grid((signal * 0.8).astype(np.float32))
        self.assertIsNotNone(grid["tempo_bpm"])
        self.assertAlmostEqual(grid["tempo_bpm"], 120.0, delta=3.0)
        self.assertGreaterEqual(len(grid["beats"]), 12)
        # Beats should land near click times (within one hop of 10 ms + window slop).
        offsets = [min(abs(b - k * interval) for k in range(20)) for b in grid["beats"][:10]]
        self.assertLess(sum(offsets) / len(offsets), 0.05)

    def test_silence_yields_no_grid(self) -> None:
        grid = sa.compute_beat_grid(np.zeros(SR * 2, dtype=np.float32))
        self.assertIsNone(grid["tempo_bpm"])
        self.assertEqual(grid["beats"], [])


@unittest.skipIf(np is None, "numpy not available")
@unittest.skipIf(FFMPEG is None, "ffmpeg not available")
class AnalyzerRunnerTests(unittest.TestCase):
    """End-to-end: temp project DB + ffmpeg-decodable media on disk."""

    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="strata-analyzer-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)

    def _ingest_clip_for(self, media_path, words_by_segment=None, duration=4.0):
        report = make_report()
        report["clip"]["file_path"] = media_path
        report["clip"]["clip_name"] = os.path.basename(media_path)
        report["technical"] = {"format": {"duration_seconds": duration}}
        if words_by_segment:
            report["transcription"] = {
                "success": True,
                "segments": [
                    {
                        "start": seg_words[0]["start"],
                        "end": seg_words[-1]["end"],
                        "text": " ".join(w["word"] for w in seg_words),
                        "words": seg_words,
                    }
                    for seg_words in words_by_segment
                ],
            }
        result = analysis_store.ingest_report(
            self.root, report, clip_dir=os.path.basename(media_path).replace(".", "-")
        )
        self.assertTrue(result["success"], result)
        return result["clip_uuid"]

    def test_run_prosody_end_to_end(self) -> None:
        wav_path = os.path.join(self.root, "take.wav")
        write_wav(wav_path, synth_speech_like([(0.5, 1.5), (2.5, 3.5)], duration=4.0))
        clip_uuid = self._ingest_clip_for(
            wav_path,
            words_by_segment=[
                [word("hello", 0.5, 0.9), word("there", 1.0, 1.5)],
                [word("general", 2.5, 3.0), word("kenobi", 3.1, 3.5)],
            ],
        )
        result = sa.run_prosody(self.root, clip_uuid)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["events"]["pause"], 1)  # the 1.5→2.5 gap
        conn = timeline_brain_db.connect(self.root)
        curve = strata.read_curve(conn, clip_uuid, "vocal_energy")
        self.assertIsNotNone(curve)
        self.assertGreater(strata.curve_value_at(curve, 1.0), 0.5)
        pitch = strata.read_curve(conn, clip_uuid, "pitch")
        self.assertIsNotNone(pitch)
        pauses = strata.read_events(conn, clip_uuid, "pause")
        self.assertAlmostEqual(pauses[0]["time_seconds"], 1.5, delta=0.05)

    def test_run_prosody_missing_media_is_honest(self) -> None:
        clip_uuid = self._ingest_clip_for(os.path.join(self.root, "gone.wav"))
        # File never written → resolver refuses before decode.
        result = sa.run_prosody(self.root, clip_uuid)
        self.assertFalse(result["success"])
        self.assertIn("not accessible", result["error"])

    def test_run_beat_grid_end_to_end(self) -> None:
        wav_path = os.path.join(self.root, "clicks.wav")
        t = np.arange(SR * 6) / SR
        signal = np.zeros_like(t)
        click = np.exp(-np.arange(int(0.02 * SR)) / (0.002 * SR))
        for k in range(12):
            start = int(k * 0.5 * SR)
            signal[start:start + len(click)] += click
        write_wav(wav_path, (signal * 0.8).astype(np.float32))
        clip_uuid = self._ingest_clip_for(wav_path, duration=6.0)
        result = sa.run_beat_grid(self.root, clip_uuid)
        self.assertTrue(result["success"], result)
        self.assertAlmostEqual(result["tempo_bpm"], 120.0, delta=3.0)
        conn = timeline_brain_db.connect(self.root)
        beats = strata.read_events(conn, clip_uuid, "beat")
        self.assertGreaterEqual(len(beats), 8)
        self.assertEqual(beats[0]["payload"]["tempo_bpm"], result["tempo_bpm"])

    def test_run_motion_energy_end_to_end(self) -> None:
        mov_path = os.path.join(self.root, "motion.mp4")
        # First second static color, then testsrc2 motion.
        proc = subprocess.run(
            [
                FFMPEG, "-v", "error",
                "-f", "lavfi", "-i", "color=c=gray:s=160x120:r=24:d=1",
                "-f", "lavfi", "-i", "testsrc2=s=160x120:r=24:d=1",
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1[out]",
                "-map", "[out]", "-pix_fmt", "yuv420p", mov_path,
            ],
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        clip_uuid = self._ingest_clip_for(mov_path, duration=2.0)
        result = sa.run_motion_energy(self.root, clip_uuid)
        self.assertTrue(result["success"], result)
        conn = timeline_brain_db.connect(self.root)
        curve = strata.read_curve(conn, clip_uuid, "motion_energy")
        self.assertIsNotNone(curve)
        static = strata.curve_value_at(curve, 0.5)
        moving = strata.curve_value_at(curve, 1.5)
        self.assertIsNotNone(static)
        self.assertIsNotNone(moving)
        self.assertGreater(moving, static + 0.1)

    def test_run_analyzers_dispatch(self) -> None:
        wav_path = os.path.join(self.root, "take2.wav")
        write_wav(wav_path, synth_speech_like([(0.5, 1.5)], duration=2.0))
        clip_uuid = self._ingest_clip_for(wav_path, duration=2.0)
        result = sa.run_analyzers(self.root, clip_uuid, ["prosody", "beat_grid"])
        self.assertIn("prosody", result["results"])
        self.assertIn("beat_grid", result["results"])
        bad = sa.run_analyzers(self.root, clip_uuid, ["nope"])
        self.assertFalse(bad["success"])
        self.assertIn("available", bad)

    def test_run_analyzers_decodes_audio_once(self) -> None:
        from unittest import mock

        wav_path = os.path.join(self.root, "take3.wav")
        write_wav(wav_path, synth_speech_like([(0.5, 1.5)], duration=2.0))
        clip_uuid = self._ingest_clip_for(wav_path, duration=2.0)
        with mock.patch.object(sa, "decode_audio", wraps=sa.decode_audio) as spy:
            result = sa.run_analyzers(self.root, clip_uuid, ["prosody", "beat_grid"])
        self.assertTrue(result["results"]["prosody"]["success"], result)
        self.assertTrue(result["results"]["beat_grid"]["success"], result)
        self.assertEqual(spy.call_count, 1)

    def test_run_analyzers_shared_decode_error_reported_per_analyzer(self) -> None:
        clip_uuid = self._ingest_clip_for(os.path.join(self.root, "gone2.wav"))
        result = sa.run_analyzers(self.root, clip_uuid, ["prosody", "beat_grid"])
        self.assertFalse(result["success"])
        for name in ("prosody", "beat_grid"):
            self.assertFalse(result["results"][name]["success"])
            self.assertIn("not accessible", result["results"][name]["error"])

    def test_capabilities_derived_from_registry(self) -> None:
        caps = sa.capabilities()["analyzers"]
        self.assertEqual(set(caps), set(sa.ANALYZERS))
        for name, spec in sa.ANALYZERS.items():
            if "capability" in spec:
                continue
            self.assertEqual(caps[name]["requires"], list(spec["requires"]))
            self.assertEqual(caps[name]["writes"], spec["writes"])
            self.assertIn("available", caps[name])


@unittest.skipIf(np is None, "numpy not available")
@unittest.skipIf(FFMPEG is None, "ffmpeg not available")
class TakeDiffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="strata-takediff-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.addCleanup(timeline_brain_db.close_all)

    def _make_take(self, name, line_words, bursts, duration):
        wav_path = os.path.join(self.root, name)
        write_wav(wav_path, synth_speech_like(bursts, duration=duration))
        report = make_report()
        report["clip"]["file_path"] = wav_path
        report["clip"]["clip_name"] = name
        report["clip"]["clip_id"] = f"take-{name}"
        report["clip"]["media_id"] = f"media-{name}"
        report["technical"] = {"format": {"duration_seconds": duration}}
        report["transcription"] = {
            "success": True,
            "segments": [
                {
                    "start": line_words[0]["start"],
                    "end": line_words[-1]["end"],
                    "text": " ".join(w["word"] for w in line_words),
                    "words": line_words,
                }
            ],
        }
        result = analysis_store.ingest_report(self.root, report, clip_dir=name.replace(".", "-"))
        self.assertTrue(result["success"], result)
        sa.run_prosody(self.root, result["clip_uuid"])
        return result["clip_uuid"]

    def test_take_diff_reports_deltas_without_judgment(self) -> None:
        # Take A: brisk. Take B: same line, slower with a long mid-line pause.
        line = ["my", "father", "built", "this", "house"]
        words_a = [word(w, 0.5 + i * 0.3, 0.7 + i * 0.3) for i, w in enumerate(line)]
        words_b = (
            [word(w, 0.5 + i * 0.4, 0.8 + i * 0.4) for i, w in enumerate(line[:2])]
            + [word(w, 3.0 + i * 0.4, 3.3 + i * 0.4) for i, w in enumerate(line[2:])]
        )
        uuid_a = self._make_take("take_a.wav", words_a, [(0.5, 2.2)], duration=3.0)
        uuid_b = self._make_take("take_b.wav", words_b, [(0.5, 1.6), (3.0, 4.5)], duration=5.0)

        result = strata_queries.take_diff(self.root, uuid_a, uuid_b)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["alignment"]["aligned_word_count"], 5)
        self.assertGreater(result["alignment"]["ratio"], 0.9)
        self.assertEqual(result["take_a"]["metrics"]["pause_count"], 0)
        self.assertEqual(result["take_b"]["metrics"]["pause_count"], 1)
        self.assertGreater(result["deltas_b_minus_a"]["duration_seconds"], 1.0)
        self.assertIn("editor", result["judgment"])

    def test_take_diff_with_text_window(self) -> None:
        line = ["my", "father", "built", "this", "house"]
        pre = [word(w, 0.2 + i * 0.25, 0.4 + i * 0.25) for i, w in enumerate(["okay", "so", "yeah"])]
        words_a = pre + [word(w, 1.5 + i * 0.3, 1.7 + i * 0.3) for i, w in enumerate(line)]
        words_b = [word(w, 0.5 + i * 0.3, 0.7 + i * 0.3) for i, w in enumerate(line)]
        uuid_a = self._make_take("take_c.wav", words_a, [(0.2, 3.2)], duration=4.0)
        uuid_b = self._make_take("take_d.wav", words_b, [(0.5, 2.2)], duration=3.0)
        result = strata_queries.take_diff(self.root, uuid_a, uuid_b, text="my father built this house")
        self.assertTrue(result["success"], result)
        self.assertGreaterEqual(result["alignment"]["aligned_word_count"], 5)
        self.assertNotIn("okay", result["take_a"]["text"])

    def test_take_diff_without_words_is_honest(self) -> None:
        report = make_report()
        result = analysis_store.ingest_report(self.root, report, clip_dir="wordless-clip")
        out = strata_queries.take_diff(self.root, result["clip_uuid"], result["clip_uuid"])
        self.assertFalse(out["success"])
        self.assertIn("transcript_words", out["error"])


if __name__ == "__main__":
    unittest.main()
