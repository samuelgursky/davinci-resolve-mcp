# DRX Parameter Calibration Status

> **Verified**: 2026-07 (Phase 1: scalar scaling) + 2026-07-01 (Phase 2: structural
> write fidelity), live against DaVinci Resolve 19 Studio.
> Companion to `DRX-VALUE-SCALING.md` (the factor reference). This file is the **coverage
> ledger** — which parameters are confirmed, how, and what's still broken/unverified.

## Methodology

Each parameter is validated two ways:

1. **Round-trip (offline, deterministic):** generate a `.drx` with a known value via the
   codec, `parse` it back, and locate the value in the decoded node. Reveals the encoder's
   true factor (1:1, ×2, ÷50, …) and any inversion/loss. Driven by
   `test/drx-scaling-matrix.test.mjs` + `test/drx-ui-space-scaling.test.mjs`.
2. **Live panel/render readback (ground truth):** apply the `.drx` to a clip and either read
   the value Resolve displays in the Primaries panel, or measure the rendered frame. Confirms
   the codec's units actually match what Resolve does (the round-trip alone can't prove that —
   see the offset case, where the code range said ±1 but the panel uses a 25-neutral base).

The `space` flag unifies input units: **`space:'ui'` (default)** = Resolve panel numbers,
**`space:'drx'`** = raw internal values. Only the factored controls differ between the two.

## Coverage ledger

| Parameter | `ui`→DRX factor | Status | Verified |
|-----------|-----------------|--------|----------|
| lift (r/g/b/master) | ×2 | ✅ | panel (0.10→0.05) + round-trip |
| gamma (r/g/b/master) | ×4 | ✅ | panel (0.20→0.05) + round-trip |
| gain (r/g/b/master) | ×1 | ✅ | panel (1.10→1.10) + round-trip |
| offset (r/g/b) | ÷25, **delta from neutral** | ✅ | panel (0.04→+1.00) + round-trip |
| saturation | ÷50 (0–100, 50=neutral) | ✅ | panel (55) + round-trip |
| contrast | 1:1 (1.0-scale) | ✅ | panel (1.2→1.200) + round-trip |
| pivot | 1:1 | ✅ | panel (0.5→0.500) + round-trip |
| temperature | 1:1 | ✅ | panel (2000) |
| tint | 1:1 | ✅ | panel (20) |
| midtoneDetail | 1:1 | ✅ | panel (30) |
| colorBoost | 1:1 | ✅ | panel (25) |
| softClipHigh / softClipLow | 1:1 | ✅ | round-trip |
| softClipHighSoft / softClipLowSoft | ÷50 (0–100, like saturation) | ✅ (fixed 2026-07) | round-trip |
| contrastLowRange | 1:1 | ✅ | round-trip |
| blackOffset (HDR) | 1:1 | ✅ | round-trip |
| logShadow / logMid / logHigh (r/g/b) | 1:1 | ✅ | round-trip; logShadow render-confirmed |
| rgbMixer (9 coeffs) | 1:1 | ✅ | round-trip |
| highlights / shadows (sliders) | 1:1 | ✅ | round-trip (regression-locked 2026-07-02) |
| lumMixSlider | 1:1 | ✅ | round-trip (was untested — locked 2026-07-02) |
| customCurves.y (interior points) | fidelity 1:1 | ✅ | round-trip (points `{x,y}`, not `[x,y]`) |
| hueRotate | affine: (UI−50)/50 | ✅ (resolved 2026-07-01) | panel (60→Hue 60.00) + round-trip |
| contrastHighRange | affine: 1−UI (Resolve-native) | ✅ (resolved 2026-07-01) | panel (0.70→↑Rng 0.700) + round-trip |

**28 scalar/wheel/RGB/affine controls + custom-curve points confirmed; 0 broken.**

## Phase 2 — Structural / write-fidelity audit (2026-07-01)

Methodology: offline generate→parse round-trip **plus** live apply (`safe_apply_drx` on a
scratch clip) with Resolve **panel readback** of the resulting control values, and wire-level
comparison against the live-captured fixtures in `test/fixtures/`. Regression tests:
`test/drx-structural-write-fidelity.test.mjs` (suite) +
`vendor/drx-codec/__tests__/` (codec round-trips, 94 tests).

| Control | Write status | Verified |
|---------|--------------|----------|
| Power window — circle transform | ✅ **fixed + live-confirmed** | Window palette reads Size 60/Pan 35/Tilt 75/Soft 5 exact for those UI inputs |
| Power window — linear softness mask | ✅ fixed (ct3, UI×16) | round-trip; stored == linear-window-softness fixture values |
| Power window — gradient | ✅ fixed (ct65554) | round-trip; stored == gradient-window fixture values exactly |
| Power window — polygon/curve shapes | ❌ no write path (vertex ring) | decode-only (`polygonVertices`) |
| HSL qualifier (12 ranges + modes) | ✅ **live-confirmed** | Qualifier palette reads Center 33.1/Width 22/Soft 11/Sat 12–88/Lum 20–80 exact |
| RGB qualifier | ✅ **wired + live-confirmed** (2026-07-02) | palette auto-switches to RGB mode; R 12/88 (soft 5/7), G 22/78, B 32/68 exact |
| Luma qualifier | ✅ wired (mode varint {F2:4}) | round-trip; same mechanism as the live-confirmed RGB mode switch |
| HDR zones (multi-zone) | ✅ **fixed + live-confirmed** | HDR palette reads Dark +0.80 AND Highlight −0.80 from one generated DRX |
| HSL curve — sat-axis (satVsSat, lumVsSat*) | ✅ live-confirmed w/ `hslCurveMeta` override | Sat vs Sat panel renders Input 0.25/Output 1.40 exact |
| HSL curve — hue-axis (hueVsHue/hueVsSat/hueVsLum) | ✅ **single- AND multi-band write LIVE-VERIFIED** (2026-07-02) | rig: single band at 1/3 + 0.6 exact; 2-band (1/3 boost + 2/3 cut) renders exact; edge-on-band-slot geometry guarded (raw passthrough); see "Hue-axis canonical structure" |
| HSL curve — lum-axis (lumVsSat) | ✅ **live-verified** (2026-07-02) | rig: naive points + meta 2 render (lum/sat-axis curves are polyline-tolerant; only hue-axis needs the cage) |
| Custom curves (YRGB) | ✅ | Phase 1 (fidelity 1:1, `{x,y}` objects) |
| Matte finesse (12 params) | ✅ (UI÷100, ct9) | codec round-trip; scale live-confirmed decode-side |
| LUT refs | ✅ | `lut_apply` body patch; vendored round-trip |
| Color Warper (pin list) | ◐ **write path built (R21 wire format); R19 does NOT accept** (2026-07-02) | round-trip exact + fixture-identical params; live 19.1.3 apply registers no tool → version-gated, verify on R21 |
| ColorSlice global params | ✅ **write path built + live-confirmed** (2026-07-02) | ColorSlice palette reads Den 0.30/Sat 1.40/Hue 0.25 exact; GetToolsInNode = ["ColorSlice"]; hue stored NEGATED |

*lumVsSat assumed to follow satVsSat (sat-axis family); only satVsSat was live-rendered.

### Encoder fixes shipped in Phase 2
1. **Power-window transform scales** — the generator wrote placeholder conventions (rotate
   direct-degrees, pan ×8.2 …) that the registry's [-1,1] ranges then clamped to garbage.
   Now writes the true live-calibrated scales (rotate −UI°/180, size 1+(UI−50)×0.08, aspect
   (50−UI)/50, pan/tilt (UI−50)/50×4096, soft UI×16) and the registry window ranges carry the
   real DRX spans. `extract-power-window.js` inverses updated to match.
2. **Window shape model** — `0x88500008` is a **constant varint `{F2:2}`** in every live
   fixture (circle/linear/gradient/polygon/curve); shape is expressed by *which corrector
   blocks exist*. Generator now writes it wire-faithfully (was float32) and routes linear
   softness to ct3 and gradient params to ct65554 (both were mis-homed in ct4).
3. **HDR multi-zone loss** — all zones now share ONE `ZONE_ADJUSTMENTS` (0x86000305) param
   as repeated F16.F1[] sub-messages (matches the hdr-zones-grid fixture). Previously each
   zone got its own param/block and only the last survived.
4. **Qualifier mode flags** — `0x0830006F` (=4) and `0x88300001` (=mode: HSL 0, RGB 2,
   luma 4, 3D 6) are varint envelopes; were written as float32.
5. **HSL curve per-curve meta** — live fixtures carry per-curve values (hueVsHue 0,
   hueVsSat 2, satVsSat 2), not the always-6 the generator wrote. Exposed as
   `gradeParams.hslCurveMeta = {satVsSat: 2}` (semantics not fully decoded).
6. **Vestigial satVsSat registry ranges removed** — the 0x08F000xx [0,1] guesses clamped
   real gradient-window writes (they're the gradient's ids; the real Sat-vs-Sat curve is an
   hslCurves spline).
7. **RGB/luma qualifier wired into `generate`** (2026-07-02) — `gradeParams.rgbQualifier` /
   `lumaQualifier` (one qualifier per node; precedence HSL > RGB > luma). RGB live-exact.
8. **ColorSlice global write path** (2026-07-02) — `gradeParams.colorSlice`
   {density, densityDepth, sat, satBalance, satDepth, hue}; identity scale, hue negated
   (drx space pre-negates). Live-exact. Per-vector grid (0x86000606) stays decode-only.
9. **Color Warper pin-list write path** (2026-07-02) — `gradeParams.colorWarper.pins[]`
   in the R21 wire format (configA/B varints, F27.F1[] pins). Round-trips exactly;
   version-gated on R19 (see table).

## Resolved former "known issues" (both were NOT encoder bugs)

### 1. `hueRotate` — encoder correct; decode/space gap fixed
Stored = `(UI − 50)/50`. **Live-confirmed 2026-07-01**: generated `hueRotate: 60` (stored
0.2) → Primaries panel reads **Hue 60.00**. `space:'drx'` now inverts (UI = 50 + 50×raw) so
raw values round-trip. Parse still surfaces the raw stored float (consistent with all
decoded values being DRX-internal).

### 2. `contrastHighRange` — the inversion is Resolve-native semantics
**Live-confirmed 2026-07-01**: generated `contrastHighRange: 0.70` (stored 0.30) → Log
palette reads **↑ Rng 0.700**, with `contrastLowRange` 0.28 → **↓ Rng 0.280** (1:1). Resolve
itself stores high range as `1 − UI` (default 0.550 → 0.45). The encoder was right; the
Phase-1 "encoder bug" hypothesis is disproven. `space:'drx'` now pre-inverts so raw stored
values round-trip. The old bug-locking test was replaced with correct assertions.

### Hue-axis canonical structure (decoded + WRITE VERIFIED 2026-07-02)
Captured live on R19.1.3 by authoring a Hue-vs-Sat green-band boost (Sat 1.50) and grabbing
the grade via the gallery (captured canonical reference retained in the internal program ledger).
The spline is a **STRICT bezier control cage, not a polyline** — live-bisected on a
throwaway rig (DRX_CALIB_19B, Local Database):
- meta `0x860000B8` = varint `{F2:2}`, commonFlag `{F2:2}`, spline `0x86000401`;
- y-scale = `1 − Sat/2` (bump y 0.25 ⇒ Sat 1.5) — same as the sat-axis curves;
- **single-band cage = 19 points spanning [x−1, x+1]** (list starts/ends on the wrapped
  bump center): neutral secondary anchors (1/6, 1/2, 5/6), enter/exit handle PAIRS at
  x±1/12, tangent slope samples at x±0.04623 (y = 0.5 + 0.72264·(y−0.5)) present only in
  the wrap halves, and segment-end anchor DOUBLES.
- Bisect results: exact pattern → **renders correct** (verified at two band positions and
  three values; panel readouts exact). Fewer points (no tangents OR no doubles) → tool
  registers but **renders flat**. Same count, plain points → **renders garbage**.
  Malformed wrap lists → **crashed Resolve 19.1.3 twice** (reproducible risk class).
- **Multi-band (live-verified 2026-07-02):** approximate midpoint TANGENT VALUES render
  fine — only the slots are load-bearing. Between-bump gaps use the slope-through-anchor
  form (inner edge → tangent → anchor(s) → tangent → inner edge), NOT vertical pairs
  (pair-only gaps render flat). Down-wrap = last bump's descending half −1; up-wrap =
  first bump's ascending half +1; 0-anchor doubled.
- **Edge-on-slot pathology:** a bump EDGE (x±1/12) landing exactly on a band slot (k/6)
  renders flat (e.g. center 0.25 → left edge = 1/6). `canonicalizeHueAxisPoints`
  (server/tools/drx.mjs) guards this: such geometry passes through raw. Band-centered
  bumps (k/6) are always safe.
- ⚠ Never iterate hue-axis structures on a production project (crash class above); use a
  throwaway rig (DRX_CALIB_19B in the Local Database is set up for this).

## Coverage completeness statement (2026-07-02 exhaustiveness audit)

**Write surface: every key the generator accepts is either calibrated + regression-locked
or explicitly documented as unsupported.** The full writable set (45 keys) audits as:
- Scalars/wheels/affine — ALL in `test/drx-scaling-matrix.test.mjs` (every wheel channel ×
  magnitudes × both spaces; every 1:1 scalar incl. temperature/tint/midtoneDetail/
  colorBoost/highlights/shadows/lumMixSlider/log wheels/full RGB-mixer matrix).
- Structural — ALL in `test/drx-structural-write-fidelity.test.mjs` + vendored round-trips
  (windows incl. vertex shapes, qualifiers all modes, HDR zones, custom + HSL curves,
  ColorSlice, Color Warper, matte finesse, LUT refs).
- Documented-unsupported raw escape hatches (semantics never confirmed): `hue` (ct4
  param-id-keyed), `lumMix` (ct5 param-id-keyed — NOTE its registry ids are actually the
  ct6 polygon geometry ids), `satVsSat` (ct3 vestigial — the real curve is an HSL spline).
  These pass raw values through; do not rely on them.

**3D-qualifier selection volume BLOB — decoded 2026-07-02** (was the last offline-reachable
opaque blob, previously "named, not deep-decoded"): value envelope `{F5: buffer}` =
9 × uint64 BE header (field 8 = sample count; fields 0–7 semantics unconfirmed) +
count × 3 float32 LE `(x, y, radius)` — the keyer's sampled chroma-plane stroke path.
Lifted as `node.params.qualifier3d`; locked in `test/qualifier-3d-calibration.test.mjs`.
The sibling "extras" (0x8830002E/30/32) resolve to simple varints/messages — no blob RE
needed.

**Decode surface: native grade tools = functionally 100%** per the June 2026 sweeps
(internal program ledger) **plus the 2026-07-02 palette sweep**:
the 5-corrector kitchen-sink grade decodes with zero unknown_/NaN, keyframes fully
cracked, no open native rows. Known holes:
- **OFX / ResolveFX plugin universe** — DEFERRED by scope decision (Layer 5); decoded
  raw/unscaled, flagged by `valueFidelity`. **SCOPE COLLAPSED 2026-07-03 by a real-project
  usage inventory** (9 projects, 4,698 graded clips): only NINE plugins appear in real work,
  four with volume — colorspacetransformv2 (1663 clips), filmgrain (1527, pairs w/ the
  CineGrain Kodak LUTs), Neat Video (833, 3rd-party opaque), acestransform (158). A
  targeted capture-sweep of filmgrain + the CST/ACES enums would cover ~95% of real usage;
  Neat Video stays opaque pass-through by design. **DECODE+WRITE LANDED 2026-07-03:**
  OFX params are SELF-DESCRIBING on the wire (name string + float64/string; enums =
  label strings) — the parser now lifts `node.ofxTools` (5,977 instances decoded by name
  across 4 real projects) and the generator accepts `gradeParams.ofx = {pluginId,
  params}` (full-envelope round-trip test). ALSO FIXED: body magic **0x80 = STORED/
  uncompressed** (~10% of real-project grades were REFUSED outright before; now parse).
  `test/ofx-parse-lift.test.mjs`. **FULL-UNIVERSE REGISTRY 2026-07-03**
  (`resolvefx-registry.json` + `lookupResolveFX()`): all **105** ResolveFX plugin ids for
  19.1.3 extracted EXACTLY from the app binary; param/enum candidates from the
  factory-block string scan (81 good windows / 24 flagged low); `paramsObserved` overlay
  = EXACT names decoded from real grades (7 plugins). Decode never needs the registry
  (wire is self-describing) — it assists authoring + enum lookup.
  `test/resolvefx-registry.test.mjs`. **WRITE LIVE-CONFIRMED UNIVERSAL 2026-07-03**
  (_mcp_ofx_live2 render): a written filmgrain node ENGAGES (flat patch → full grain
  spread) and a CST node written with the SAME entry ids engages too. TWO write bugs
  found+fixed en route: (1) the old "Film Grain toolId 0xC0000087 + offsets" scheme was
  a MISREAD — entry ids are UNIVERSAL constants (0x49 pluginId / 0x5E context / 0x63
  enable / 0x87 container / 0xD2 end) and the misplaced ids HARD-CRASHED Resolve on
  deserialize (incl. on startup restore of a saved poisoned project — quarantine the
  project to recover); (2) container F3 is the OFX CONTEXT name ("OfxImageEffectContextFilter"),
  not an instance id — a synthesized unique string leaves the plugin silently
  un-instantiated. There is NO per-plugin tool id: Resolve keys on the pluginId STRING →
  the write path covers the full plugin universe. Float values are OFX-native (float64
  = the plugin's own units, per the OFX param model; real-grade values read in panel
  units). `test/ofx-parse-lift.test.mjs` pins container structure.
  **FULL-UNIVERSE RANGE SWEEP 2026-07-03** (3,816 rendered probes, 88 plugins ×
  636 params, ~65 min autonomous): per-param dose-response verdicts in
  `resolvefx-registry.json` `rangesMeasured` — 33 responsive params w/ curves+ceilings,
  **44 plugins render-confirmed engaging from written DRXs** (`defaultOutputDiffers`),
  318 flat-engaged / 285 flat-identity. **V2 SWEEP (chart media + 0-100 ladders,
  1,508 probes) 2026-07-03**: +2 responsive (directionalblur.BlurAngle,
  jpegdamage.FrequencyScale); 375 params flat under BOTH probes ⇒ remaining flats are
  candidate-NAME noise / section-gated params — future coverage is capture-driven (true
  names arrive via ofxTools decode of real grades; rerun the sweep rig per name). ALSO
  2026-07-03: **HDR ZONE_DEFINITIONS WRITE built + live-verified** (panel showed
  authored −2.20/0.40; Resolve re-serialized identically); **framesFlag ×2 two-point
  confirmed** (panel 4 → wire 8); **panel defaults recorded** for the 7 used BMD
  plugins (registry panelDefaults; NB enum vocabularies are PER-PLUGIN — write enum
  strings only from that plugin's observed/enum pool).
- **Footage-blocked blobs** — external mattes, AI masks, and the stereoscopic-3D palette
  (each needs real footage / stereo media in a rig to capture). **Tracker data DECODED
  2026-07-03** (synthetic known-motion capture, 12 px/frame): keyframed ct3 window stream of
  protobuf records `0A len { F1 frame×2 varint, F2 { F1 param-id, F2 { 0x52: nine tagged
  f32 } } }` — the nine floats are a row-major **3×3 transform vs the reference frame**
  (pan=f3/tx, tilt=f6/ty, rotation/zoom in the 2×2, perspective row ≈ [0,0,1]); validated
  slope 11.96 px/frame vs 12.0 ground truth, final tx == panel readout. Fixture
  `test/fixtures/tracker-linear-motion.drx` + `test/tracker-data-blob.test.mjs`. Decode-level
  only — no write path.

**Blur / Key / Motion Effects palettes — hole CLOSED, decode + WRITE (2026-07-02).**
Fixture `test/fixtures/blur-key-motionfx.drx` + `test/blur-key-motionfx-calibration.test.mjs`
(decode, zero unknown_ params); write paths in the generator
(`gradeParams.blur` / `key` / `motionEffects`), panel-readback-verified:
- **Blur palette** (ct1): radius 0x86000052–54 and H/V ratio 0x86000056–58 stored =
  (UI−0.5)×2 — now a TWO-point fit on both sides of neutral (0.73→0.46, 0.60→0.20,
  0.40→−0.20; panel read 0.60/0.40 exact); scaling 0x8600005B–5D identity. Write
  live-confirmed.
- **Key palette** (ct9, 0x0C30001x — beside Matte Finesse's 0x0C30002x): input/output
  gain+offset identity; write live-confirmed exact (0.850/0.120/0.650/0.080). The old
  "Curves corrector (Type 18)" registry grouping for these ids was an unvalidated legacy
  claim — corrected.
- **Motion Effects** = a NEW corrector type **ct15** (0x0C4000xx): spatial/temporal NR
  thresholds and blends identity (write live-confirmed; panel Frames 2 + 27/27 + 21/21
  exact); **framesFlag varint = UI frames × 2 CONFIRMED** (wrote 4 → panel Frames 2).
  temporalMotion (UI 35 → 11.8) and motionBlur (UI 0.4 → 0.0044) scales still
  unconfirmed single-points — decode-named, NOT writable yet.

## CURRENT BLIND SPOTS — consolidated 2026-07-03 (the authoritative list)
Everything below is flagged in code/tests where it applies; this list is the summary.

**Needs external resources (cannot self-serve):**
- Color Warper WRITE verify on Resolve 19 + Luma Warp sweep — needs an R21 install.
- External-matte / AI-mask / stereoscopic-3D palette blobs — need real footage or a rig.
- ACEScct iterate-loop convergence, real-SLog3 extract_frames, real-skin cross-framing
  cohesion, runner→apply live action names — needs the next real-footage session.

**Decoded but no write path (deliberate; transfer via Body copy works byte-exact):**
- Tracker data (per-frame 3×3 transforms) — authoring synthetic tracks not built.
- Keyframed/animated params — decode cracked; keyframe WRITE not built
  (verify_grade flags keyframed grades `unverifiable`).

**Known-soft spots (documented in place):**
- HDR zone-def STOCK defaults: only Dark is capture-verified; other zones' F2/F4
  placeholders — pass explicit defaults when zone-editor display fidelity matters.
- ResolveFX registry: ~375 binary-scan param candidates are double-flat (likely name
  noise / section-gated) — future ranges are CAPTURE-DRIVEN (true names arrive via
  ofxTools decode of real grades; rerun the sweep rig per name). 17 AI-heavy plugins
  never render-swept. Panel defaults recorded only for the 7 used BMD plugins.
  Enum vocabularies are PER-PLUGIN (write only observed/pool strings).
- Neat Video / third-party profile blobs: opaque pass-through by design.
- OFX declared min/max & untouched-param defaults are NOT in the wire (Resolve doesn't
  clamp at deserialize) — measured effective ranges + panel reads are the substitute.
- hue-axis HSL bumps whose edges land ON band slots pass through raw (nudge/snap idea).
- Pipeline run-level status doesn't roll up when stages are driven individually (rollup
  polish); gallery ExportStills / export_frame_as_still fail HEADLESS-only.

## Remaining gaps (follow-ups)
- **Color Warper write on R21**: the built pin-list path matches the R21 fixture exactly
  but Resolve 19.1.3 ignores it. CONFIRMED version split 2026-07-02: the original
  DRX_CALIB rig project refuses to open on 19.1.3 ("newer version needed") — the June
  sweeps ran on R21. One live apply + palette check on an R21 install closes this.
- **Polygon/curve vertex write — VERIFIED, artifact FIXED (2026-07-02).** ct6 cage
  (varint 0x08D00002={F2:2}, three F9.F1[] rings with corner-repetition bezier closure,
  scalars, identity matrix at 0x88D00014) renders the exact input geometry and masks the
  grade. The extra empty circle window row was caused by the ct4 type-flag entry — the
  generator no longer emits it for vertex shapes (one window row remains, shown as a
  Curve window; polygon vs curve is cosmetic — straight-corner geometry IS a polygon).
  0x08D00010/11 (unknown floats) still omitted; no observed effect.
- **Hue-axis edge-on-slot geometry**: bumps whose edges land on band slots pass through
  raw (renders flat if caged) — a nudge/snap strategy could lift this if ever needed.
- ~~HDR zone **definitions**~~ **DECODED 2026-07-03** (zone-editor capture sweep, two-point
  disambiguation): `hdrZone.definitions` = repeated F17 { F1 zone record }, record =
  { F1 name(str) · F2 default boundary f32 · F3 CURRENT boundary/Max-Range f32 ·
  F4 default falloff f32 · F5 CURRENT falloff f32 }. Fixtures
  `test/fixtures/hdr-zone-def-*.drx` + `test/hdr-zone-definitions.test.mjs`. Decode-level
  only — definition WRITES stay refused (no write path).
- **Color Warper Luma Warp mode**: only the chroma (hue/sat) pin grid is decoded/written;
  the Luma Warp pin-list variant is unswept (R21 rig session, same trip as the pin-write
  verify).
- ~~Motion Effects temporalMotion / motionBlur scales~~ **CONFIRMED + WRITABLE 2026-07-03**
  (three-point panel captures): temporalMotion stored = 0.28×UI + 2.0 (35→11.8, 60→18.8,
  80→24.4 exact); motionBlur stored = 0.0099×UI (50→0.495, 25→0.2475 exact; the old
  "0.4→0.0044" point was UI 0.44). Generator maps UI→stored; `test/motion-effects-scales.test.mjs`.

## Fixed during Phase 1 (2026-07)
- **offset factor**: doc said ÷2500; actual **÷25** (100× off) — corrected.
- **saturation factor**: doc said ÷100; actual **÷50** (neutral 50) — corrected.
- **contrast**: doc implied ÷100; codec takes the **1.0-scale directly (1:1)** — corrected.
- **softClipHighSoft/LowSoft**: `space:'drx'` now ×50-compensates them like saturation (they
  were passing raw → ÷50 in the encoder → 50× off in DRX space).
- **`space` flag + unified value space**; **`merge` newNodes** now fold top-level wheel keys.

*Status doc v2.0 — 2026-07 Phase 1 (scalar scaling) + Phase 2 (structural write fidelity).*
