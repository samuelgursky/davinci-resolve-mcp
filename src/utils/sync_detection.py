"""Source-safe sync event detection for 2-pops and slate claps.

The detector reads source audio through ffprobe/ffmpeg and returns advisory
sync points. It never writes media, creates derivatives, or modifies Resolve.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from array import array
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.utils.multicam import timecode_to_frames


SYNC_EVENT_TYPES = ("two_pop", "slate_clap")
DEFAULT_SAMPLE_RATE = 16000
DEFAULT_HEAD_SCAN_SECONDS = 30.0
DEFAULT_TAIL_SCAN_SECONDS = 30.0
DEFAULT_COMMAND_TIMEOUT_SECONDS = 180


def _err(message: str, **extra: Any) -> Dict[str, Any]:
    payload = {"success": False, "error": message}
    payload.update(extra)
    return payload


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _coerce_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _fraction_to_float(value: Any) -> Optional[float]:
    if value in (None, "", "0/0"):
        return None
    raw = str(value)
    if "/" in raw:
        numerator, denominator = raw.split("/", 1)
        try:
            denominator_f = float(denominator)
            if denominator_f == 0:
                return None
            return float(numerator) / denominator_f
        except ValueError:
            return None
    return _coerce_float(raw)


def _dbfs(value: float) -> float:
    return round(20.0 * math.log10(max(abs(value), 1e-12)), 2)


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    index = max(0.0, min(1.0, percentile)) * (len(ordered) - 1)
    lower = int(math.floor(index))
    upper = int(math.ceil(index))
    if lower == upper:
        return float(ordered[lower])
    weight = index - lower
    return float((ordered[lower] * (1.0 - weight)) + (ordered[upper] * weight))


def _normalize_event_types(value: Any) -> Tuple[List[str], Optional[str]]:
    if value in (None, "", "all"):
        return list(SYNC_EVENT_TYPES), None
    raw_values = value if isinstance(value, list) else [value]
    normalized = []
    aliases = {
        "two-pop": "two_pop",
        "2-pop": "two_pop",
        "2pop": "two_pop",
        "pop": "two_pop",
        "slate": "slate_clap",
        "slate-clap": "slate_clap",
        "clap": "slate_clap",
        "slate_clap": "slate_clap",
        "all": "all",
    }
    for raw in raw_values:
        key = str(raw or "").strip().lower().replace(" ", "_")
        event_type = aliases.get(key, key)
        if event_type == "all":
            return list(SYNC_EVENT_TYPES), None
        if event_type not in SYNC_EVENT_TYPES:
            return [], f"Unknown sync event type '{raw}'. Valid: {list(SYNC_EVENT_TYPES)}"
        if event_type not in normalized:
            normalized.append(event_type)
    return normalized or list(SYNC_EVENT_TYPES), None


def detect_sync_event_capabilities() -> Dict[str, Any]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    return {
        "success": True,
        "available": bool(ffmpeg and ffprobe),
        "no_auto_install": True,
        "tools": {
            "ffmpeg": {"available": bool(ffmpeg), "path": ffmpeg},
            "ffprobe": {"available": bool(ffprobe), "path": ffprobe},
        },
        "event_types": list(SYNC_EVENT_TYPES),
        "analysis": {
            "source_safe": True,
            "writes_media": False,
            "default_windows": ["head", "tail"],
            "outputs": ["event times", "frames", "record_offset suggestions"],
        },
    }


def sync_event_install_guidance(capabilities: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    caps = capabilities or detect_sync_event_capabilities()
    missing = {}
    tools = caps.get("tools", {})
    if not tools.get("ffmpeg", {}).get("available") or not tools.get("ffprobe", {}).get("available"):
        missing["ffmpeg_suite"] = {
            "required_for": ["2-pop detection", "slate-clap detection", "sync offset suggestions"],
            "macos": "Ask the user before running: brew install ffmpeg",
            "linux": "Ask the user to install ffmpeg with their distribution package manager.",
            "windows": "Ask the user to install ffmpeg and add ffmpeg/ffprobe to PATH.",
        }
    return {"success": True, "no_auto_install": True, "missing": missing}


def _run_json(args: List[str], timeout: int) -> Tuple[int, Dict[str, Any], str]:
    try:
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, {}, f"Command timed out after {timeout}s"
    except OSError as exc:
        return 127, {}, str(exc)
    stdout = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
    stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
    try:
        payload = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        payload = {}
    return proc.returncode, payload, stderr


def _probe_media(path: str, ffprobe_path: str, timeout: int) -> Dict[str, Any]:
    code, raw, stderr = _run_json(
        [
            ffprobe_path,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ],
        timeout,
    )
    if code != 0:
        return _err(stderr.strip() or "ffprobe failed")

    streams = raw.get("streams") or []
    fmt = raw.get("format") or {}
    duration = _coerce_float(fmt.get("duration"))
    audio_streams = []
    video_streams = []
    source_timecode = (fmt.get("tags") or {}).get("timecode")

    for stream in streams:
        tags = stream.get("tags") or {}
        if not source_timecode and tags.get("timecode"):
            source_timecode = tags.get("timecode")
        if stream.get("codec_type") == "audio":
            if duration is None:
                duration = _coerce_float(stream.get("duration"))
            audio_streams.append({
                "index": stream.get("index"),
                "codec": stream.get("codec_name"),
                "sample_rate": _coerce_int(stream.get("sample_rate")),
                "channels": stream.get("channels"),
                "duration_seconds": _coerce_float(stream.get("duration")),
            })
        elif stream.get("codec_type") == "video":
            frame_rate = _fraction_to_float(stream.get("avg_frame_rate")) or _fraction_to_float(stream.get("r_frame_rate"))
            if duration is None:
                duration = _coerce_float(stream.get("duration"))
            video_streams.append({
                "index": stream.get("index"),
                "codec": stream.get("codec_name"),
                "frame_rate": frame_rate,
                "duration_seconds": _coerce_float(stream.get("duration")),
            })

    return {
        "success": True,
        "duration_seconds": duration,
        "source_timecode": source_timecode,
        "audio_streams": audio_streams,
        "video_streams": video_streams,
        "format": {
            "format_name": fmt.get("format_name"),
            "size_bytes": _coerce_int(fmt.get("size")),
            "duration_seconds": _coerce_float(fmt.get("duration")),
        },
    }


def _nominal_timecode_rate(fps: float) -> int:
    if abs(fps - 23.976) < 0.02:
        return 24
    if abs(fps - 29.97) < 0.02:
        return 30
    if abs(fps - 47.952) < 0.05:
        return 48
    if abs(fps - 59.94) < 0.05:
        return 60
    return int(round(fps))


def _frames_to_timecode(frame: int, fps: float) -> Optional[str]:
    if fps <= 0:
        return None
    nominal = _nominal_timecode_rate(fps)
    if nominal <= 0:
        return None
    frame = max(0, int(frame))
    hours, remainder = divmod(frame, nominal * 3600)
    minutes, remainder = divmod(remainder, nominal * 60)
    seconds, frames = divmod(remainder, nominal)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"


def _timecode_for_event(time_seconds: float, fps: Optional[float], start_timecode: Optional[str]) -> Optional[str]:
    if not fps or not start_timecode:
        return None
    start_frame = timecode_to_frames(start_timecode, fps)
    if start_frame is None:
        return None
    return _frames_to_timecode(start_frame + int(round(time_seconds * fps)), fps)


def _event_marker_color(event_type: str, params: Dict[str, Any]) -> str:
    override = params.get("marker_color") or params.get("markerColor")
    if override:
        return str(override)
    return "Cyan" if event_type == "two_pop" else "Yellow"


def _event_marker_name(event: Dict[str, Any], params: Dict[str, Any]) -> str:
    prefix = str(params.get("marker_name_prefix") or params.get("markerNamePrefix") or "Sync")
    return f"{prefix}: {event.get('label') or event.get('type') or 'event'}"


def _event_marker_custom_data(record: Dict[str, Any], event: Dict[str, Any]) -> str:
    clip_key = record.get("clip_id") or Path(str(record.get("file_path") or record.get("clip_name") or "file")).name
    frame_key = event.get("frame")
    if frame_key is None:
        frame_key = f"{float(event.get('time_seconds') or 0.0):.3f}s"
    return f"mcp.sync_event:{clip_key}:{event.get('type')}:{frame_key}"


def _event_marker_suggestion(record: Dict[str, Any], event: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    clip_id = record.get("clip_id")
    frame = event.get("frame")
    note = (
        f"Detected {event.get('label')} at {event.get('time_seconds')}s"
        f" (confidence {event.get('confidence')}). Verify sync before using."
    )
    if event.get("timecode"):
        note += f" Timecode: {event['timecode']}."
    marker = {
        "frame": frame,
        "color": _event_marker_color(str(event.get("type") or ""), params),
        "name": _event_marker_name(event, params),
        "note": note,
        "duration": max(1, _coerce_int(params.get("marker_duration_frames"), 1) or 1),
        "custom_data": _event_marker_custom_data(record, event),
    }
    return {
        "scope": "media_pool_item",
        "clip_id": clip_id,
        "clip_name": record.get("clip_name"),
        "event_type": event.get("type"),
        "event_time_seconds": event.get("time_seconds"),
        "event_frame": frame,
        "confidence": event.get("confidence"),
        "marker": marker,
        "eligible": bool(clip_id and frame is not None),
        "requires_confirmation": True,
        "reason": None if clip_id and frame is not None else "Requires a Media Pool clip id and a detected event frame.",
    }


def _analysis_windows(duration: Optional[float], params: Dict[str, Any]) -> Tuple[List[Dict[str, float]], List[str]]:
    warnings: List[str] = []
    raw_windows = params.get("windows")
    max_window = max(1.0, _coerce_float(params.get("max_window_seconds"), 120.0) or 120.0)

    if isinstance(raw_windows, list) and raw_windows:
        windows = []
        for index, raw in enumerate(raw_windows):
            if not isinstance(raw, dict):
                warnings.append(f"Skipping windows[{index}] because it is not an object")
                continue
            start = max(0.0, _coerce_float(raw.get("start_seconds", raw.get("start")), 0.0) or 0.0)
            window_duration = _coerce_float(raw.get("duration_seconds", raw.get("duration")), None)
            if window_duration is None and duration is not None:
                window_duration = max(0.0, duration - start)
            if window_duration is None or window_duration <= 0:
                warnings.append(f"Skipping windows[{index}] because duration is missing or non-positive")
                continue
            if window_duration > max_window and not _coerce_bool(params.get("allow_long_windows"), False):
                warnings.append(f"Clamped windows[{index}] from {window_duration:.3f}s to {max_window:.3f}s")
                window_duration = max_window
            windows.append({
                "label": str(raw.get("label") or f"window_{index + 1}"),
                "start": start,
                "duration": window_duration,
            })
        return windows, warnings

    head = max(0.0, _coerce_float(params.get("scan_start_seconds"), DEFAULT_HEAD_SCAN_SECONDS) or 0.0)
    tail = max(0.0, _coerce_float(params.get("scan_tail_seconds"), DEFAULT_TAIL_SCAN_SECONDS) or 0.0)

    if _coerce_bool(params.get("scan_full"), False):
        full_duration = duration or max_window
        if full_duration > max_window and not _coerce_bool(params.get("allow_long_windows"), False):
            warnings.append(f"Clamped full scan from {full_duration:.3f}s to {max_window:.3f}s")
            full_duration = max_window
        return [{"label": "full", "start": 0.0, "duration": max(0.0, full_duration)}], warnings

    if duration is None:
        return [{"label": "head", "start": 0.0, "duration": min(head or max_window, max_window)}], warnings

    windows = []
    if head > 0:
        windows.append({"label": "head", "start": 0.0, "duration": min(head, duration, max_window)})
    if tail > 0 and duration > 0:
        tail_duration = min(tail, duration, max_window)
        tail_start = max(0.0, duration - tail_duration)
        if not windows or tail_start > windows[-1]["start"] + windows[-1]["duration"] - 0.5:
            windows.append({"label": "tail", "start": tail_start, "duration": tail_duration})
    return windows, warnings


def _decode_audio_window(
    path: str,
    window: Dict[str, float],
    *,
    ffmpeg_path: str,
    audio_stream_index: int,
    sample_rate: int,
    timeout: int,
) -> Tuple[Optional[array], Optional[str]]:
    args = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
    ]
    if window["start"] > 0:
        args.extend(["-ss", f"{window['start']:.6f}"])
    args.extend([
        "-i",
        path,
        "-t",
        f"{window['duration']:.6f}",
        "-map",
        f"0:a:{audio_stream_index}",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "f32le",
        "-",
    ])
    try:
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"ffmpeg audio decode timed out after {timeout}s"
    except OSError as exc:
        return None, str(exc)
    if proc.returncode != 0:
        return None, (proc.stderr or b"ffmpeg audio decode failed").decode("utf-8", errors="replace").strip()

    data = proc.stdout[: len(proc.stdout) - (len(proc.stdout) % 4)]
    samples = array("f")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples, None


def _estimate_frequency(samples: Sequence[float], sample_rate: int) -> Optional[float]:
    if len(samples) < max(8, sample_rate // 2000):
        return None
    active_indices = [index for index, sample in enumerate(samples) if abs(sample) >= 1e-4]
    if len(active_indices) < 4:
        return None
    first = active_indices[0]
    last = active_indices[-1]
    samples = samples[first:last + 1]
    crossings = 0
    previous = 0
    for sample in samples:
        if abs(sample) < 1e-4:
            continue
        sign = 1 if sample > 0 else -1
        if previous and sign != previous:
            crossings += 1
        previous = sign
    duration = len(samples) / float(sample_rate)
    if duration <= 0 or crossings < 2:
        return None
    return round(crossings / (2.0 * duration), 1)


def _window_envelope(samples: Sequence[float], sample_rate: int, step_seconds: float) -> List[Dict[str, float]]:
    window_size = max(1, int(round(sample_rate * step_seconds)))
    envelope = []
    for start in range(0, len(samples), window_size):
        chunk = samples[start:start + window_size]
        if not chunk:
            continue
        peak = max(abs(float(value)) for value in chunk)
        rms = math.sqrt(sum(float(value) * float(value) for value in chunk) / len(chunk))
        envelope.append({
            "sample_start": float(start),
            "sample_end": float(min(start + window_size, len(samples))),
            "peak": peak,
            "rms": rms,
        })
    return envelope


def _group_active_windows(envelope: List[Dict[str, float]], params: Dict[str, Any]) -> List[Tuple[int, int]]:
    if not envelope:
        return []
    rms_values = [row["rms"] for row in envelope]
    peak_values = [row["peak"] for row in envelope]
    noise_rms = _percentile(rms_values, 0.50)
    p90_rms = _percentile(rms_values, 0.90)
    p90_peak = _percentile(peak_values, 0.90)
    absolute_rms = _coerce_float(params.get("absolute_rms_threshold"), 0.015) or 0.015
    absolute_peak = _coerce_float(params.get("absolute_peak_threshold"), 0.08) or 0.08
    rms_threshold = max(absolute_rms, noise_rms * 6.0, p90_rms * 0.45)
    peak_threshold = max(absolute_peak, p90_peak * 0.60)

    active = [
        index
        for index, row in enumerate(envelope)
        if row["rms"] >= rms_threshold or row["peak"] >= peak_threshold
    ]
    if not active:
        return []

    groups = []
    gap_limit = max(0, _coerce_int(params.get("merge_gap_windows"), 2) or 0)
    start = active[0]
    previous = active[0]
    for index in active[1:]:
        if index - previous <= gap_limit + 1:
            previous = index
            continue
        groups.append((start, previous))
        start = previous = index
    groups.append((start, previous))
    return groups


def _score_event(metrics: Dict[str, Any], event_types: List[str]) -> Tuple[Optional[str], float, Dict[str, float]]:
    duration = float(metrics.get("duration_seconds") or 0)
    frequency = metrics.get("estimated_frequency_hz")
    crest = float(metrics.get("crest_factor") or 0)
    peak_dbfs = float(metrics.get("peak_dbfs") or -120)
    rms_dbfs = float(metrics.get("rms_dbfs") or -120)
    onset = float(metrics.get("onset_ratio") or 0)

    scores: Dict[str, float] = {}

    if "two_pop" in event_types:
        tonal = 0.0
        if frequency:
            tonal = max(0.0, 1.0 - abs(float(frequency) - 1000.0) / 400.0)
        score = 0.0
        if 0.015 <= duration <= 0.40:
            score += 0.25
        elif 0.005 <= duration <= 0.75:
            score += 0.10
        score += tonal * 0.45
        if rms_dbfs > -30:
            score += 0.15
        elif rms_dbfs > -42:
            score += 0.08
        if 0 < crest <= 4.0:
            score += 0.10
        if peak_dbfs > -24:
            score += 0.05
        scores["two_pop"] = min(0.99, score)

    if "slate_clap" in event_types:
        tonal_1k = bool(frequency and 800.0 <= float(frequency) <= 1200.0)
        score = 0.0
        if duration <= 0.25:
            score += 0.20
        elif duration <= 0.50:
            score += 0.08
        if peak_dbfs > -15:
            score += 0.20
        elif peak_dbfs > -30:
            score += 0.10
        if crest >= 4.0:
            score += 0.25
        elif crest >= 2.5:
            score += 0.10
        if not tonal_1k:
            score += 0.15
        if onset >= 8.0:
            score += 0.20
        elif onset >= 4.0:
            score += 0.10
        scores["slate_clap"] = min(0.99, score)

    if not scores:
        return None, 0.0, scores
    best_type, best_score = max(scores.items(), key=lambda row: row[1])
    return best_type, best_score, scores


def analyze_samples_for_sync_events(
    samples: Sequence[float],
    sample_rate: int,
    *,
    window_start_seconds: float = 0.0,
    fps: Optional[float] = None,
    start_timecode: Optional[str] = None,
    event_types: Optional[List[str]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    params = params or {}
    event_types = event_types or list(SYNC_EVENT_TYPES)
    step_seconds = max(0.002, _coerce_float(params.get("envelope_step_seconds"), 0.01) or 0.01)
    envelope = _window_envelope(samples, sample_rate, step_seconds)
    groups = _group_active_windows(envelope, params)
    min_confidence = _coerce_float(params.get("min_confidence"), 0.45) or 0.45
    events: List[Dict[str, Any]] = []

    for start_index, end_index in groups:
        start_sample = int(envelope[start_index]["sample_start"])
        end_sample = int(envelope[end_index]["sample_end"])
        event_segment = samples[start_sample:end_sample]
        if not event_segment:
            continue
        peak = max(abs(float(value)) for value in event_segment)
        rms = math.sqrt(sum(float(value) * float(value) for value in event_segment) / len(event_segment))
        if rms <= 0 and peak <= 0:
            continue
        previous_rms = _percentile([row["rms"] for row in envelope[max(0, start_index - 10):start_index]], 0.50)
        onset_ratio = peak / max(previous_rms, 1e-6)
        duration_seconds = max(step_seconds, (end_sample - start_sample) / float(sample_rate))
        local_time = start_sample / float(sample_rate)
        absolute_time = window_start_seconds + local_time
        estimated_frequency = _estimate_frequency(event_segment, sample_rate)
        crest = peak / max(rms, 1e-9)
        metrics = {
            "duration_seconds": round(duration_seconds, 6),
            "estimated_frequency_hz": estimated_frequency,
            "peak_dbfs": _dbfs(peak),
            "rms_dbfs": _dbfs(rms),
            "crest_factor": round(crest, 3),
            "onset_ratio": round(onset_ratio, 3),
        }
        event_type, confidence, scores = _score_event(metrics, event_types)
        if not event_type or confidence < min_confidence:
            continue
        event_frame = int(round(absolute_time * fps)) if fps else None
        event = {
            "type": event_type,
            "label": "2-pop" if event_type == "two_pop" else "slate clap",
            "time_seconds": round(absolute_time, 6),
            "window_local_time_seconds": round(local_time, 6),
            "frame": event_frame,
            "timecode": _timecode_for_event(absolute_time, fps, start_timecode),
            "confidence": round(confidence, 3),
            "scores": {key: round(value, 3) for key, value in scores.items()},
            **metrics,
        }
        events.append(event)

    return sorted(events, key=lambda row: (-row["confidence"], row["time_seconds"]))


def _record_path(record: Dict[str, Any]) -> Optional[str]:
    path = record.get("file_path") or record.get("path")
    if not path:
        return None
    return os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))


def _record_fps(record: Dict[str, Any], probe: Dict[str, Any], params: Dict[str, Any]) -> Optional[float]:
    explicit = _coerce_float(params.get("fps"))
    if explicit:
        return explicit
    record_fps = _coerce_float(record.get("fps"))
    if record_fps:
        return record_fps
    videos = probe.get("video_streams") or []
    for video in videos:
        if video.get("frame_rate"):
            return _coerce_float(video.get("frame_rate"))
    return None


def _start_timecode(record: Dict[str, Any], probe: Dict[str, Any], params: Dict[str, Any]) -> Optional[str]:
    return (
        params.get("start_timecode")
        or params.get("source_timecode")
        or record.get("start_timecode")
        or record.get("source_timecode")
        or probe.get("source_timecode")
    )


def detect_sync_events_for_file(record: Dict[str, Any], params: Dict[str, Any], capabilities: Dict[str, Any]) -> Dict[str, Any]:
    path = _record_path(record)
    if not path:
        return _err("Record has no file_path", clip_name=record.get("clip_name"))
    if not os.path.isfile(path):
        return _err(f"Media file not found: {path}", path=path, clip_name=record.get("clip_name"))

    tools = capabilities.get("tools", {})
    ffmpeg_path = tools.get("ffmpeg", {}).get("path") or "ffmpeg"
    ffprobe_path = tools.get("ffprobe", {}).get("path") or "ffprobe"
    timeout = _coerce_int(params.get("timeout_seconds"), DEFAULT_COMMAND_TIMEOUT_SECONDS) or DEFAULT_COMMAND_TIMEOUT_SECONDS
    probe = _probe_media(path, ffprobe_path, timeout)
    if not probe.get("success"):
        probe.update({"path": path, "clip_name": record.get("clip_name")})
        return probe
    if not probe.get("audio_streams"):
        return _err("No audio streams found for sync-event detection", path=path, clip_name=record.get("clip_name"))

    event_types, event_err = _normalize_event_types(params.get("event_types"))
    if event_err:
        return _err(event_err, path=path, clip_name=record.get("clip_name"))

    sample_rate = max(1000, _coerce_int(params.get("sample_rate"), DEFAULT_SAMPLE_RATE) or DEFAULT_SAMPLE_RATE)
    audio_stream_index = max(0, _coerce_int(params.get("audio_stream_index"), 0) or 0)
    fps = _record_fps(record, probe, params)
    start_tc = _start_timecode(record, probe, params)
    windows, warnings = _analysis_windows(probe.get("duration_seconds"), params)

    all_events = []
    for window in windows:
        samples, decode_error = _decode_audio_window(
            path,
            window,
            ffmpeg_path=ffmpeg_path,
            audio_stream_index=audio_stream_index,
            sample_rate=sample_rate,
            timeout=timeout,
        )
        if decode_error:
            warnings.append(f"{window['label']} decode failed: {decode_error}")
            continue
        events = analyze_samples_for_sync_events(
            samples or [],
            sample_rate,
            window_start_seconds=window["start"],
            fps=fps,
            start_timecode=start_tc,
            event_types=event_types,
            params=params,
        )
        for event in events:
            event["window"] = {
                "label": window["label"],
                "start_seconds": round(window["start"], 6),
                "duration_seconds": round(window["duration"], 6),
            }
        all_events.extend(events)

    max_events = max(1, _coerce_int(params.get("max_events_per_file"), 12) or 12)
    all_events = sorted(all_events, key=lambda row: (-row["confidence"], row["time_seconds"]))[:max_events]
    all_events = sorted(all_events, key=lambda row: row["time_seconds"])
    marker_suggestions = [_event_marker_suggestion(record, event, params) for event in all_events]

    return {
        "success": True,
        "clip_id": record.get("clip_id"),
        "clip_name": record.get("clip_name") or Path(path).name,
        "path": path,
        "source_safe": True,
        "writes_media": False,
        "metadata": {
            "duration_seconds": probe.get("duration_seconds"),
            "fps": fps,
            "source_timecode": start_tc,
            "audio_streams": probe.get("audio_streams"),
            "video_streams": probe.get("video_streams"),
        },
        "scan": {
            "sample_rate": sample_rate,
            "audio_stream_index": audio_stream_index,
            "windows": windows,
            "event_types": event_types,
        },
        "events": all_events,
        "marker_suggestions": marker_suggestions,
        "marker_write": {
            "available": any(suggestion.get("eligible") for suggestion in marker_suggestions),
            "requires_confirmation": True,
            "action": "media_analysis(action='add_sync_event_markers')",
            "note": "Detection only suggests markers; marker writes require an explicit confirmed action.",
        },
        "warnings": warnings,
    }


def _best_alignment_event(file_result: Dict[str, Any], preferred_type: Optional[str]) -> Optional[Dict[str, Any]]:
    events = file_result.get("events") or []
    if preferred_type:
        typed = [event for event in events if event.get("type") == preferred_type]
        if typed:
            return max(typed, key=lambda row: row.get("confidence", 0))
    if not events:
        return None
    return max(events, key=lambda row: row.get("confidence", 0))


def _alignment_suggestions(file_results: List[Dict[str, Any]], params: Dict[str, Any]) -> Dict[str, Any]:
    preferred_type = params.get("prefer_event_type") or params.get("alignment_event_type")
    if preferred_type:
        event_types, event_err = _normalize_event_types([preferred_type])
        if event_err:
            return {"success": False, "error": event_err}
        preferred_type = event_types[0]

    choices = []
    for index, result in enumerate(file_results):
        if not result.get("success"):
            continue
        event = _best_alignment_event(result, preferred_type)
        if not event:
            continue
        fps = _coerce_float((result.get("metadata") or {}).get("fps")) or _coerce_float(params.get("fps")) or 24.0
        event_frame = event.get("frame")
        if event_frame is None:
            event_frame = int(round(float(event.get("time_seconds") or 0.0) * fps))
        choices.append((index, result, event, int(event_frame), fps))

    if not choices:
        return {
            "success": True,
            "status": "no_common_sync_events",
            "suggestions": [],
            "notes": ["No sync events were detected strongly enough to suggest record offsets."],
        }

    reference_index = _coerce_int(params.get("reference_index"), None)
    reference_path = params.get("reference_path")
    reference = None
    if reference_path:
        reference_path = os.path.realpath(os.path.abspath(os.path.expanduser(str(reference_path))))
        for choice in choices:
            if choice[1].get("path") == reference_path:
                reference = choice
                break
    if reference is None and reference_index is not None:
        for choice in choices:
            if choice[0] == reference_index:
                reference = choice
                break
    if reference is None:
        reference = choices[0]

    _, reference_result, reference_event, reference_frame, reference_fps = reference
    suggestions = []
    for index, result, event, event_frame, fps in choices:
        offset_frames = reference_frame - event_frame
        offset_seconds = offset_frames / float(fps or reference_fps or 24.0)
        suggestions.append({
            "index": index,
            "clip_id": result.get("clip_id"),
            "clip_name": result.get("clip_name"),
            "path": result.get("path"),
            "event_type": event.get("type"),
            "event_time_seconds": event.get("time_seconds"),
            "event_frame": event_frame,
            "confidence": event.get("confidence"),
            "suggested_record_offset_frames": offset_frames,
            "suggested_record_offset_seconds": round(offset_seconds, 6),
        })

    return {
        "success": True,
        "reference": {
            "clip_id": reference_result.get("clip_id"),
            "clip_name": reference_result.get("clip_name"),
            "path": reference_result.get("path"),
            "event_type": reference_event.get("type"),
            "event_time_seconds": reference_event.get("time_seconds"),
            "event_frame": reference_frame,
            "confidence": reference_event.get("confidence"),
        },
        "suggestions": suggestions,
        "notes": [
            "Use suggested_record_offset_frames as per-angle record_offset values with "
            "media_pool.setup_multicam_timeline(sync_mode='record_frame').",
            "Offsets are advisory; verify sync visually and audibly in Resolve before converting to a native multicam clip.",
        ],
    }


def detect_sync_events_for_records(records: Iterable[Dict[str, Any]], params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    params = dict(params or {})
    caps = detect_sync_event_capabilities()
    if not caps.get("available"):
        return {
            "success": False,
            "status": "missing_dependency",
            "no_auto_install": True,
            "capabilities": caps,
            "install_guidance": sync_event_install_guidance(caps),
        }

    file_results = []
    warnings = []
    for record in records:
        result = detect_sync_events_for_file(record, params, caps)
        if result.get("warnings"):
            warnings.extend(result["warnings"])
        file_results.append(result)

    alignment = _alignment_suggestions(file_results, params)
    return {
        "success": any(result.get("success") for result in file_results),
        "source_safe": True,
        "writes_media": False,
        "no_auto_install": True,
        "capabilities": caps,
        "files": file_results,
        "alignment": alignment,
        "marker_write": {
            "available": any(
                suggestion.get("eligible")
                for result in file_results
                for suggestion in (result.get("marker_suggestions") or [])
            ),
            "requires_confirmation": True,
            "action": "media_analysis(action='add_sync_event_markers')",
            "note": "Ask the user before adding Resolve markers from detected sync events.",
        },
        "warnings": warnings,
    }
