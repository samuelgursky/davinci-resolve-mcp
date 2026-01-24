"""
Unit tests for video analyzer.

Tests schema validation and analyzer logic WITHOUT requiring video files.
"""

import pytest
import tempfile
from pathlib import Path

from autonomous.video_analyzer import (
    SceneInfo,
    ClipAnalysis,
    CandidatesReport,
    VideoAnalyzer,
)


class TestSceneInfo:
    """Tests for SceneInfo dataclass."""

    def test_create_scene(self):
        """Test creating scene info."""
        scene = SceneInfo(
            index=0,
            start_sec=0.0,
            end_sec=3.0,
            duration_sec=3.0,
            motion_score=0.5,
        )
        assert scene.index == 0
        assert scene.duration_sec == 3.0
        assert scene.motion_score == 0.5

    def test_to_dict(self):
        """Test serialization."""
        scene = SceneInfo(
            index=1,
            start_sec=3.0,
            end_sec=6.5,
            duration_sec=3.5,
            motion_score=0.123456,
        )
        d = scene.to_dict()
        assert d["index"] == 1
        assert d["start_sec"] == 3.0
        assert d["end_sec"] == 6.5
        assert d["motion_score"] == 0.123  # Rounded to 3 decimals

    def test_none_motion_score(self):
        """Test scene with no motion score."""
        scene = SceneInfo(
            index=0,
            start_sec=0.0,
            end_sec=3.0,
            duration_sec=3.0,
            motion_score=None,
        )
        d = scene.to_dict()
        assert d["motion_score"] is None


class TestClipAnalysis:
    """Tests for ClipAnalysis dataclass."""

    def test_create_minimal(self):
        """Test creating minimal clip analysis."""
        analysis = ClipAnalysis(clip_name="test.mp4")
        assert analysis.clip_name == "test.mp4"
        assert analysis.has_audio == False
        assert len(analysis.scenes) == 0

    def test_create_full(self):
        """Test creating full clip analysis."""
        analysis = ClipAnalysis(
            clip_name="scene_01.mp4",
            file_path="/path/to/scene_01.mp4",
            duration_sec=12.5,
            fps=24.0,
            width=1920,
            height=1080,
            has_audio=True,
            analysis_method="scenedetect",
            motion_method="opencv",
        )
        analysis.scenes.append(SceneInfo(
            index=0, start_sec=0, end_sec=6, duration_sec=6, motion_score=0.3
        ))
        analysis.scenes.append(SceneInfo(
            index=1, start_sec=6, end_sec=12.5, duration_sec=6.5, motion_score=0.7
        ))

        assert analysis.duration_sec == 12.5
        assert analysis.has_audio == True
        assert len(analysis.scenes) == 2

    def test_to_dict(self):
        """Test serialization."""
        analysis = ClipAnalysis(
            clip_name="test.mp4",
            duration_sec=10.0,
            has_audio=True,
        )
        d = analysis.to_dict()
        assert d["clip_name"] == "test.mp4"
        assert d["duration_sec"] == 10.0
        assert d["has_audio"] == True
        assert "transcript" not in d  # Not included when None

    def test_to_dict_with_transcript(self):
        """Test serialization includes transcript when present."""
        analysis = ClipAnalysis(
            clip_name="test.mp4",
            transcript="Hello world",
        )
        d = analysis.to_dict()
        assert d["transcript"] == "Hello world"

    def test_warnings_included(self):
        """Test warnings are included in dict."""
        analysis = ClipAnalysis(clip_name="missing.mp4")
        analysis.warnings.append("File not found")
        d = analysis.to_dict()
        assert "warnings" in d
        assert "File not found" in d["warnings"]


class TestCandidatesReport:
    """Tests for CandidatesReport."""

    def test_create_empty(self):
        """Test creating empty report."""
        report = CandidatesReport()
        assert len(report.clips) == 0
        assert report.summary == {}

    def test_to_dict(self):
        """Test serialization."""
        report = CandidatesReport()
        report.clips.append(ClipAnalysis(clip_name="test1.mp4", duration_sec=5.0))
        report.clips.append(ClipAnalysis(clip_name="test2.mp4", duration_sec=10.0))
        report.summary = {
            "total_clips": 2,
            "total_duration_sec": 15.0,
        }

        d = report.to_dict()
        assert len(d["clips"]) == 2
        assert d["summary"]["total_clips"] == 2

    def test_save_and_load(self):
        """Test saving report to file."""
        report = CandidatesReport()
        report.clips.append(ClipAnalysis(
            clip_name="test.mp4",
            duration_sec=12.0,
            has_audio=True,
        ))
        report.summary = {"total_clips": 1}

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "candidates.json"
            report.save(path)

            assert path.exists()
            content = path.read_text()
            assert "test.mp4" in content
            assert '"has_audio": true' in content


class TestVideoAnalyzer:
    """Tests for VideoAnalyzer."""

    def test_init_no_transcription(self):
        """Test initializing without transcription."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = VideoAnalyzer(
                enable_transcription=False,
                work_dir=Path(tmpdir),
            )
            assert analyzer.enable_transcription == False

    def test_init_transcription_without_whisper(self):
        """Test error when transcription enabled but whisper not installed."""
        # This will raise ImportError if faster-whisper is not installed
        # We test the error message
        try:
            from faster_whisper import WhisperModel
            whisper_installed = True
        except ImportError:
            whisper_installed = False

        if not whisper_installed:
            with pytest.raises(ImportError) as exc_info:
                VideoAnalyzer(enable_transcription=True)
            assert "faster-whisper" in str(exc_info.value)
            assert "pip install" in str(exc_info.value)

    def test_segment_by_duration(self):
        """Test fallback segmentation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = VideoAnalyzer(work_dir=Path(tmpdir))

            # Test 10 second video with 3 second segments
            segments = analyzer._segment_by_duration(10.0, 3.0)
            assert len(segments) == 4  # 0-3, 3-6, 6-9, 9-10
            assert segments[0] == (0.0, 3.0)
            assert segments[-1] == (9.0, 10.0)

    def test_segment_by_duration_short_video(self):
        """Test segmentation with video shorter than segment length."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = VideoAnalyzer(work_dir=Path(tmpdir))

            segments = analyzer._segment_by_duration(2.0, 3.0)
            assert len(segments) == 1
            assert segments[0] == (0.0, 2.0)

    def test_segment_by_duration_zero(self):
        """Test segmentation with zero duration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = VideoAnalyzer(work_dir=Path(tmpdir))

            segments = analyzer._segment_by_duration(0.0)
            assert segments == [(0.0, 0.0)]

    def test_analyze_nonexistent_file(self):
        """Test analyzing non-existent file returns warnings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = VideoAnalyzer(work_dir=Path(tmpdir))

            result = analyzer.analyze_clip(
                clip_name="missing.mp4",
                file_path="/nonexistent/path/missing.mp4"
            )

            assert result.clip_name == "missing.mp4"
            assert len(result.warnings) > 0
            assert "not found" in result.warnings[0].lower()

    def test_analyze_clips_empty_list(self):
        """Test analyzing empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = VideoAnalyzer(work_dir=Path(tmpdir))

            report = analyzer.analyze_clips([])

            assert len(report.clips) == 0
            assert report.summary["total_clips"] == 0


class TestDependencyChecks:
    """Tests for dependency checking behavior."""

    def test_opencv_check(self):
        """Test OpenCV availability check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = VideoAnalyzer(work_dir=Path(tmpdir))
            # Just verify the check runs without error
            assert isinstance(analyzer._cv2_available, bool)

    def test_scenedetect_check(self):
        """Test scenedetect availability check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = VideoAnalyzer(work_dir=Path(tmpdir))
            assert isinstance(analyzer._scenedetect_available, bool)

    def test_fallback_motion_scores(self):
        """Test motion fallback returns None values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = VideoAnalyzer(work_dir=Path(tmpdir))

            scenes = [(0.0, 3.0), (3.0, 6.0)]
            scores = analyzer._compute_motion_fallback(scenes)

            assert len(scores) == 2
            assert all(s is None for s in scores)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
