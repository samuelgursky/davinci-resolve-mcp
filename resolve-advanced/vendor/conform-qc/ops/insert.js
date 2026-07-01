'use strict';

/**
 * ops/insert.js — element-insert lifecycle (spec §0.5, P4.5): slot finished
 * elements (VFX renders, Topaz/upscale, regrades, graphics) into the timeline,
 * verify by the right MODE (alignment for VFX/graphics, content-identity for
 * Topaz/regrade), reconcile sizing, resolve versions. Pure (comparator injected).
 */

/**
 * Match an incoming element to its timeline slot (spec §0.5 ladder):
 *   shot-id naming → plate source-TC → content edge-match → explicit map.
 */
function matchElementToSlot(element, timeline, opts = {}) {
  if (opts.explicitMap && opts.explicitMap[element.name] != null) {
    const slot = timeline.find((c) => c.cutId === opts.explicitMap[element.name]);
    if (slot) return { slot, method: 'explicit' };
  }
  if (element.shotId != null) {
    const slot = timeline.find((c) => c.shotId === element.shotId);
    if (slot) return { slot, method: 'shot-id' };
  }
  if (element.plateSourceTc != null) {
    const slot = timeline.find((c) => c.sourceTc === element.plateSourceTc);
    if (slot) return { slot, method: 'plate-tc' };
  }
  if (element.edgeFrameKey != null) {
    const slot = timeline.find((c) => c.edgeFrameKey === element.edgeFrameKey);
    if (slot) return { slot, method: 'edge-frame' };
  }
  return null;
}

/** Resolve to the latest APPROVED version of an element (§9 wrong-version). */
function resolveLatestVersion(versions) {
  const approved = versions.filter((v) => v.approved !== false);
  const pool = approved.length ? approved : versions;
  return pool.reduce((best, v) => (best == null || v.version > best.version ? v : best), null);
}

/**
 * ALIGNMENT verification mode (spec §8.1, P4.5): the element SHOULD look
 * different from the plate. Verify it covers the used range + handles, is
 * frame-aligned (edge-frame/TC), and is correctly sized — NOT pixel identity.
 */
function alignmentVerify(element, plate, opts = {}) {
  const reqHandles = plate.requiredHandles != null ? plate.requiredHandles : 0;
  const covers = element.sourceIn <= plate.usedIn - reqHandles && element.sourceOut >= plate.usedOut + reqHandles;
  const headHandles = plate.usedIn - element.sourceIn;
  const tailHandles = element.sourceOut - plate.usedOut;
  const handlesOk = headHandles >= reqHandles && tailHandles >= reqHandles;
  const edgeOk = opts.requireEdge ? element.edgeFrameKey === plate.edgeFrameKey : true;
  const sizingOk = !element.dims || !plate.dims || (element.dims.w === plate.dims.w && element.dims.h === plate.dims.h);
  const reasons = [];
  if (!covers) reasons.push('does not cover used range + handles');
  if (!handlesOk) reasons.push(`handles head ${headHandles}/tail ${tailHandles} < required ${reqHandles}`);
  if (!edgeOk) reasons.push('edge-frame/TC mismatch');
  if (!sizingOk) reasons.push('sizing mismatch');
  return { mode: 'alignment', aligned: covers && handlesOk && edgeOk && sizingOk, covers, handlesOk, headHandles, tailHandles, edgeOk, sizingOk, reasons };
}

/** §9 VFX render misaligned: propose re-alignment to the plate source range + handles. */
function vfxRealign(plate, opts = {}) {
  const h = plate.requiredHandles != null ? plate.requiredHandles : (opts.handles || 0);
  return { realignedIn: plate.usedIn - h, realignedOut: plate.usedOut + h, handles: h };
}

/** §9 VFX/Topaz res-or-format mismatch: propose resize/transcode + sizing patch. */
function resFormatReconcile(element, expectation) {
  const dimsMatch = !element.dims || !expectation.dims || (element.dims.w === expectation.dims.w && element.dims.h === expectation.dims.h);
  const codecMatch = !expectation.codec || element.codec === expectation.codec;
  if (dimsMatch && codecMatch) return { match: true, sizingPatch: null, transcode: null };
  const sizingPatch = dimsMatch ? null : { scale: expectation.dims.w / element.dims.w };
  return { match: false, sizingPatch, transcode: codecMatch ? null : { to: expectation.codec } };
}

/**
 * Topaz/regrade insert: CONTENT-IDENTITY verify (enhanced-but-structurally-same)
 * + res/format reconcile. comparator is injected (the brightness-robust one).
 */
async function topazContentVerify(referenceFrame, derivedFrame, expectation, compareFn) {
  const det = await compareFn(referenceFrame, derivedFrame, { mode: 'content-identity' });
  const recon = expectation ? resFormatReconcile({ dims: expectation.elementDims, codec: expectation.elementCodec }, expectation) : { match: true };
  return { mode: 'content-identity', verdict: det.verdict, structure: det.structure, sizing: recon };
}

/** Element/slot record (§11): incoming render ↔ slot, versioned, verify mode + verdict + provenance. */
function makeSlotRecord({ element, slot, method, verifyMode, verdict, provenance }) {
  return {
    type: 'ElementSlot',
    element: { name: element.name, kind: element.kind, version: element.version },
    slotCutId: slot ? slot.cutId : null,
    matchMethod: method || null,
    verifyMode,
    verdict,
    provenance: provenance || {},
  };
}

module.exports = {
  matchElementToSlot,
  resolveLatestVersion,
  alignmentVerify,
  vfxRealign,
  resFormatReconcile,
  topazContentVerify,
  makeSlotRecord,
};
