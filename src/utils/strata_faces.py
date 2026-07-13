"""Face strata — blink events + gaze/expression curves (optional capability).

Requires mediapipe + opencv (``pip install mediapipe opencv-python``). Both
are optional extras: when absent this module still imports, reports itself
unavailable, and run_face_strata refuses honestly. Nothing else in the
strata stack depends on it — cut_candidates simply notes the blink track as
missing.

What it writes (geometric measurements, not emotion classification):
- events  ``blink``                 — eye-aspect-ratio dip (Soukupová/Čech EAR)
- curves  ``gaze_x`` / ``gaze_y``   — iris offset within the eye box, -1..1
- curves  ``expression_mouth_open`` — mouth aspect ratio 0..~1
- curves  ``expression_brow_raise`` — brow-to-eye distance, face-height units

The compute layer is pure (landmark series in, tracks out) so blink/gaze
logic is unit-testable without mediapipe; only the capture loop needs it.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.utils import strata, timeline_brain_db

logger = logging.getLogger("resolve-mcp.strata-faces")

FACE_SOURCE = "face_v1"
FACE_VERSION = "1.0.0"

FACE_CURVE_RATE_DEFAULT = 12.0  # analysis fps; blinks need >=10 to be caught

# Broad excepts on purpose: mediapipe (and cv2) can raise non-ImportError
# exceptions at import time (e.g. protobuf version mismatches raise TypeError).
# A broken optional dependency must degrade to "face analyzer unavailable",
# never crash strata_status / strata_run.
try:  # pragma: no cover - environment-dependent
    import cv2 as _cv2
except Exception as _exc:  # pragma: no cover
    logger.debug("cv2 unavailable: %s", _exc)
    _cv2 = None

try:  # pragma: no cover - environment-dependent
    import mediapipe as _mp
except Exception as _exc:  # pragma: no cover
    logger.debug("mediapipe unavailable: %s", _exc)
    _mp = None

# FaceMesh landmark indices (canonical mediapipe topology).
_LEFT_EYE = {"outer": 33, "inner": 133, "top1": 160, "top2": 158, "bot1": 144, "bot2": 153}
_RIGHT_EYE = {"outer": 362, "inner": 263, "top1": 385, "top2": 387, "bot1": 380, "bot2": 373}
_LEFT_IRIS = (468, 469, 470, 471, 472)
_RIGHT_IRIS = (473, 474, 475, 476, 477)
_MOUTH = {"left": 61, "right": 291, "top": 13, "bottom": 14}
_BROW = {"left": 105, "right": 334}
_FACE_BOX = {"top": 10, "bottom": 152}

EAR_BLINK_THRESHOLD = 0.21
EAR_MIN_CLOSED_FRAMES = 1
EAR_MAX_CLOSED_SECONDS = 0.5  # longer than this is eyes-closed, not a blink


def capabilities() -> Dict[str, Any]:
    available = _cv2 is not None and _mp is not None
    return {
        "available": available,
        "requires": ["opencv-python", "mediapipe"],
        "missing": [
            name
            for name, mod in (("opencv-python", _cv2), ("mediapipe", _mp))
            if mod is None
        ],
        "writes": {
            "events": ["blink"],
            "curves": ["gaze_x", "gaze_y", "expression_mouth_open", "expression_brow_raise"],
        },
    }


# ── pure compute: landmark series → tracks ───────────────────────────────────


def _dist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def eye_aspect_ratio(pts: Dict[str, Tuple[float, float]]) -> float:
    """EAR = (‖top1−bot1‖ + ‖top2−bot2‖) / (2·‖outer−inner‖)."""
    horiz = _dist(pts["outer"], pts["inner"])
    if horiz <= 0:
        return 0.0
    return (_dist(pts["top1"], pts["bot1"]) + _dist(pts["top2"], pts["bot2"])) / (2.0 * horiz)


def detect_blinks(
    ear_series: Sequence[Optional[float]],
    rate_hz: float,
    threshold: float = EAR_BLINK_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Blink events from an EAR time series (None = no face that frame).

    A blink is a run of frames with EAR below threshold, at least
    EAR_MIN_CLOSED_FRAMES long and shorter than EAR_MAX_CLOSED_SECONDS
    (longer runs are eyes-closed, recorded with kind='eyes_closed').
    """
    blinks: List[Dict[str, Any]] = []
    run_start: Optional[int] = None
    max_frames = int(EAR_MAX_CLOSED_SECONDS * rate_hz)

    def flush(end_index: int) -> None:
        nonlocal run_start
        if run_start is None:
            return
        length = end_index - run_start
        if length >= EAR_MIN_CLOSED_FRAMES:
            event = {
                "time_seconds": run_start / rate_hz,
                "duration_seconds": length / rate_hz,
                "payload": {"kind": "blink" if length <= max_frames else "eyes_closed"},
            }
            blinks.append(event)
        run_start = None

    for i, ear in enumerate(ear_series):
        below = ear is not None and ear < threshold
        if below and run_start is None:
            run_start = i
        elif not below:
            flush(i)
    flush(len(ear_series))
    return blinks


def iris_offset(
    eye_pts: Dict[str, Tuple[float, float]],
    iris_center: Tuple[float, float],
) -> Tuple[float, float]:
    """Iris position inside the eye box, each axis -1..1 (0 = centered)."""
    cx = (eye_pts["outer"][0] + eye_pts["inner"][0]) / 2.0
    cy = (eye_pts["top1"][1] + eye_pts["top2"][1] + eye_pts["bot1"][1] + eye_pts["bot2"][1]) / 4.0
    half_w = abs(eye_pts["inner"][0] - eye_pts["outer"][0]) / 2.0 or 1.0
    half_h = (
        abs((eye_pts["bot1"][1] + eye_pts["bot2"][1]) / 2.0 - (eye_pts["top1"][1] + eye_pts["top2"][1]) / 2.0)
    ) / 2.0 or 1.0
    return (
        max(-1.0, min(1.0, (iris_center[0] - cx) / half_w)),
        max(-1.0, min(1.0, (iris_center[1] - cy) / half_h)),
    )


def landmarks_to_tracks(
    frames: Sequence[Optional[Dict[str, Any]]],
    rate_hz: float,
) -> Dict[str, Any]:
    """Per-frame landmark dicts → blink events + gaze/expression curves.

    Each frame entry (or None when no face): {
      left_eye/right_eye: {outer,inner,top1,top2,bot1,bot2: (x,y)},
      left_iris/right_iris: (x,y),
      mouth: {left,right,top,bottom: (x,y)},
      brow: {left,right: (x,y)}, face: {top,bottom: (x,y)},
    }
    """
    nan = float("nan")
    ear_series: List[Optional[float]] = []
    gaze_x: List[float] = []
    gaze_y: List[float] = []
    mouth_open: List[float] = []
    brow_raise: List[float] = []

    for frame in frames:
        if not frame:
            ear_series.append(None)
            gaze_x.append(nan)
            gaze_y.append(nan)
            mouth_open.append(nan)
            brow_raise.append(nan)
            continue
        ears = []
        offsets = []
        for eye_key, iris_key in (("left_eye", "left_iris"), ("right_eye", "right_iris")):
            eye = frame.get(eye_key)
            if not eye:
                continue
            ears.append(eye_aspect_ratio(eye))
            iris = frame.get(iris_key)
            if iris:
                offsets.append(iris_offset(eye, iris))
        ear_series.append(sum(ears) / len(ears) if ears else None)
        if offsets:
            gaze_x.append(sum(o[0] for o in offsets) / len(offsets))
            gaze_y.append(sum(o[1] for o in offsets) / len(offsets))
        else:
            gaze_x.append(nan)
            gaze_y.append(nan)

        mouth = frame.get("mouth")
        if mouth:
            width = _dist(mouth["left"], mouth["right"]) or 1.0
            mouth_open.append(_dist(mouth["top"], mouth["bottom"]) / width)
        else:
            mouth_open.append(nan)

        brow = frame.get("brow")
        face = frame.get("face")
        eye = frame.get("left_eye") or frame.get("right_eye")
        if brow and face and eye:
            face_h = _dist(face["top"], face["bottom"]) or 1.0
            eye_top_y = (eye["top1"][1] + eye["top2"][1]) / 2.0
            brow_y = (brow["left"][1] + brow["right"][1]) / 2.0
            brow_raise.append(abs(eye_top_y - brow_y) / face_h)
        else:
            brow_raise.append(nan)

    return {
        "blinks": detect_blinks(ear_series, rate_hz),
        "curves": {
            "gaze_x": gaze_x,
            "gaze_y": gaze_y,
            "expression_mouth_open": mouth_open,
            "expression_brow_raise": brow_raise,
        },
        "face_frame_count": sum(1 for e in ear_series if e is not None),
        "frame_count": len(frames),
    }


# ── capture loop (mediapipe/cv2 required) ────────────────────────────────────


def _landmark_frame(landmarks, width: int, height: int) -> Dict[str, Any]:
    def pt(idx: int) -> Tuple[float, float]:
        lm = landmarks[idx]
        return (lm.x * width, lm.y * height)

    def group(spec: Dict[str, int]) -> Dict[str, Tuple[float, float]]:
        return {name: pt(idx) for name, idx in spec.items()}

    frame: Dict[str, Any] = {
        "left_eye": group(_LEFT_EYE),
        "right_eye": group(_RIGHT_EYE),
        "mouth": group(_MOUTH),
        "brow": group(_BROW),
        "face": group(_FACE_BOX),
    }
    if len(landmarks) > _RIGHT_IRIS[-1]:
        for key, indices in (("left_iris", _LEFT_IRIS), ("right_iris", _RIGHT_IRIS)):
            xs = [pt(i)[0] for i in indices]
            ys = [pt(i)[1] for i in indices]
            frame[key] = (sum(xs) / len(xs), sum(ys) / len(ys))
    return frame


def extract_landmark_frames(
    video_path: str,
    rate_hz: float = FACE_CURVE_RATE_DEFAULT,
    max_seconds: Optional[float] = None,
) -> Tuple[List[Optional[Dict[str, Any]]], float]:
    """Sample the video at ~rate_hz and run FaceMesh per sampled frame."""
    if _cv2 is None or _mp is None:  # pragma: no cover
        raise RuntimeError("face strata require opencv-python + mediapipe")
    cap = _cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"could not open video: {video_path}")
    native_fps = cap.get(_cv2.CAP_PROP_FPS) or 24.0
    step = max(1, int(round(native_fps / rate_hz)))
    effective_rate = native_fps / step
    frames: List[Optional[Dict[str, Any]]] = []
    with _mp.solutions.face_mesh.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    ) as mesh:
        index = 0
        while True:
            ok, image = cap.read()
            if not ok:
                break
            if index % step == 0:
                if max_seconds is not None and (index / native_fps) > max_seconds:
                    break
                result = mesh.process(_cv2.cvtColor(image, _cv2.COLOR_BGR2RGB))
                if result.multi_face_landmarks:
                    height, width = image.shape[:2]
                    frames.append(
                        _landmark_frame(result.multi_face_landmarks[0].landmark, width, height)
                    )
                else:
                    frames.append(None)
            index += 1
    cap.release()
    return frames, effective_rate


def run_face_strata(
    project_root: str,
    clip_ref: Any,
    *,
    rate_hz: float = FACE_CURVE_RATE_DEFAULT,
    max_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute + persist face strata for one clip (refuses without deps)."""
    caps = capabilities()
    if not caps["available"]:
        return {
            "success": False,
            "error": f"face strata unavailable — install: {', '.join(caps['missing'])}",
            "missing": caps["missing"],
        }
    from src.utils.strata_analyzers import _clip_row

    clip, err = _clip_row(project_root, clip_ref)
    if err:
        return err
    try:
        frames, effective_rate = extract_landmark_frames(
            clip["file_path"], rate_hz=rate_hz, max_seconds=max_seconds
        )
    except RuntimeError as exc:
        return {"success": False, "error": str(exc), "clip_uuid": clip["clip_uuid"]}
    if not frames:
        return {"success": False, "error": "no video frames sampled", "clip_uuid": clip["clip_uuid"]}

    tracks = landmarks_to_tracks(frames, effective_rate)
    with timeline_brain_db.transaction(project_root) as txn:
        strata.replace_track_events(
            txn, clip["clip_uuid"], "blink", tracks["blinks"],
            source=FACE_SOURCE, analyzer_version=FACE_VERSION,
        )
        for track_name, values in tracks["curves"].items():
            strata.write_curve(
                txn, clip["clip_uuid"], track_name, values,
                sample_rate=effective_rate, source=FACE_SOURCE, analyzer_version=FACE_VERSION,
            )
    return {
        "success": True,
        "clip_uuid": clip["clip_uuid"],
        "clip_name": clip["clip_name"],
        "sample_rate": round(effective_rate, 3),
        "frames_sampled": tracks["frame_count"],
        "frames_with_face": tracks["face_frame_count"],
        "blink_count": len(tracks["blinks"]),
        "analyzer_version": FACE_VERSION,
    }
