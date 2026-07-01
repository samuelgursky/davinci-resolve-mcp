'use strict';

/**
 * compare/ — derived-vs-reference frame comparison (spec §8).
 *
 * Two modes (spec §0.5):
 *  - content-identity (conform/patch/Topaz/regrade): the derived frame must
 *    STRUCTURALLY match the reference, brightness-robustly. Implemented here.
 *  - alignment (VFX/new graphics): the element SHOULD look different; verify it
 *    lands on the right shot, range + handles, frame-aligned, sized — NOT pixels.
 *    Stubbed (full impl is P4.5).
 */

const metrics = require('./metrics');
const { decodeGrayNormalized } = require('./decode');

const DEFAULT_SIZE = Object.freeze({ width: 320, height: 192 });

/** Alignment verification mode — stub (P4.5). Distinct entry point. */
function alignmentVerify() {
  throw new Error(
    'conform-qc compare: alignment verification mode not implemented (P4.5) — ' +
      'VFX/graphics intentionally differ from the plate; verify range + handles + ' +
      'edge-frame/TC alignment + sizing, not pixel identity.',
  );
}

/**
 * Compare a reference frame and a derived frame.
 * @param {string|Buffer} referenceInput
 * @param {string|Buffer} derivedInput
 * @param {object} opts { size?, mask?, burnInRegions?, thresholds?, maxShift?, mode? }
 * @returns {Promise<object>} verdict object (content-identity mode)
 */
async function compareFrames(referenceInput, derivedInput, opts = {}) {
  const size = opts.size || DEFAULT_SIZE;
  const mode = opts.mode || 'content-identity';
  if (mode === 'alignment') return alignmentVerify();
  if (mode !== 'content-identity') {
    throw new Error(`conform-qc compare: unknown mode "${mode}"`);
  }

  const ref = await decodeGrayNormalized(referenceInput, size);
  const der = await decodeGrayNormalized(derivedInput, size);
  const mask = opts.mask || metrics.buildBurnInMask(size.width, size.height, opts.burnInRegions);
  return metrics.classify(ref.data, der.data, {
    width: size.width,
    height: size.height,
    mask,
    thresholds: opts.thresholds,
    maxShift: opts.maxShift,
  });
}

module.exports = {
  DEFAULT_SIZE,
  compareFrames,
  alignmentVerify,
  decodeGrayNormalized,
  ...metrics,
};
