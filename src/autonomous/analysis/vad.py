from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import json
import subprocess
import tempfile
import wave

import webrtcvad


SUPPORTED_SAMPLE_RATES = (8000, 16000, 32000, 48000)
FRAME_MS = 30  # WebRTC supports 10, 20, 30 ms


@dataclass
class SpeechSegment:
    start: float
    end: float
    confidence: float  # proxy: fraction of voiced frames in segment window


def _run_ffmpeg_to_pcm_wav(
    input_path: Path,
    output_path: Path,
    sample_rate: int = 16000,
) -> None:
    """
    Convert input audio to mono PCM 16-bit WAV at sample_rate.
    WebRTC VAD requires PCM mono.
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-acodec",
        "pcm_s16le",
        str(output_path),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "FFmpeg audio conversion failed.\n"
            f"Command: {' '.join(cmd)}\n"
            f"stderr:\n{proc.stderr}"
        )


def _read_wav_pcm(path: Path) -> Tuple[bytes, int, int]:
    """
    Returns (pcm_bytes, sample_rate, num_channels).
    """
    with wave.open(str(path), "rb") as wf:
        num_channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        sampwidth = wf.getsampwidth()
        if sampwidth != 2:
            raise ValueError(
                f"Expected 16-bit PCM WAV (2 bytes), got sampwidth={sampwidth}"
            )
        pcm = wf.readframes(wf.getnframes())
        return pcm, sample_rate, num_channels


def _frame_generator(
    pcm: bytes, sample_rate: int, frame_ms: int = FRAME_MS
) -> List[bytes]:
    bytes_per_sample = 2  # 16-bit PCM
    samples_per_frame = int(sample_rate * frame_ms / 1000)
    bytes_per_frame = samples_per_frame * bytes_per_sample
    frames = []
    for i in range(0, len(pcm), bytes_per_frame):
        frame = pcm[i : i + bytes_per_frame]
        if len(frame) < bytes_per_frame:
            break
        frames.append(frame)
    return frames


def _merge_frames_to_segments(
    voiced_flags: List[bool],
    frame_ms: int,
    pad_ms: int = 300,
    min_speech_ms: int = 250,
) -> List[Tuple[int, int, float]]:
    """
    Merge voiced frames into segments using padding.
    Returns list of (start_frame_idx, end_frame_idx_exclusive, confidence_proxy).
    """
    if not voiced_flags:
        return []

    pad_frames = max(1, int(pad_ms / frame_ms))
    min_frames = max(1, int(min_speech_ms / frame_ms))

    segments: List[Tuple[int, int, float]] = []
    i = 0
    n = len(voiced_flags)

    while i < n:
        while i < n and not voiced_flags[i]:
            i += 1
        if i >= n:
            break

        start = i
        end = i
        silence_run = 0
        voiced_count = 0

        while end < n:
            if voiced_flags[end]:
                voiced_count += 1
                silence_run = 0
            else:
                silence_run += 1
            end += 1
            if silence_run >= pad_frames:
                break

        trimmed_end = end - silence_run if silence_run > 0 else end

        if (trimmed_end - start) >= min_frames:
            conf = voiced_count / max(1, (trimmed_end - start))
            conf = max(0.0, min(1.0, conf))
            segments.append((start, trimmed_end, float(conf)))

        i = end + 1

    return segments


def detect_speech_segments(
    audio_path: str,
    aggressiveness: int = 2,
    sample_rate: int = 16000,
    frame_ms: int = FRAME_MS,
    pad_ms: int = 600,
    min_speech_ms: int = 400,
) -> List[Dict]:
    """
    Detect speech segments in an audio file.
    Returns: [{"start": float, "end": float, "confidence": float}, ...]
    """
    if aggressiveness not in (0, 1, 2, 3):
        raise ValueError("aggressiveness must be 0–3")

    if sample_rate not in SUPPORTED_SAMPLE_RATES:
        raise ValueError(f"sample_rate must be one of {SUPPORTED_SAMPLE_RATES}")

    in_path = Path(audio_path)
    if not in_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    vad = webrtcvad.Vad(aggressiveness)

    with tempfile.TemporaryDirectory() as td:
        tmp_wav = Path(td) / "vad_input.wav"
        _run_ffmpeg_to_pcm_wav(in_path, tmp_wav, sample_rate)

        pcm, sr, ch = _read_wav_pcm(tmp_wav)
        if ch != 1 or sr != sample_rate:
            raise ValueError("Audio conversion failed")

        frames = _frame_generator(pcm, sr, frame_ms)
        voiced_flags = [vad.is_speech(frame, sr) for frame in frames]

        merged = _merge_frames_to_segments(
            voiced_flags, frame_ms, pad_ms, min_speech_ms
        )

        results: List[Dict] = []
        for start_f, end_f, conf in merged:
            results.append(
                {
                    "start": round(start_f * frame_ms / 1000, 3),
                    "end": round(end_f * frame_ms / 1000, 3),
                    "confidence": round(conf, 3),
                }
            )

        return results


def vad_summary(
    segments: List[Dict], total_duration_s: Optional[float] = None
) -> Dict:
    speech_s = sum(max(0.0, s["end"] - s["start"]) for s in segments)
    has_speech = speech_s > 0.0

    speech_ratio = None
    if total_duration_s:
        speech_ratio = speech_s / total_duration_s

    return {
        "has_speech": has_speech,
        "speech_seconds": round(speech_s, 3),
        "speech_ratio": None if speech_ratio is None else round(speech_ratio, 4),
        "segments": segments,
    }


def write_vad_json(vad_data: Dict, out_path: str) -> None:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(vad_data, f, indent=2)
