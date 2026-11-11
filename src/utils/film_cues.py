"""Read-only picture-to-score interchange; frames, not timecodes, are canonical.

Resolve timeline marker keys are relative to timeline start, even for markers
later than that start's absolute frame number. Never guess/rebase those keys.
"""
from fractions import Fraction
import math
import re


def _integer(value, field, minimum=0):
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer >= {minimum}")
    try:
        number = Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{field} must be an integer >= {minimum}") from exc
    if number.denominator != 1 or number < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return int(number)


def _rate(value):
    text = str(value).strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?(?:/\d+)?)\s*(?:DF|NDF)?", text)
    if not match:
        raise ValueError("timelineFrameRate must be a positive numeric frame rate")
    text = match[1]
    # Resolve displays rounded NTSC rates. Recover their standard clock rates
    # before converting a feature-length timeline to seconds.
    ntsc = {"23.976": 24000, "23.98": 24000, "29.97": 30000,
            "47.952": 48000, "59.94": 60000, "119.88": 120000}
    try:
        rate = Fraction(ntsc[text], 1001) if text in ntsc else Fraction(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError("Invalid timelineFrameRate") from exc
    if rate <= 0 or rate > 1000:
        raise ValueError("timelineFrameRate must be between 0 and 1000 fps")
    return rate


def export_cue_sheet(timeline, *, color=None):
    """Return a film-cues/v1 payload without writing files or changing Resolve.

    ``start_frame`` inside each cue is relative; ``timeline.start_frame`` is
    absolute metadata only. Seconds are convenient approximations; consumers
    must derive timing from integer frames and the rational frame rate.
    """
    if color is not None and (not isinstance(color, str) or not color.strip()):
        raise ValueError("color must be a non-empty marker colour name")
    rate = _rate(timeline.GetSetting("timelineFrameRate"))
    start = _integer(timeline.GetStartFrame(), "timeline start frame")
    markers = timeline.GetMarkers()
    if not isinstance(markers, dict):
        raise ValueError("Resolve did not return a marker dictionary")
    cues = []
    seen = set()
    for key, marker in markers.items():
        if not isinstance(marker, dict):
            raise ValueError("Resolve returned an invalid marker record")
        frame = _integer(key, "marker frame")
        if frame in seen:
            raise ValueError(f"Duplicate marker frame {frame}")
        seen.add(frame)
        duration = _integer(marker.get("duration"), "marker duration", 1)
        values = {}
        for source, target in (("name", "name"), ("note", "note"),
                               ("color", "color"), ("customData", "custom_data")):
            value = marker.get(source, "")
            if not isinstance(value, str):
                raise ValueError(f"marker {source} must be a string")
            values[target] = value
        seconds, duration_seconds = float(frame / rate), float(duration / rate)
        if not math.isfinite(seconds) or not math.isfinite(duration_seconds):
            raise ValueError("Marker timing exceeds the supported numeric range")
        if color is not None and values["color"].casefold() != color.casefold():
            continue
        cues.append({"id": f"marker:{frame}", **values,
                     "start_frame": frame, "duration_frames": duration,
                     "start_seconds": seconds, "duration_seconds": duration_seconds})
    return {"schema": "film-cues/v1",
            "frame_rate": {"numerator": rate.numerator, "denominator": rate.denominator},
            "timeline": {"name": timeline.GetName(), "start_frame": start,
                         "start_timecode": timeline.GetStartTimecode()},
            "cues": sorted(cues, key=lambda cue: cue["start_frame"])}
