# conform-qc — Operator Runbook

The conform QC & repair engine. This runbook covers both surfaces, the ground-truth
tiers, the package options, and every closed decision. Spec:
`docs/design/conform-qc-repair-engine-2026-06-16.md`.

## Core principle
A filename match is **not** a conform. The engine derives the frame the target tool
actually shows (the **Oracle**) and frame-compares it to a reference. The truth loop
(Oracle + comparator) is **deterministic and offline** — no LLM.

## One engine, injected adapters
- **Core** — the deterministic truth loop (Oracle + comparator + repair) is
  surface-agnostic. All IO is injected: a media-source adapter, a reference/frame
  sampler, a delivery sink, and an optional vision validator.
- **Local** — the same core with local adapters (local ffmpeg, local Resolve via
  bridge/MCP, filesystem media index); package → a local folder.
- **Other surfaces** — a host can compose the core with its own source/sink adapters
  (e.g. an asset library + object store). The engine itself ships only the local path.
- **Agent toolset** — `verify` / `conform` / `insert` / `package` are exposed as
  MCP/CLI tools; the agent orchestrates, the deterministic truth loop does the proving.

## Ground-truth tiers (§7)
- **A — burned reference**: source TC + filename burned in → content + identity verified
  (tesseract OCR, dark-lift, multi-frame consensus, fuzzy identity match).
- **B — clean ref + TC sidecar**: content verified by frame; identity from the sidecar.
- **C — no reference**: Oracle (+ Resolve read-back) only → **math-verified** (no picture).
- **Badge rule (non-negotiable):** no picture, no `content-verified`. Tier C is at most
  `math-verified`.

## Comparator (§8) — brightness-robust by construction
Mask burn-ins → SSIM **structure** component (brightness/contrast-invariant) → z-normalized
PSNR fallback → X/Y cross-correlation offset. Verdict `MATCH | OFFSET | WRONG | UNREADABLE`.
The dark-grade trap: plain SSIM false-rejects it (luminance term); the structure metric
MATCHes it.

## Advisory vision validation (§8.1) — ADVISORY ONLY
An **optional, host-injected** `VisionValidator` gives a second opinion on borderline /
stubborn-propose-only / alignment-mode cuts. It may **raise a flag (→ REVIEW)** or
corroborate; it can **never** clear a flag, flip a deterministic WRONG to MATCH, or
auto-apply. Disagreement → human review. Cost-gated. When no validator is injected the
truth loop runs fully deterministic.
- **Interface:** `adapters/vision-validator.js` ships the `VisionValidator` contract and a
  `FakeVisionValidator` (for tests). Concrete LLM-backed validators are supplied by the
  host application — the engine has no LLM dependency and makes no network calls.

## Repair (§9) — auto-apply policy (DECIDED)
Auto-apply **only** deterministic strategies (subclip / ticks / scale / relink-by-exact-name)
that re-verify content-identity **SSIM ≥ 0.90** (brightness-normalized, burn-in-masked) **or
PSNR ≥ 25** fallback. True-source-search + measured X/Y/scale offsets are **propose-only**.
VFX alignment **never** auto-applies. Everything else → V2 flag track. Diagnoses persist to
`ConformKnowledge` (pattern signature → strategy → outcome, confidence accrues with use).

## Finishing-media resolution (§10) — order
explicit `MediaRelationship` → project override → version `editorialRole` (finishing→online)
→ naming convention (`4K-2K` proxy → `4K` scan) → highest-resolution version. The
`MediaRelationship.frameOffset` stores the proxy↔scan head offset as data.

## Package options (§12)
media mode `{ relink | full | consolidate+handles }` × formats `{ DRP | FCP7 XML | AAF | OTIO }`
(emit any subset; **OTIO is the internal canonical**). FCP7 XML keeps `<in>` and
`<pproTicksIn>` **consistent** (Resolve reads ticks). Plus a V2 flag track + a per-clip
provenance manifest + a `ConformPackage` record. `full` / `consolidate` need mounted volumes.

## Trigger model (§15) — DECIDED
Cheap **auto-verify** (Tier C / math-only) on editorial-sidecar upload surfaces a QC badge;
the full **conform + package + Resolve read-back** runs on-demand via a "Conform" action.

## Environment tiers (for the build/tests)
Tier 1 (any machine, goldens) · Tier 2 (mounted volumes) · Tier 3 (headless Resolve) ·
Tier Vision (present only when the host injects a `VisionValidator`). A feature whose tier
is absent is BLOCKED, not failed.
