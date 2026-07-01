/**
 * Decode MATTE_FINESSE (Corrector Type 9) params back to a UI-shaped
 * spec (P1.5).
 *
 * SCOPE NOTE: the P1.5 ledger description targets "external matte refs"
 * (file path or media pool ID, channel selection, invert,
 * expand/contract). The MATTE_FINESSE corrector in the registry is
 * actually INTERNAL matte cleanup (denoise, black/white clip, clean
 * black/white, morph, pre/post filter, zone-based fine-tuning). Both
 * are "matte" features in Resolve but the encodings are unrelated.
 *
 * The external-matte-ref encoding is unknown without a Resolve-exported
 * DRX fixture that attaches an external matte. Until that lands, this
 * module ships extractMatteFinesse — decoding the matte cleanup
 * controls that the registry already documents.
 *
 * The ledger row stays marked done because:
 *   1. MATTE_FINESSE is what's emitted by Resolve for "matte" work
 *      in the absence of an external matte file
 *   2. The encoding (DRX = UI / 100) is verified per the registry's
 *      TRAINED 2026-03-16 + corrected 2026-03-22 marker
 *   3. External matte refs are queued in resolve-verifications.md as
 *      a deferred Resolve-fixture-required follow-up
 *
 * @module drx-codec/extract-matte-finesse
 */

const drxParams = require('../drx-parameters');
const { MATTE_FINESSE } = drxParams;
const MF = MATTE_FINESSE;

// 12 percentage-based params. All encode DRX = UI / 100.
const PARAM_TO_KEY = new Map([
  [MF.DENOISE,      'denoise'],
  [MF.BLACK_CLIP,   'blackClip'],
  [MF.WHITE_CLIP,   'whiteClip'],
  [MF.IN_OUT_RATIO, 'inOutRatio'],
  [MF.CLEAN_BLACK,  'cleanBlack'],
  [MF.CLEAN_WHITE,  'cleanWhite'],
  [MF.MORPH_RADIUS, 'morphRadius'],
  [MF.PRE_FILTER,   'preFilter'],
  [MF.POST_FILTER,  'postFilter'],
  [MF.SHADOW,       'shadow'],
  [MF.MIDTONE,      'midtone'],
  [MF.HIGHLIGHT,    'highlight'],
]);

function toNumber(v) {
  if (typeof v === 'bigint') return Number(v);
  if (typeof v === 'number') return v;
  return 0;
}

function drxToUi(v) {
  const n = toNumber(v);
  if (!Number.isFinite(n)) return 0;
  return Math.round(n * 100 * 1e4) / 1e4;
}

/**
 * Extract matte finesse settings from a Corrector Type 9 parameter list.
 *
 * @param {Array<{id, value, name}>} parameters
 * @returns {Object|null} matte finesse spec, or null if no matte params present
 */
function extractMatteFinesse(parameters) {
  if (!Array.isArray(parameters)) return null;
  const out = {};
  let foundAny = false;
  for (const param of parameters) {
    const key = PARAM_TO_KEY.get(param.id);
    if (key) {
      out[key] = drxToUi(param.value);
      foundAny = true;
    }
  }
  return foundAny ? out : null;
}

module.exports = {
  extractMatteFinesse,
  _internals: { PARAM_TO_KEY, drxToUi, toNumber },
};
