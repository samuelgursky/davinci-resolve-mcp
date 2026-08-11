"""Deduplicated, read-only exposure planning for timeline source ranges."""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List


Analyzer = Callable[[str, float], Dict[str, Any]]


def build_exposure_plan(
    items: Iterable[Dict[str, Any]],
    analyzer: Analyzer,
    *,
    source_fps: float = 30.0,
) -> Dict[str, Any]:
    rows = list(items)
    blockers: List[Dict[str, Any]] = []
    cache: Dict[tuple, Dict[str, Any]] = {}
    results: List[Dict[str, Any]] = []
    fps = float(source_fps)
    if fps <= 0:
        return {"success": False, "items": [], "blockers": [{"code": "INVALID_SOURCE_FPS"}]}

    for item in rows:
        item_id = item.get("timeline_item_id")
        path = item.get("file_path")
        online = str(item.get("online_status") or "").lower() == "online"
        start = item.get("source_start")
        end = item.get("source_end")
        if not path or not online or start is None or end is None:
            blocker = {"code": "SOURCE_UNAVAILABLE", "timeline_item_id": item_id}
            blockers.append(blocker)
            results.append({"timeline_item_id": item_id, "analysis": {"success": False, "error": "source unavailable"}})
            continue
        key = (path, int(start), int(end))
        if key not in cache:
            at_seconds = ((int(start) + int(end)) / 2.0) / fps
            try:
                cache[key] = analyzer(path, at_seconds)
            except Exception as exc:
                cache[key] = {"success": False, "error": str(exc)}
        analysis = cache[key]
        results.append({"timeline_item_id": item_id, "source_range": {"path": path, "start": int(start), "end": int(end)}, "analysis": analysis})
        if not analysis.get("success"):
            blockers.append({"code": "EXPOSURE_ANALYSIS_FAILED", "timeline_item_id": item_id, "error": analysis.get("error")})

    return {
        "success": not blockers,
        "items": results,
        "blockers": blockers,
        "unique_ranges_analyzed": len(cache),
    }
