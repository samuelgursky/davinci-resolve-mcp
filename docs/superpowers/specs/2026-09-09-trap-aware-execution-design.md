# Trap-Aware Execution

**Date:** 2026-09-09
**Status:** Approved design, pending implementation plan

## Context

An official DaVinci Resolve MCP extension now exists. Its surface is small —
`run_script`, `get_scripting_api`, `search_scripting_api`, `get_scripting_docs`,
`get_whats_new`, plus LUT/DCTL helpers. In raw capability terms `run_script` is a
superset of this repository's 376 typed tools: anything a tool does, a script can do.

So typed coverage is no longer this repository's reason to exist. What `run_script`
cannot supply is *memory of how the API lies*. That memory already lives here, in
`src/utils/api_truth.py` — 109 behaviorally-verified facts about silent failures,
unreliable returns, and silently-rejected enum keys.

Two defects make that asset underperform:

1. **It is pull, not push.** `lookup_api_truth()` is reachable as
   `resolve_control(action="api_truth")`. The agent must know to ask. Exactly one
   call site fires it proactively — `_setting_limitation()` at `src/server.py:19334`.
2. **It is thinnest where this project has actually lost work.**

   | Symbol | Known failure | Entries |
   |---|---|---|
   | `ApplyGradeFromStill` | fails silently | 0 |
   | `ExportLUT` | requires the Color page | 0 |
   | `ArchiveProject` / `SetCurrentTimeline` | archive moves the current-timeline pointer; later grade calls hit the backup | 0 |
   | `CopyGrades` | overwrote 60 hand-graded clips, unrecoverable | 1 |
   | `SetCDL` | replaces existing Primary Balance | 6 |
   | `AppendToTimeline` | consumes SOURCE frames | 19 |

   The four thinnest rows are the four that cost real work.

## Goal

Make the guardrail the product: the trap database reaches the caller at the moment
of the call, and covers the calls that have actually caused loss.

Optimizing for this operator's own work first, the public npm package second.

## Design

### 1. Action→symbol registry

`{(tool, action): [Resolve symbols the action calls]}`, declared explicitly.

Never substring-matched. The governing constraint is inherited from the docstring of
`_setting_limitation`:

> Matched narrowly on purpose … attaching an unrelated explanation to a failure is
> worse than attaching none — it reads as a diagnosis.

A drift guard asserts every symbol named in the registry is a real handler, following
the existing `test_destructive_registry_drift` pattern.

### 2. `traps_for(tool, action)`

Generalizes `_setting_limitation` beyond settings keys. Returns only exact-match
entries.

### 3. Two response paths

- **Informational** traps ride along on the result as `known_limitation`.
- **Work-destroying** traps cause `destructive_op` to refuse until the caller passes
  `acknowledge_trap: true`, reusing the shape of `_dry_run_unavailable_response` and
  `_security_block_response`.

Which path an entry takes is decided by an explicit `destroys_prior_work: true` key on
the entry — not inferred from `tags`, and not from risk level. Inferring a hard refusal
from a free-text tag is how a refusal fires on the wrong call, and a guard that cries
wolf gets disabled. Only an entry a probe has demonstrated destroys unrecoverable work
may carry the key; a drift guard asserts every such entry has a probe.

### 4. Token economy

A push returns `symbol` + `reality` + `recommended` only — never the full entry, never
a speculative match, once per operation. Response bloat is a real cost on grading jobs
and is a design constraint here, not an afterthought.

### 5. Verification (folded in)

Every entry touched by this work carries a `verify_by_readback` recipe: the concrete
readback proving the call did what it claimed. Facts come from measurement.

## Live probes

Facts are measured on Resolve 21.1, not transcribed. Both probes extend existing files
and reuse their existing scratch primitives, so no probe can reach real media or a real
project:

- **`src/utils/color_grade_live_probe.py`** — already has `_make_synthetic_video()`
  (ffmpeg-generated footage). Add: `CopyGrades` against a graph containing hand-work,
  `ApplyGradeFromStill`, `ExportLUT`.
- **`src/utils/project_lifecycle_live_probe.py`** — already has
  `_delete_disposable_project()`. Add: does `ArchiveProject` move the current-timeline
  pointer?

### Per-entry freshness stamps

The module's freshness contract is currently prose, not data. There is no per-entry
version key: build numbers live inside `reality` strings ("measured on Studio
21.0.4.5", "Studio 21.1.0.14"), while the single module constant reads
`VERIFIED_ON = "DaVinci Resolve Studio 21.0.2"`.

That constant is already false — entries beneath it cite later builds than it claims.
Staleness cannot be queried and no drift guard can see it.

Add a `verified_on` key to every entry this work touches, and backfill it wherever a
build number can be read out of existing prose. The module constant becomes the
*floor* (the oldest unrefreshed entry) rather than a global claim, with a drift guard
asserting no entry claims a build older than the floor.

Bumping the global constant to 21.1 is explicitly rejected: only four entries are
re-measured here, and a global bump would assert 109 re-measurements that did not
happen.

### Measurement overrides memory

Where a probe contradicts an existing entry — including the six `SetCDL` and nineteen
`AppendToTimeline` entries — the measured result wins and the entry is corrected in the
same change. Entries are not preserved for being old.

## Scope

**In:** the four probes; four entries written from measurement plus corrections to any
entry a probe contradicts; the registry and resolver; push wiring in `destructive_op`;
two drift guards.

**Out:** structural changes to the 32k-line `src/server.py`; deleting any tool; exposing
traps to the official extension. The last is a good follow-on — a trap digest served by
the `knowledge` tool — but shipping it before the database is trustworthy only exports
gaps faster.

## Compatibility

Step 3 is a behavior change for existing public installs: a call that returned
`{success: true}` may now refuse pending acknowledgement. Default **on** (personal
first), with a documented opt-out env var.

## Testing

Resolver and refusal paths unit-test offline against fixtures. Probes are live-gated
like the existing twelve.
