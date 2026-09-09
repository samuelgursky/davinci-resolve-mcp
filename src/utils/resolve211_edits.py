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


def validate_transition_options(options):
    if not isinstance(options, dict) or not options:
        return "options must be a non-empty dictionary"
    allowed = {"type", "category", "position", "alignment", "duration"}
    if set(options) - allowed:
        return "Unknown transition options: " + ", ".join(sorted(map(str, set(options) - allowed)))
    if not isinstance(options.get("type"), str) or not options["type"].strip():
        return "type must be a non-empty transition name"
    for key, choices in (("category", ("simple", "fusion", "ofx", "audio")),
                         ("position", ("start", "end")),
                         ("alignment", ("left", "center", "right"))):
        if options.get(key) not in choices:
            return key + " must be one of: " + ", ".join(choices)
    duration = options.get("duration")
    if duration is not None and (type(duration) is not int or duration <= 0):
        return "duration must be a positive integer number of frames or null"
    return None


def transition_result(transition):
    if transition is None or transition is False:
        return {"success": False}
    return {"success": True, "transition": {
        "id": transition.GetUniqueId(), "name": transition.GetName(),
        "start": transition.GetStart(), "end": transition.GetEnd(),
        "duration": transition.GetDuration(),
    }}
