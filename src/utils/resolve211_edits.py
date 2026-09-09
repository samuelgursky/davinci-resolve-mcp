"""Validate native 21.1 editing dictionaries without guessing undocumented bounds."""
import math


def validate_edit_options(action, options):
    if not isinstance(options, dict) or not options:
        return "options must be a non-empty dictionary"
    allowed = ({"Percentage", "PitchCorrection", "StretchKeyframesToFit", "RippleTimeline"}
               if action == "set_speed" else {"FadeIn", "FadeOut"})
    if set(options) - allowed:
        return "Unknown options: " + ", ".join(sorted(map(str, set(options) - allowed)))
    for key, value in options.items():
        if key in {"PitchCorrection", "StretchKeyframesToFit", "RippleTimeline"}:
            if type(value) is not bool:
                return key + " must be a boolean"
        elif action == "set_fades":
            if type(value) is not int or value < 0:
                return key + " must be a non-negative integer number of frames"
        else:
            try:
                finite = type(value) in (int, float) and math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                return key + " must be a finite number"
    return None
