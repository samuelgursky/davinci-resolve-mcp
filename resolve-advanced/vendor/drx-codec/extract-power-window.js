/**
 * Decode POWER_WINDOWS (Corrector Type 4 + companions) params back to the
 * spec shape generateDRX's window input accepts (P1.4).
 *
 * Encoding (TRUE live-calibrated scales, multi-point fit 2026-06-22, applied
 * to the generator 2026-07-01 — see test/power-window-transform-calibration):
 *   WINDOW_TYPE  0x88500008  varint {F2:2} — CONSTANT in every shape's fixture;
 *                shape is discriminated by which corrector blocks are present,
 *                not by this flag (circle=ct4; linear=ct4+ct3 mask;
 *                gradient=ct65554; polygon/curve=ct4+ct6 vertex ring)
 *   ROTATE       float   stored = −UI°/180
 *   SIZE         float   stored = 1 + (UI−50)×0.08 (neutral 1.0)
 *   ASPECT       float   stored = (50−UI)/50 (neutral 0)
 *   PAN/TILT     float   stored = (UI−50)/50 × 4096 (frame pixels)
 *   SOFT_REF, SOFT_1..4  float  UI × 16 (SOFT_1–4 live in the ct3 mask block)
 *   OPACITY      float   UI / 100
 *   gradient     ct65554: ROTATION −UI°/180, HANDLE_1/2 ±4096 px,
 *                SOFTNESS UI × 100, OPACITY UI / 100
 *
 * SOFT_REF and SOFT_1 both surface as soft1 (prefer SOFT_REF when both).
 *
 * @module drx-codec/extract-power-window
 */

const drxParams = require('../drx-parameters');
const { POWER_WINDOWS, GRADIENT_WINDOW } = drxParams;

const PW = POWER_WINDOWS;
const GW = GRADIENT_WINDOW;

function toNumber(v) {
  if (typeof v === 'bigint') return Number(v);
  if (typeof v === 'number') return v;
  // Varint envelope params (e.g. WINDOW_TYPE) may arrive as a parsed {F2: n} message.
  if (v && typeof v === 'object' && v.F2 !== undefined) return Number(v.F2);
  return 0;
}

function round4(v) { return Math.round(v * 1e4) / 1e4; }
function drxToRotate(v) { return round4(-toNumber(v) * 180); }
function drxToSize(v) { return round4(50 + (toNumber(v) - 1) / 0.08); }
function drxToAspect(v) { return round4(50 - toNumber(v) * 50); }
function drxToPanTilt(v) { return round4(50 + (toNumber(v) / 4096) * 50); }
function drxSoftToUi(v, scale) { return round4(toNumber(v) / scale); }

// Back-compat shims (old approximate conventions) kept ONLY for _internals users.
function drxToPan(v) { return drxToPanTilt(v); }
function drxToTilt(v) { return drxToPanTilt(v); }

/**
 * Convert the raw DRX window-type flag back to a UI type.
 *
 * The wire flag is a CONSTANT varint 2 for every shape (live-confirmed on the
 * circle/linear/gradient/polygon/curve fixtures), so it cannot discriminate
 * shape. We disambiguate by sibling params:
 *   - gradient params (0x08F0xxxx) present → UI 5 (Gradient)
 *   - SOFT_2..4 present (linear-only mask) → UI 2 (Linear)
 *   - otherwise → UI 1 (Circle)
 * Values 3 (Polygon) and 4 (Curve) never appear in this flag; their shape is
 * carried by the ct6 vertex ring (node.params.polygonVertices).
 */
function drxToUiType(drxType, hasLinearSoftness = false) {
  const t = toNumber(drxType);
  if (t === 2) return hasLinearSoftness ? 2 : 1;
  return t;
}

/**
 * Extract window settings from a flattened window parameter list
 * (ct4 transform + ct3 softness mask + ct65554 gradient params).
 *
 * @param {Array<{id, value, name}>} parameters
 * @returns {Object|null} window spec, or null if no window params present
 */
function extractPowerWindow(parameters) {
  if (!Array.isArray(parameters)) return null;

  const out = {};
  let foundAny = false;
  let softRefVal;
  let soft1Val;

  // First pass — sibling-param shape discrimination (see drxToUiType).
  let hasLinearSoftness = false;
  let hasGradient = false;
  for (const p of parameters) {
    if (p.id === PW.SOFT_2 || p.id === PW.SOFT_3 || p.id === PW.SOFT_4) hasLinearSoftness = true;
    if (GW && (p.id === GW.SOFTNESS || p.id === GW.ROTATION || p.id === GW.HANDLE_1_POS)) hasGradient = true;
  }

  for (const param of parameters) {
    const v = param.value;
    switch (param.id) {
      case PW.WINDOW_TYPE:
        out.type = hasGradient ? 5 : drxToUiType(v, hasLinearSoftness);
        foundAny = true;
        break;
      case PW.ROTATE:
        out.rotate = drxToRotate(v);
        foundAny = true;
        break;
      case PW.SIZE:
        out.size = drxToSize(v);
        foundAny = true;
        break;
      case PW.ASPECT:
        out.aspect = drxToAspect(v);
        foundAny = true;
        break;
      case PW.PAN:
        out.pan = drxToPanTilt(v);
        foundAny = true;
        break;
      case PW.TILT:
        out.tilt = drxToPanTilt(v);
        foundAny = true;
        break;
      case PW.OPACITY:
        out.opacity = round4(toNumber(v) * 100);
        foundAny = true;
        break;
      case PW.SOFT_REF:
        softRefVal = toNumber(v);
        foundAny = true;
        break;
      case PW.SOFT_1:
        soft1Val = toNumber(v);
        foundAny = true;
        break;
      case PW.SOFT_2:
        out.soft2 = drxSoftToUi(v, 16);
        foundAny = true;
        break;
      case PW.SOFT_3:
        out.soft3 = drxSoftToUi(v, 16);
        foundAny = true;
        break;
      case PW.SOFT_4:
        out.soft4 = drxSoftToUi(v, 16);
        foundAny = true;
        break;
      default:
        // Gradient window (ct65554) params.
        if (GW && param.id === GW.SOFTNESS) {
          out.type = 5;
          out.soft1 = drxSoftToUi(v, 100);
          foundAny = true;
        } else if (GW && param.id === GW.ROTATION) {
          out.type = 5;
          out.rotate = drxToRotate(v);
          foundAny = true;
        } else if (GW && param.id === GW.HANDLE_1_POS) {
          out.type = 5;
          out.pan = drxToPanTilt(v);
          foundAny = true;
        } else if (GW && param.id === GW.HANDLE_2_POS) {
          out.type = 5;
          out.tilt = drxToPanTilt(v);
          foundAny = true;
        } else if (GW && param.id === GW.OPACITY) {
          out.type = 5;
          out.opacity = round4(toNumber(v) * 100);
          foundAny = true;
        }
        break;
    }
  }

  // Reconcile SOFT_REF / SOFT_1 if either was present (circle/linear), UI × 16.
  if (softRefVal !== undefined) {
    out.soft1 = drxSoftToUi(softRefVal, 16);
  } else if (soft1Val !== undefined) {
    out.soft1 = drxSoftToUi(soft1Val, 16);
  }

  return foundAny ? out : null;
}

module.exports = {
  extractPowerWindow,
  _internals: {
    drxToRotate, drxToSize, drxToAspect, drxToPanTilt, drxToPan, drxToTilt, drxSoftToUi, drxToUiType, toNumber,
  },
};
