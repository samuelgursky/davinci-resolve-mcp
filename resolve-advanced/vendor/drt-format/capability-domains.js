/**
 * Unified capability layer across Resolve file formats.
 *
 * One version registry serves all three formats (DRT/DRP/DRX all carry the same
 * DbAppVer/DbPrjVer). Capability *gating*, though, is domain-specific:
 *
 *   - TIMELINE domain (DRT, DRP): which SeqContainer elements a target can open.
 *     Backed by ./capabilities (element-based gate) — built, sparse-but-growing.
 *   - COLOR domain (DRX): which grade nodes / ResolveFX params a target supports.
 *     The vocabulary already exists in the AutoResearch param registry
 *     (packages/drx/drx-parameters/{parameter-ids.js,calibrated-ranges.json}); the
 *     PER-VERSION gating is filled by DRX fingerprint/diff across versions — the same
 *     method as the timeline domain (see ./schema-fingerprint). Until that data lands,
 *     color downgrades are NOT gated (treated as universal) and say so.
 *
 * DRPs span BOTH domains (they carry a timeline AND grades/render settings); the
 * timeline gate covers the SeqContainer side, the color domain the grade side.
 *
 * @module drt-format/capability-domains
 */

const timeline = require('./capabilities');

// format → capability domain
const DOMAIN_BY_FORMAT = { drt: 'timeline', drp: 'timeline', drx: 'color' };

function domainForFormat(fmt) {
  return DOMAIN_BY_FORMAT[String(fmt).toLowerCase().replace(/^\./, '')] || null;
}

// Color domain — structural surface backed by the DRX param registry. Version-gating
// is not yet populated, so it never blocks; it points at where the vocabulary lives and
// surfaces (does not block on) the fact that gating data is pending.
const color = {
  domain: 'color',
  paramRegistry: 'packages/drx/drx-parameters/parameter-ids.js',
  gatingPopulated: false,
  // Same shape as ./capabilities so callers are uniform.
  collectCapabilities() { return { used: [], unknownElements: [] }; },
  checkCapabilities() { return { ok: true, blocked: [], unknown: [], note: 'color version-gating not yet mapped' }; },
};

const timelineDomain = { domain: 'timeline', ...timeline };

/** Select the capability surface for a format ('drt' | 'drp' | 'drx'). */
function capabilitiesForFormat(fmt) {
  return domainForFormat(fmt) === 'color' ? color : timelineDomain;
}

module.exports = {
  DOMAIN_BY_FORMAT,
  domainForFormat,
  capabilitiesForFormat,
  timeline: timelineDomain,
  color,
};
