"""Preserve native pixel coordinates without inventing undocumented geometry limits."""
import math


def validate_blanking(options):
    if not isinstance(options,dict) or not options:
        return 'options must be a non-empty dictionary'
    if set(options)-{'Top','Bottom','Left','Right'}:
        return 'Only Top, Bottom, Left and Right are accepted'
    for value in options.values():
        try:
            valid = type(value) in (int,float) and math.isfinite(value) and int(value)==value
        except OverflowError:
            valid = False
        if not valid:
            return 'Blanking values must be finite whole-pixel coordinates'
    return None
