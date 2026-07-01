/**
 * Version-specific capability map — the safety gate for retargeting.
 *
 * Re-stamping a timeline DOWN to an older Resolve is only safe if every schema
 * element / feature it uses is supported by the target's `DbPrjVer`. This maps
 * `capability → minimum DbPrjVer that supports it`.
 *
 * GROUND-TRUTH ONLY. Seeded with what's been verified against real exports: for
 * standard timeline content (media clips, cross-dissolves, geometry transforms,
 * speed retime) the SeqContainer schema is byte-identical across Resolve 19/20/21,
 * so those capabilities are universal (min = 14, the oldest version in the registry).
 *
 * This map is intentionally sparse. It GROWS two ways:
 *   1. Diff real exports of ADVANCED content across versions (what element appears
 *      in a 21 export that a 19 can't parse) → add a row with the gating DbPrjVer.
 *   2. Fold in Resolve release notes (which version first shipped a feature).
 * Until a feature is recorded here from ground truth, it is treated as UNKNOWN
 * (see `collectCapabilities` → `unknown`), and downgrades surface it rather than
 * silently shipping a file the target can't open.
 *
 * @module drt-format/capabilities
 */

// capability id → minimum DbPrjVer. Only verified-universal rows so far.
const CAPABILITIES = {
  'clip:media': 14, // Sm2TiVideoClip with MediaRef
  'transition:cross-dissolve': 14, // Sm2TiTransition PrettyType "Cross Dissolve"
  'transform:basic': 14, // zoom/pan/rotation via EffectFiltersBA
  'retime:speed': 14, // constant-speed retime (ticks/in)
  'clip:title-fusion': 14, // Sm2TiVideoClip + CompositionTable (Fusion Title)
};

// Detectors: how to tell a capability is USED from the SeqContainer XML.
// id → predicate(seqXml). Add a detector when you add a gated capability.
const DETECTORS = {
  'clip:media': (x) => /<Sm2TiVideoClip\b/.test(x) && /<MediaRef>/.test(x),
  'transition:cross-dissolve': (x) => /Cross Dissolve/.test(x),
  'transform:basic': (x) => /<EffectFiltersBA>/.test(x),
  'clip:title-fusion': (x) => /<CompositionTable>/.test(x) || /CompositionBA/.test(x),
};

/**
 * Which known capabilities does this SeqContainer use?
 * @returns {{ used: string[], unknownElements: string[] }}
 *   `used` — recognized capabilities present.
 *   `unknownElements` — Sm2Ti* element tags present that aren't covered by any
 *   detector (candidates for a new registry row before trusting a downgrade).
 */
function collectCapabilities(seqXml) {
  const used = Object.keys(DETECTORS).filter((id) => DETECTORS[id](seqXml));
  const known = new Set(['Sm2TiTrack', 'Sm2TiVideoClip', 'Sm2TiAudioClip', 'Sm2TiTransition']);
  const unknownElements = [...new Set(
    (seqXml.match(/<Sm2Ti[A-Za-z0-9]+/g) || []).map((t) => t.slice(1)),
  )].filter((t) => !known.has(t));
  return { used, unknownElements };
}

/**
 * Can a timeline using `used` capabilities be targeted to `targetDbPrjVer`?
 * @returns {{ ok: boolean, blocked: Array<{cap:string, min:number}>, unknown: string[] }}
 */
function checkCapabilities(used, unknownElements, targetDbPrjVer) {
  const blocked = used
    .map((cap) => ({ cap, min: CAPABILITIES[cap] ?? Infinity }))
    .filter((r) => r.min > Number(targetDbPrjVer));
  return { ok: blocked.length === 0, blocked, unknown: unknownElements || [] };
}

module.exports = { CAPABILITIES, collectCapabilities, checkCapabilities };
