"""Deterministic, dependency-free cover-frame quality signals."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _metrics(raw_rgb: bytes) -> Dict[str, float]:
    if not raw_rgb:
        return {"brightness": 0.0, "detail": 0.0, "clipped": 0.0, "crushed": 1.0, "score": -1.0}
    luminance = [sum(raw_rgb[index:index + 3]) / 3.0 for index in range(0, len(raw_rgb), 3)]
    brightness = sum(luminance) / len(luminance) / 255.0
    detail = (sum(abs(b - a) for a, b in zip(luminance, luminance[1:])) / max(1, len(luminance) - 1)) / 255.0
    clipped = sum(value >= 250 for value in luminance) / len(luminance)
    crushed = sum(value <= 5 for value in luminance) / len(luminance)
    exposure = max(0.0, 1.0 - abs(brightness - 0.5) * 2.0)
    score = round(0.55 * detail + 0.45 * exposure - 0.30 * clipped - 0.15 * crushed, 6)
    return {"brightness": round(brightness, 6), "detail": round(detail, 6), "clipped": round(clipped, 6), "crushed": round(crushed, 6), "score": score}


def rank_cover_candidates(samples: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked = []
    for sample in samples:
        thumbnail = sample.get("thumbnail_rgb")
        if not thumbnail or len(thumbnail) != 3:
            continue
        _, _, raw_rgb = thumbnail
        row = {key: value for key, value in sample.items() if key != "thumbnail_rgb"}
        row.update(_metrics(raw_rgb))
        ranked.append(row)
    ranked.sort(key=lambda row: (-row["score"], int(row.get("frame") or 0)))
    for index, row in enumerate(ranked, 1):
        row["rank"] = index
    return ranked
