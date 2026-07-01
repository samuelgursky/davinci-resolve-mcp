# DRX Value Scaling Reference

> **Generated**: 2026-01-14
> **Based on**: Analysis of 32 DRX sample files from Resolve 19

---

## Overview

DaVinci Resolve's DRX format stores parameter values with different scaling factors depending on the control type. This document maps UI values to internal DRX values.

---

## Primary Corrector (Color Wheels)

### Lift (Shadows)

| UI Value | DRX Value | Scaling |
|----------|-----------|---------|
| +0.25 | 0.500 | **2x** |
| -0.25 | -0.500 | **2x** |
| 0 (default) | 0.0 | - |

**Formula**: `DRX = UI × 2`

### Gamma (Midtones)

| UI Value | DRX Value | Scaling |
|----------|-----------|---------|
| +0.25 | 1.000 | **4x** |
| 0 (default) | 0.0 | - |

**Formula**: `DRX = UI × 4`

### Gain (Highlights)

| UI Value | DRX Value | Scaling |
|----------|-----------|---------|
| 1.50 | 1.500 | **1:1** |
| 1.0 (default) | 1.0 | - |

**Formula**: `DRX = UI` (direct mapping)

### Offset

> **Re-calibrated 2026-07 (Resolve 19 Studio, live panel readback):** the earlier ÷2500
> factor was ~100× off. A DRX offset of 0.04 moves the Primaries Offset readout by +1.00
> (panel neutral = 25.00 → 26.00). So the true factor is **÷25**, not ÷2500.

| UI Value (panel delta) | DRX Value | Scaling |
|------------------------|-----------|---------|
| +1.00 | 0.04 | **÷25** |
| 0 (default) | 0.0 | - |

**Formula**: `DRX = UI / 25`   *(UI = panel value − 25 neutral)*

---

## Saturation

### Primary Saturation

| UI Value | DRX Value | Scaling |
|----------|-----------|---------|
| 0% | 0.0 | **÷100** |
| 50% | 0.5 | **÷100** |
| 100% (default) | 1.0 | **÷100** |
| 150% | 1.5 | **÷100** |
| 200% | 2.0 | **÷100** |

**Formula**: `DRX = UI / 100`

### Color Boost

| UI Value | DRX Value | Scaling |
|----------|-----------|---------|
| 50 | 50.0 | **1:1** |
| 100 | 100.0 | **1:1** |
| 0 (default) | 0.0 | - |

**Formula**: `DRX = UI` (direct mapping)

---

## Temperature & Tint

### Temperature

| UI Value | DRX Value | Scaling |
|----------|-----------|---------|
| +2000K | 2000.0 | **1:1** |
| -2000K | -2000.0 | **1:1** |
| 0 (default) | 0.0 | - |

**Formula**: `DRX = UI` (direct Kelvin offset)

### Tint

| UI Value | DRX Value | Scaling |
|----------|-----------|---------|
| +50 | 50.0 | **1:1** |
| -50 | -50.0 | **1:1** |
| 0 (default) | 0.0 | - |

**Formula**: `DRX = UI` (direct mapping)

### Midtone Detail

| UI Value | DRX Value | Scaling |
|----------|-----------|---------|
| +50 | 50.0 | **1:1** |
| -50 | -50.0 | **1:1** |
| 0 (default) | 0.0 | - |

**Formula**: `DRX = UI` (direct mapping)

---

## Contrast

### Primary Contrast

> **Re-verified 2026-07 (live panel readback):** the generator takes contrast on the
> **1.0 scale directly** — input `1.2` displays as `1.200` in the Primaries panel (which
> shows contrast as `1.000`-neutral, NOT `100%`). So for the codec's input path contrast is
> **1:1** (no ÷100). The ÷100 below only applies if you're starting from a percentage UI
> (150% form); when passing the panel's 1.0-scale number, use it directly.

| Input to codec | DRX / panel | Scaling |
|----------------|-------------|---------|
| 1.2 | 1.200 | **1:1** (panel 1.0-scale) |
| 1.0 (default) | 1.0 | — |
| (150% percentage form) | 1.5 | ÷100 |

**Formula (codec input)**: `DRX = UI` (1.0-scale, direct)

---

## Log Wheels

Log wheel values are stored as direct float offsets in RGB.

### Shadow/Midtone/Highlight Wheels

| Direction | R | G | B |
|-----------|---|---|---|
| Warm (orange) | +0.53 | -0.11 | -0.47 |
| Cool (blue) | -0.38 | +0.05 | +0.63 |
| Green | -0.35 | +0.67 | -0.03 |
| Magenta | +0.52 | -0.35 | +0.15 |

### Master (Exposure)

| UI Value | R | G | B |
|----------|---|---|---|
| +0.026 | +0.026 | +0.026 | +0.026 |
| -0.026 | -0.026 | -0.026 | -0.026 |

Equal RGB values = neutral exposure adjustment.

---

## Parameter ID Reference

| Control | Parameter ID | Hex |
|---------|--------------|-----|
| Lift R/G/B/Master | 100663320-100663323 | 0x6000018-0x600001b |
| Gamma R/G/B/Master | 100663330-100663333 | 0x6000022-0x6000025 |
| Gain R/G/B/Master | 100663325-100663328 | 0x600001d-0x6000020 |
| Offset R/G/B | 100663421-100663423 | 0x600007d-0x600007f |
| Saturation | 100663301 | 0x6000005 |
| Temperature | 2248147221 | 0x86000115 |
| Tint | 2248147222 | 0x86000116 |
| Midtone Detail | 2248147219 | 0x86000113 |
| Color Boost | 2248147218 | 0x86000112 |
| Contrast (Log) | 2248147137 | 0x860000c1 |
| Log Shadow R/G/B | 2248147138-2248147140 | 0x860000c2-0x860000c4 |
| Log Midtone R/G/B | 2248147141-2248147143 | 0x860000c5-0x860000c7 |
| Log Highlight R/G/B | 2248147144-2248147146 | 0x860000c8-0x860000ca |

---

## Quick Conversion Functions

```javascript
// UI to DRX — verified live vs Resolve 19 panel (2026-07). These are what the codec's
// space:'ui' path applies (lift/gamma/gain/offset); the rest the encoder handles internally.
const uiToDrx = {
  lift: (ui) => ui * 2,
  gamma: (ui) => ui * 4,
  gain: (ui) => ui,
  offset: (ui) => ui / 25,      // re-calibrated 2026-07 (was /2500); ui = delta from neutral
  saturation: (ui) => ui / 50,  // corrected 2026-07 (was /100); neutral 50, e.g. 52 -> 1.04
  contrast: (ui) => ui,         // corrected 2026-07 (was /100); codec takes 1.0-scale directly
  colorBoost: (ui) => ui,
  temperature: (ui) => ui,
  tint: (ui) => ui,
  midtoneDetail: (ui) => ui,
};

// DRX to UI
const drxToUi = {
  lift: (drx) => drx / 2,
  gamma: (drx) => drx / 4,
  gain: (drx) => drx,
  offset: (drx) => drx * 25,    // re-calibrated 2026-07 (was *2500)
  saturation: (drx) => drx * 50, // corrected 2026-07 (was *100)
  contrast: (drx) => drx,        // corrected 2026-07 (was *100)
  colorBoost: (drx) => drx,
  temperature: (drx) => drx,
  tint: (drx) => drx,
  midtoneDetail: (drx) => drx,
};
```

---

## Codec Input Notes (verified 2026-07)

- **`space` flag (drx.generate / merge).** `space:'ui'` (default) takes Resolve panel numbers
  and applies the factors above; `space:'drx'` takes raw DRX-internal values. Only
  lift/gamma/gain/offset/saturation differ between the two; everything else is 1:1 in both.
- **Offset in `space:'ui'` is a DELTA from neutral (0 = no change), not the panel's absolute
  number.** The panel displays offset on a 25-neutral base (a display base that can vary), but
  the control's true neutral is DRX 0, so a 0-based delta maps cleanly and portably. Example:
  `offset.g: -1` (ui) → DRX -0.04 → panel 25.00 → 24.00.
- **Direct-float (1:1) controls** — pass raw, no factor: temperature, tint, contrast (1.0-scale),
  pivot, midtoneDetail, colorBoost, log wheels (shadow/mid/highlight R/G/B), soft clips
  (high/low + softness), HDR black offset, RGB mixer, contrast low range. All round-trip-verified.

## Affine-mapped controls (RESOLVED 2026-07-01 — live panel readback)

Both former "known issues" turned out to be Resolve-faithful encoder transforms, not bugs.
The gap was `space:'drx'` compensation, now fixed in `normalizeGradeParams`:

- **`hueRotate`** — stored = `(UI − 50) / 50` (UI 0–100, neutral 50). Panel-confirmed:
  generated `hueRotate: 60` (stored 0.2) reads **Hue 60.00** in the Primaries panel.
  `space:'ui'` takes the panel number; `space:'drx'` takes the raw stored float
  (normalizer inverts: UI = 50 + 50 × raw).
- **`contrastHighRange`** — **Resolve itself stores `1 − UI`** (default UI 0.550 → stored
  0.45). Panel-confirmed: generated `contrastHighRange: 0.70` (stored 0.30) reads
  **↑ Rng 0.700** in the Log palette, alongside the 1:1 `contrastLowRange` (0.28 → 0.280).
  The asymmetry is native semantics, not an encoder bug. `space:'drx'` pre-inverts so raw
  stored values round-trip.

Structural (point/coordinate/blob) controls are covered by the companion coverage ledger,
`CALIBRATION-STATUS.md` (Phase 2: windows, qualifiers, HDR zones, HSL curves).

---

*Document Version: 1.2 (2026-07 live-calibration passes 1–2)*
