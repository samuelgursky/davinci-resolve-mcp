#!/usr/bin/env python3
"""Regenerate the control-panel doc screenshots from a live panel.

Drives the panel's hash deep links headlessly and writes 1280x800 captures
into docs/images/control-panel/. Run whenever the panel UI changes visibly.

Setup:
  1. venv/bin/pip install playwright  (chromium is fetched on first run if absent)
  2. Start the panel bound to a project that HAS an analyzed clip, e.g.:
       venv/bin/python -m src.control_panel --no-open
     (Bind to a rich analysis context if the live Resolve project is empty.)
  3. venv/bin/python scripts/regen_panel_screenshots.py [--clip-id <id>] [--port 8765]

The clip id defaults to the first analyzed clip reported by /api/clips.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request

OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "docs" / "images" / "control-panel"


def first_clip_id(base: str) -> str:
    with urllib.request.urlopen(f"{base}/api/clips", timeout=10) as resp:
        payload = json.load(resp)
    clips = payload.get("clips") or []
    if not clips:
        sys.exit("No analyzed clips in the panel's project — bind the panel to a project with analysis data first.")
    return clips[0]["clip_id"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--clip-id", default=None)
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright not installed: venv/bin/pip install playwright")

    clip = args.clip_id or first_clip_id(base)
    shots = [
        ("#overview", "01-overview.png", 3000),
        ("#analysis/review", "02-review-bin-grid.png", 3500),
        (f"#analysis/review/clip/{clip}", "03-clip-detail.png", 4000),
        (f"#analysis/review/clip/{clip}/transcript", "04-transcript.png", 4000),
        (f"#analysis/review/clip/{clip}/shot/3", "05-shot-detail.png", 4500),
        ("#analysis/media", "06-inventory.png", 3500),
        ("#diagnostics/resolve", "07-diagnostics-resolve.png", 3000),
        ("#preferences/analysis", "08-preferences-analysis.png", 3000),
        ("#aiconsole", "09-ai-console.png", 3000),
        ("#analysis/review/history", "10-history.png", 3500),
        ("#analysis/review/plans", "11-edit-plans.png", 3500),
    ]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        for hash_, name, wait in shots:
            page.goto(f"{base}/{hash_}")
            page.wait_for_timeout(wait)
            page.screenshot(path=str(OUT_DIR / name))
            print("shot:", name)
        browser.close()
    print(f"done — {len(shots)} screenshots in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
