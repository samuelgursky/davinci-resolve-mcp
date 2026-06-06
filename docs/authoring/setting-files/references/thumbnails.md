# Thumbnail Files

Each `.setting` (or `.alut3`) ships with a bundle of PNGs named after the effect file. They are not embedded — they live as sibling files in the same folder. Resolve indexes them at launch and uses them for the tiles in the Effects Library. If your effect is `My Cool Thing.setting`, every thumbnail starts with `My Cool Thing.` followed by a suffix that identifies the UI slot. Spaces in the base name are fine — Resolve matches on exact prefix.

---

## Suffix Catalog

Every distinct suffix found in the stock library, with confirmed dimensions and purpose.

| Suffix | Dimensions (1×) | Dimensions (`@2x`) | UI slot |
|--------|-----------------|---------------------|---------|
| `.large.png` | 128 × 128 | 256 × 256 | Square tile in grid/icon view |
| `.large@2x.png` | — | 256 × 256 | HiDPI version of `.large.png` |
| `.small.png` | 30 × 30 | 60 × 60 | Small icon in list/compact view |
| `.small@2x.png` | — | 60 × 60 | HiDPI version of `.small.png` |
| `.small.active.png` | 30 × 30 | 60 × 60 | Button pressed/active state |
| `.small.active@2x.png` | — | 60 × 60 | HiDPI active state |
| `.small.hover.png` | 30 × 30 | 60 × 60 | Mouse-hover state |
| `.small.hover@2x.png` | — | 60 × 60 | HiDPI hover state |
| `.small.push.png` | 30 × 30 | 60 × 60 | Mouse-down state |
| `.small.push@2x.png` | — | 60 × 60 | HiDPI push state |
| `.wide.png` | 52 × 29 | 104 × 58 | Wide tile (transitions, titles) |
| `.wide@2x.png` | — | 104 × 58 | HiDPI wide tile |
| `.wide.active.png` | 52 × 29 | 52 × 29 | Active state for wide tile |
| `.wide.active@2x.png` | — | 104 × 58 | HiDPI wide active state |
| `.wide.hover.png` | 52 × 29 | 52 × 29 | Hover state for wide tile |
| `.wide.hover@2x.png` | — | 104 × 58 | HiDPI wide hover state |
| `.wide.push.png` | 52 × 29 | 52 × 29 | Push state for wide tile |
| `.wide.push@2x.png` | — | 104 × 58 | HiDPI wide push state |

The full 12-suffix set (`.large`, `.large@2x`, `.small`, `.small@2x`, `.small.active`, `.small.active@2x`, `.small.hover`, `.small.hover@2x`, `.small.push`, `.small.push@2x`, `.wide`, `.wide@2x`) is the standard complement for most categories. Categories that omit `.large.*` use only the wide/small subsets.

---

## Per-Category Reference

All 14 stock categories verified against the `Core Davinci Effects/` library (2,897 PNG files total).

**Suffix set key:**
- **Full-12** = `.large`, `.large@2x`, `.small`, `.small@2x`, `.small.active`, `.small.active@2x`, `.small.hover`, `.small.hover@2x`, `.small.push`, `.small.push@2x`, `.wide`, `.wide@2x`
- **Wide-only** = `.wide`, `.wide@2x` (no large or small variants)
- **Partial** = some effects have the full set, some have a smaller subset — see notes

| # | Category | Baseline thumbnail set | Notes |
|---|----------|----------------------|-------|
| 1 | **Edit / Effects** | Full-12 | 22 of 23 effects ship the full-12. Both `_default.png` and `_default.wide.png` fallbacks present. |
| 2 | **Edit / Transitions** | Partial | 30 of 53 effects ship full-12 including `.large.*`. All 53 have `.wide` + `.wide@2x`. Most have `.small.*` button states. `.wide.active@2x`, `.wide.hover@2x`, `.wide.push@2x` exist but only on a single effect. |
| 3 | **Edit / Titles** | Partial | Baseline is wide-only (`.wide`, `.wide@2x`) across 90 of 97 titles. 18 titles additionally ship the full-12 (`.large.*` + `.small.*` button states). Do not assume titles are always wide-only. |
| 4 | **Edit / Generators** | Partial | Baseline is full-12. 14 of 16 effects have `.large.*`. All have `.wide.*`. Not all have `.small.*` button states. |
| 5 | **Fusion / Tools** | Full-12 | All Tools effects ship the complete 12-suffix set. |
| 6 | **Fusion / Backgrounds** | Full-12 | All Backgrounds effects ship the complete 12-suffix set. |
| 7 | **Fusion / Generators** | Full-12 | All Fusion Generators ship the complete 12-suffix set. |
| 8 | **Fusion / Particles** | Partial | Some effects ship full-12; some ship only `.large.*` + `.wide.*` without `.small.*` button states. |
| 9 | **Fusion / Shaders** | Full-12 | All Shaders ship the complete 12-suffix set. |
| 10 | **Fusion / Motion Graphics** | Full-12 | All Motion Graphics ship the complete 12-suffix set. |
| 11 | **Fusion / Lens Flares** | Full-12 | All Lens Flares ship the complete 12-suffix set. |
| 12 | **Fusion / Looks** | Mixed | Only `.setting`-based effects get thumbnails; `.alut3` files do not get per-file thumbnails. The one `.setting` effect (`Posterize`) ships the full-12. The 10 `.alut3` files (e.g. `Abstract.alut3`, `Film chrome.alut3`) carry no per-effect thumbnail — only `_default.png` and `_default@2x.png` serve as fallbacks for the whole category. |
| 13 | **Fusion / Styled Text** | Wide-only | All Styled Text effects use only `.wide` + `.wide@2x`. No `.large.*` or `.small.*` variants. |
| 14 | **Fusion / How To** | None (defaults only) | Zero per-effect thumbnails in this category. All 12 How To `.setting` files share only the two `_default` fallbacks (`_default.png`, `_default@2x.png`). Do not try to add `.large.png` thumbnails here — the UI does not render them for How To entries. |

**Minimum viable ship:**
- For any category that uses `.large.*`: provide at least `.large.png` (128×128). Resolve handles the rest with fallbacks.
- For titles and transitions: provide at least `.wide.png` (52×29).
- For Styled Text: provide `.wide.png` + `.wide@2x.png`.
- For Looks `.alut3` files: no per-effect thumbnail is possible; the category relies entirely on `_default.*`.

---

## `_default.*` Fallbacks

Every stock Edit and Fusion folder ships a small set of fallback files that Resolve displays when no per-effect thumbnail exists.

| File | Dimensions | Role |
|------|-----------|------|
| `_default.png` | 52 × 29 | Fallback for the wide slot. Despite the name suggesting a "default large", this file is actually wide-sized — do not use it as a large-thumbnail fallback. |
| `_default@2x.png` | 256 × 256 | HiDPI fallback; note the dimension mismatch — `_default.png` is wide-sized (52×29) while `_default@2x.png` is large-sized (256×256). The two files are not matched scales. |
| `_default.wide.png` | 52 × 29 | Explicit wide-slot fallback, present in Edit category folders alongside `_default.png`. |
| `_default.wide@2x.png` | 104 × 58 | HiDPI version of the wide-slot fallback. |

The `_default.wide.*` pair is distinct from `_default.*` — both exist side-by-side in Edit folders. When building new categories, supply your own `_default.png` and `_default@2x.png` rather than relying on Resolve's built-in fallback graphic.

---

## Creating Thumbnails

1. Apply the effect to a clip in Resolve.
2. Grab a frame (File → Export → Still, or viewer right-click → Grab Still).
3. Crop to the target dimensions with any image tool. Alpha PNGs are supported.
4. Name the crops per the suffix rules above and drop next to the `.setting` file.

For button states (`.active`, `.hover`, `.push`), start from the base `.small.png` and brighten / darken / tint by ~10% — this matches the stock library's approach.

---

## Quirks — Stock Anomalies (Do Not Replicate)

These are bugs or accidents in the stock library. They are documented here so authors recognize them as anomalies, not as valid naming patterns.

- **Double-dot typo:** `Stretch Region.small.@2x.png` and `Watermark.small.@2x.png` in `Edit/Effects/` have an extra dot (`.small.@2x.png` instead of `.small@2x.png`). Resolve ignores these files; the correct form is `.small@2x.png` with no dot before `@2x`.

- **Bare-suffix transition:** `Rotate 90.png` and `Rotate 90@2x.png` in `Edit/Transitions/` have no slot suffix at all — just the base name with `.png`. This appears to be a naming error; use an explicit slot suffix on every thumbnail.

- **Compound Slide name:** The transition `Slide.push` has its base name parsed as `Slide.push`, producing filenames like `Slide.push.small.push.png` and `Slide.push.small.push@2x.png`. This is a side effect of the base name containing a dot. Avoid dots in effect base names.

None of these patterns are understood by Resolve as intentional slots — authors should not replicate them.
