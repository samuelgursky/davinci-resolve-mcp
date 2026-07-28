#!/usr/bin/env python3
"""Labelled contact sheets from a media_analysis frames directory.

Solves a concrete cost problem in the host-chat vision loop. `media_analysis`
extracts sampled frames at FULL source resolution — a 35-minute 4K clip yields
80 frames at 2160x3840, ~280 KB each. Reading those one at a time to satisfy
`commit_vision` costs roughly 1,100 tokens per frame; a four-clip shoot runs to
250+ frames and several hundred thousand tokens.

Tiling them into labelled grids drops that by an order of magnitude while
keeping every frame visible. Each tile is burned with its frame index, source
timestamp and the sampler's `selection_reason`, so per-frame findings can still
be reported by index against the schema.

Source-safe: reads only the analysis scratch directory and the sidecar
`visual.json`; writes only into `out_dir`. Never touches source media.

Run: `python3 scripts/contact_sheet.py <clip_analysis_dir> <out_dir>`
where `<clip_analysis_dir>` is the directory holding `visual.json` and
`frames/` (printed as `artifacts.clip_dir` by `media_analysis`).
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - guidance only, never auto-installs
    raise SystemExit(
        "Pillow is required: pip install Pillow "
        "(source-safe; used only to tile analysis scratch frames)"
    )

LABEL_HEIGHT = 26
FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _load_font(size: int):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _timestamp(seconds: Any) -> str:
    if seconds is None:
        return "?"
    minutes, secs = divmod(float(seconds), 60)
    return "%d:%05.2f" % (int(minutes), secs)


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def load_frames(clip_dir: str) -> Tuple[List[str], Dict[int, Dict[str, Any]]]:
    """Resolve frame paths + per-frame labels across all three artifact states.

    Order matters. While vision is pending, visual.json's `frame_paths` IS the
    payload `commit_vision` expects findings reported against, so its indices
    must win — analysis.json holds a larger superset (vision sample plus
    cut-boundary frames) whose numbering would not line up.

    `commit_vision` then REPLACES visual.json with the committed analysis,
    dropping `frame_paths`. After that analysis.json's `analysis_keyframes` is
    the richest surviving source, and index alignment no longer matters because
    there is no vision payload left to report against.
    """
    visual = _read_json(os.path.join(clip_dir, "visual.json"))
    paths = [p for p in visual.get("frame_paths", []) if os.path.exists(p)]
    if paths:
        meta = {
            m["frame_index"]: m for m in visual.get("frame_metadata", [])
        }
        return paths, meta

    keyframes = _read_json(os.path.join(clip_dir, "analysis.json")).get(
        "analysis_keyframes"
    )
    if keyframes:
        paths, meta = [], {}
        for position, entry in enumerate(keyframes, start=1):
            frame_path = entry.get("frame_path")
            if not frame_path or not os.path.exists(frame_path):
                continue
            paths.append(frame_path)
            meta[len(paths)] = {
                "time_seconds": entry.get("time_seconds"),
                "selection_reason": entry.get("selection_reason"),
                "frame_index": entry.get("index", position),
            }
        if paths:
            return paths, meta

    frames_dir = os.path.join(clip_dir, "frames")
    if os.path.isdir(frames_dir):
        listed = sorted(
            os.path.join(frames_dir, n)
            for n in os.listdir(frames_dir)
            if n.lower().endswith((".jpg", ".jpeg", ".png"))
        )
        return listed, {}

    return [], {}


def build_sheets(
    clip_dir: str,
    out_dir: str,
    tile_width: int = 300,
    columns: int = 6,
    rows: int = 3,
) -> Tuple[List[Tuple[str, int, int]], int]:
    """Tile every sampled frame into labelled sheets. Returns (sheets, frame_count)."""
    paths, meta = load_frames(clip_dir)
    if not paths:
        return [], 0

    per_sheet = columns * rows
    os.makedirs(out_dir, exist_ok=True)
    font = _load_font(17)

    # Derive tile height from a real frame — never assume 16:9. Vertical phone
    # footage arrives here already rotated to portrait by ffmpeg.
    with Image.open(paths[0]) as probe:
        tile_height = max(1, round(tile_width * probe.height / probe.width))

    sheets: List[Tuple[str, int, int]] = []
    for offset in range(0, len(paths), per_sheet):
        chunk = paths[offset:offset + per_sheet]
        used_rows = (len(chunk) + columns - 1) // columns
        sheet = Image.new(
            "RGB",
            (columns * tile_width, used_rows * (tile_height + LABEL_HEIGHT)),
            (18, 18, 18),
        )
        draw = ImageDraw.Draw(sheet)

        for position, frame_path in enumerate(chunk):
            index = offset + position + 1
            row, column = divmod(position, columns)
            x = column * tile_width
            y = row * (tile_height + LABEL_HEIGHT)
            with Image.open(frame_path) as frame:
                frame = frame.convert("RGB").resize(
                    (tile_width, tile_height), Image.LANCZOS
                )
                sheet.paste(frame, (x, y + LABEL_HEIGHT))
            entry = meta.get(index, {})
            reason = (entry.get("selection_reason") or "")[:14]
            draw.text(
                (x + 5, y + 4),
                "#%d  %s  %s" % (index, _timestamp(entry.get("time_seconds")), reason),
                fill=(255, 220, 90),
                font=font,
            )

        out_path = os.path.join(out_dir, "sheet_%02d.jpg" % (offset // per_sheet + 1))
        sheet.save(out_path, quality=82, optimize=True)
        sheets.append((out_path, offset + 1, offset + len(chunk)))

    return sheets, len(paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("clip_dir", help="directory containing visual.json and frames/")
    parser.add_argument("out_dir", help="where to write the contact sheets")
    parser.add_argument("--tile-width", type=int, default=300)
    parser.add_argument("--columns", type=int, default=6)
    parser.add_argument("--rows", type=int, default=3)
    args = parser.parse_args()

    sheets, frame_count = build_sheets(
        args.clip_dir, args.out_dir, args.tile_width, args.columns, args.rows
    )
    if not frame_count:
        print(
            "no sampled frames found in %s\n"
            "expected analysis.json, visual.json, or a frames/ directory "
            "(use the clip_dir printed as artifacts.clip_dir by media_analysis)"
            % args.clip_dir
        )
        return 1

    print("frames=%d sheets=%d" % (frame_count, len(sheets)))
    for path, first, last in sheets:
        print("%s  frames %d-%d" % (path, first, last))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
