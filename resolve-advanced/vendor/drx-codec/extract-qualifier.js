/**
 * Decode HSL_QUALIFIER (Corrector Type 2) params back to the spec
 * shape generateDRX's qualifier input accepts (P1.3).
 *
 * All percentage-based params store DRX value = UI / 100, so the
 * extractor multiplies by 100 to recover UI units. mode and modeFlag
 * (varints) come through as numbers.
 *
 * @module drx-codec/extract-qualifier
 */

const drxParams = require('../drx-parameters');
const { HSL_QUALIFIER } = drxParams;

// Map of param ID → output key. The duplicate hue params (HUE_WIDTH_DUP,
// HUE_SOFT_DUP) appear in the protobuf but are linked to the canonical
// HUE_WIDTH / HUE_SOFT values — we don't surface them separately, only
// the canonical names. If they disagree, the canonical entry wins
// (the canonical id appears first in the generator's emission order).
const PARAM_TO_KEY = new Map([
  [HSL_QUALIFIER.HUE_CENTER,    'hueCenter'],
  [HSL_QUALIFIER.HUE_WIDTH,     'hueWidth'],
  [HSL_QUALIFIER.HUE_SYM,       'hueSymmetry'],
  [HSL_QUALIFIER.HUE_SOFT,      'hueSoft'],
  [HSL_QUALIFIER.SAT_HIGH,      'satHigh'],
  [HSL_QUALIFIER.SAT_LOW,       'satLow'],
  [HSL_QUALIFIER.SAT_HIGH_SOFT, 'satHighSoft'],
  [HSL_QUALIFIER.SAT_LOW_SOFT,  'satLowSoft'],
  [HSL_QUALIFIER.LUM_HIGH,      'lumHigh'],
  [HSL_QUALIFIER.LUM_LOW,       'lumLow'],
  [HSL_QUALIFIER.LUM_HIGH_SOFT, 'lumHighSoft'],
  [HSL_QUALIFIER.LUM_LOW_SOFT,  'lumLowSoft'],
]);

const VARINT_IDS = new Set([
  HSL_QUALIFIER.MODE_FLAG,
  HSL_QUALIFIER.QUALIFIER_MODE,
]);

/**
 * Convert a stored DRX float value back to UI percentage.
 * Tolerates BigInt (from varints) and clamps to a sane range.
 */
function drxToUi(v) {
  if (typeof v === 'bigint') v = Number(v);
  if (typeof v !== 'number' || !Number.isFinite(v)) return 0;
  // Multiply by 100 and round to 6 decimals to suppress float32 noise.
  return Math.round(v * 100 * 1e6) / 1e6;
}

/**
 * Convert a varint value (possibly BigInt) to a plain number.
 */
function varintToNumber(v) {
  if (typeof v === 'bigint') return Number(v);
  if (typeof v === 'number') return v;
  return 0;
}

/**
 * Extract HSL qualifier settings from a corrector's parameter list.
 *
 * @param {Array<{id, value, name}>} parameters - parser-surfaced params
 * @returns {Object|null} qualifier spec or null if not a qualifier corrector
 */
function extractQualifier(parameters) {
  if (!Array.isArray(parameters)) return null;

  const out = {};
  let foundAny = false;
  let foundMode = false;

  for (const param of parameters) {
    if (PARAM_TO_KEY.has(param.id)) {
      const key = PARAM_TO_KEY.get(param.id);
      // Don't overwrite if already set (duplicate hue params come after
      // the canonical ones in the generator's emission order, but the
      // canonical entries should win).
      if (out[key] === undefined) {
        out[key] = drxToUi(param.value);
        foundAny = true;
      }
    } else if (param.id === HSL_QUALIFIER.MODE_FLAG) {
      out.modeFlag = varintToNumber(param.value);
      foundMode = true;
    } else if (param.id === HSL_QUALIFIER.QUALIFIER_MODE) {
      out.mode = varintToNumber(param.value);
      foundMode = true;
    }
  }

  if (!foundAny && !foundMode) return null;
  return out;
}

module.exports = {
  extractQualifier,
  _internals: { PARAM_TO_KEY, VARINT_IDS, drxToUi, varintToNumber },
};
