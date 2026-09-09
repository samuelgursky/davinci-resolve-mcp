"""Read-only validation of granular clip-type recognition on a running Resolve.

Run from the repository root: python tests/live_granular_item_types.py
Requires an open timeline with an ordinary video clip on a video track.
Reads the first such clip through the actual property-resource handler.
Does not set properties, switch projects/timelines or render. Mutation coverage
is limited to the stub contracts in test_granular_item_types.py.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from src.granular.common import get_current_project, get_resolve
    from src.granular.timeline_item import get_timeline_item_properties

    _, project = get_current_project()
    if project is None or project.GetCurrentTimeline() is None:
        raise SystemExit("Open a timeline with an ordinary video clip first.")
    timeline = project.GetCurrentTimeline()
    item = next((
        item
        for track in range(1, timeline.GetTrackCount("video") + 1)
        for item in (timeline.GetItemListInTrack("video", track) or [])
        # `GetMediaPoolItem` resolves to None on some items (a conform
        # timeline's transitions on Studio 19.1.3.7), and calling None raises
        # before the read under test; only call it where it is callable.
        if callable(getattr(item, "GetMediaPoolItem", None))
        and item.GetMediaPoolItem() is not None
    ), None)
    if item is None:
        raise SystemExit("No ordinary video clip found; nothing was changed.")
    result = get_timeline_item_properties(str(item.GetUniqueId()))
    receipt = {
        "version": get_resolve().GetVersionString(),
        "type": item.GetType(),
        "error": result.get("error"),
        "has_transform": "transform" in result,
        "has_crop": "crop" in result,
        "has_composite": "composite" in result,
        "optional_media_type_callable": callable(getattr(item, "GetMediaType", None)),
        "mutators_invoked": False,
    }
    print(json.dumps(receipt, indent=2))
    assert receipt["error"] is None, receipt
    assert receipt["has_transform"] and receipt["has_crop"] and receipt["has_composite"], receipt


if __name__ == "__main__":
    main()
