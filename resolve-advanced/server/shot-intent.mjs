/**
 * shot-intent tagging (Layer-3 capability) — deterministic SIGNALS → persisted TAGS.
 *
 * The matchers are intent-blind: they ask "are the numbers equal?", never "was this
 * deliberate?" — so gray-world kills a motivated warm look, exposure_level flattens a
 * low-key-by-design shot. Intent is a HYBRID (cross-craft review): (L1) DETERMINISTIC
 * signals — scope-derived (this module, from scope_read) + metadata (WB/TOD/ISO if the
 * caller supplies it) — become a proposal; (L2) the CLIENT (LLM, not this tool) turns
 * signals into a human-readable review WITH EVIDENCE and the human ratifies; (L3) the
 * ratified decision becomes a persisted TAG the deterministic tools consume.
 *
 * This module owns L1 + the exclusion contract the matchers honor. It NEVER decides intent
 * on its own — it surfaces evidence and a low/med confidence; the human (via the client)
 * ratifies ambiguous/creative cases. PURE: consumes a scope_read result, emits tags.
 */

/**
 * Derive candidate intent tags from a scope_read result (+ optional clip metadata).
 * @param {object} scope a scope_read result (server/scope-read.mjs)
 * @param {{whiteBalanceK?:number, tint?:number, timeOfDay?:string, gel?:string, iso?:number}} [meta]
 * @returns {{tags:Array<{tag:string, confidence:'low'|'med'|'high', evidence:string}>}}
 */
export function deriveIntentTags(scope, meta = {}) {
  const tags = [];
  if (!scope || !scope.signals) return { tags };
  const s = scope.signals;
  const parade = scope.parade || {};

  // ── scope-derived signals ────────────────────────────────────────────
  if (s.lowKey) {
    tags.push({ tag: 'low_key', confidence: 'med', evidence: `luma median ${s.lumaMedian}, shadow-weighted` });
  }
  if (s.monochromatic) {
    tags.push({ tag: 'monochromatic', confidence: 'med', evidence: `hue concentration ${s.hueConcentration} @ ~${s.dominantHueDeg}°` });
  }
  if (s.lowSaturation && Math.abs(parade.spread ?? 0) < 8) {
    tags.push({ tag: 'neutral', confidence: 'low', evidence: `mean sat ${s.meanSat}, parade spread ${parade.spread}` });
  }
  // Warm/cool CAST from the RGB parade (motivated colour a matcher must not neutralize away).
  const rb = parade.rb ?? 0;
  if (rb > 25 && s.meanSat > 0.08) {
    tags.push({ tag: 'motivated_warm', confidence: 'low', evidence: `R−B parade +${rb}` });
  } else if (rb < -25 && s.meanSat > 0.08) {
    tags.push({ tag: 'motivated_cool', confidence: 'low', evidence: `R−B parade ${rb}` });
  }
  if (s.highContrast) tags.push({ tag: 'high_contrast', confidence: 'low', evidence: `luma range ${s.contrastRange}` });
  if (s.lowContrast) tags.push({ tag: 'low_contrast', confidence: 'low', evidence: `luma range ${s.contrastRange}` });

  // ── metadata signals (raise confidence when present) ─────────────────
  if (typeof meta.whiteBalanceK === 'number') {
    if (meta.whiteBalanceK <= 3400) upgradeOrAdd(tags, 'motivated_warm', `WB ${meta.whiteBalanceK}K (tungsten/warm)`);
    else if (meta.whiteBalanceK >= 6500) upgradeOrAdd(tags, 'motivated_cool', `WB ${meta.whiteBalanceK}K (cool)`);
  }
  if (meta.timeOfDay === 'night') upgradeOrAdd(tags, 'night', `metadata TOD=night`);
  else if (meta.timeOfDay === 'day') upgradeOrAdd(tags, 'day', `metadata TOD=day`);
  if (meta.gel) tags.push({ tag: 'gelled', confidence: 'med', evidence: `gel: ${meta.gel}` });

  return { tags };
}

function upgradeOrAdd(tags, tag, evidence) {
  const existing = tags.find((t) => t.tag === tag);
  if (existing) {
    // Two independent signals (scope + metadata) agreeing = high confidence.
    existing.confidence = 'high';
    existing.evidence += `; ${evidence}`;
  } else {
    tags.push({ tag, confidence: 'med', evidence });
  }
}

// Tags that mark INTENTIONAL colour/exposure — a neutralize/level pass must EXCLUDE these
// shots (or only touch them behind an explicit override). This is the contract the matchers honor.
export const INTENT_EXCLUDE_TAGS = new Set(['motivated_warm', 'motivated_cool', 'monochromatic', 'low_key', 'gelled', 'neon']);

/**
 * Given a clip's ratified tags, should a neutralize/level pass SKIP it?
 * @param {Array<string|{tag:string}>} tags
 */
export function shouldExcludeFromNeutralize(tags = []) {
  return (tags || []).some((t) => INTENT_EXCLUDE_TAGS.has(typeof t === 'string' ? t : t.tag));
}
