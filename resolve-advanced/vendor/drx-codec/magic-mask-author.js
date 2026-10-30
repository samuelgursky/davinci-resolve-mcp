/**
 * magic-mask-author — move a Magic Mask 2 subject click inside a captured grade, so a mask can
 * be placed on another clip with no Viewer clicks.
 *
 * Decoded from a hand-made Magic Mask 2 (person click, Better) on Studio 21.0.4.5, 2026-10-19.
 * The grade body stores the CLICK, not the tracked mattes (those are regenerated):
 *
 *   node.F9 corrector type 2 → F6.F2:
 *     F3 { F1: 0x88300037, F2 { F2: 2 } }                       mask mode
 *     F4 { F1 { F1: frame × 2,                                  SOURCE frame of the click
 *              F2 { F1: 0x88300036, F2 { F23 { F1 {
 *                F1: 2048 (stroke id), F2 { F1: 2, F2: 6 (add point),
 *                F3 { F1: x f32, F2: y f32 } } } } } } } }
 *   node.F10 tool list: 0xC00000B3 (stroke list, "Overall Track"), 0xC00000B6/B7 (= stroke id),
 *     0xC00000CA { F2.F11.F1.F220 = frame × 2 }, 0xC00000CC { F2.F2 = frame × 2 }
 *
 * x / y are centred and y-up, normalised to the image: x = u − 0.5, y = 0.5 − v for a click at
 * (u, v) of the frame measured from its top-left (the hand click at u 0.484, v 0.371 stored
 * −0.0156, 0.1286).
 *
 * Proven 2026-10-19: the authored grade applied with ApplyGradeFromDRX (gradeMode 0) to a
 * DIFFERENT clip, then TimelineItem.CreateMagicMask("BI") — no clicks — tracked all 50 frames;
 * a Saturation 0 Primary in the same node dropped subject saturation 170 → 4.6 while the
 * background stayed 164.6 → 164.6. RegenerateMagicMask() returned False on the fresh apply;
 * use CreateMagicMask.
 *
 * @module drx-codec/magic-mask-author
 */

const { decodeProtobuf, encodeProtobuf } = require('../drp-format/protobuf-wire');
const { decodeBody, encodeBody, bodyHexOf, withBodyHex, hasF1, editAt, readAt } = require('./grade-body-wire');

const MASK_CORRECTOR = 2;
const TOOL_REF_FRAME_A = 0xc00000ca;
const TOOL_REF_FRAME_B = 0xc00000cc;
const CLICK = [1, 7, 9, { field: 1, where: hasF1(MASK_CORRECTOR) }, 6, 2, 4, 1];

/** Read the click(s) of a Magic Mask grade body: [{ frame, x, y, op }]. */
function readMagicMaskClicks(bodyHex) {
  const raw = decodeBody(bodyHex);
  const out = [];
  editAt(raw, CLICK.slice(0, -1), (f4) => {
    for (const blk of f4.filter((f) => f.field === 1 && f.wire === 2)) {
      const b = decodeProtobuf(blk.value);
      const t = b.find((f) => f.field === 1 && f.wire === 0);
      const frame = t ? Number(t.value) / 2 : 0;
      const strokes = readAt(blk.value, [2, 2, 23]) || [];
      for (const s of strokes.filter((f) => f.field === 1 && f.wire === 2)) {
        const pt = readAt(s.value, [2]);
        const xy = readAt(s.value, [2, 3]);
        out.push({
          frame,
          op: Number((pt.find((f) => f.field === 2) || {}).value),
          x: xy.find((f) => f.field === 1).value.readFloatLE(0),
          y: xy.find((f) => f.field === 2).value.readFloatLE(0),
        });
      }
    }
  });
  return out;
}

/**
 * Re-place the single subject click of a captured Magic Mask 2 grade.
 *
 * @param {string} drxXml - .drx whose <Body> is a captured Magic Mask grade (one click).
 * @param {{frame:number, x:number, y:number}} click - SOURCE frame; x/y centred, y-up, in [-0.5, 0.5].
 * @param {object} [opts]
 * @param {string} [opts.primaryFromDrx] - .drx whose Primary corrector (type 1) is copied into the
 *   mask node, so the correction lands inside the mask (e.g. saturation, Midtone Detail).
 * @returns {string} .drx content.
 */
function placeMagicMaskClick(drxXml, { frame, x, y }, { primaryFromDrx } = {}) {
  if (!Number.isInteger(frame) || frame < 0) throw new TypeError('placeMagicMaskClick: frame must be a non-negative integer (source frame)');
  if (!(Math.abs(x) <= 0.5 && Math.abs(y) <= 0.5)) throw new RangeError('placeMagicMaskClick: x/y are centred image fractions in [-0.5, 0.5]');
  let raw = decodeBody(bodyHexOf(drxXml));
  if (!encodeProtobuf(decodeProtobuf(raw)).equals(raw)) throw new Error('placeMagicMaskClick: body does not round-trip; refusing');
  if (readMagicMaskClicks(bodyHexOf(drxXml)).length !== 1) throw new Error('placeMagicMaskClick: expected exactly one captured click');
  const t2 = BigInt(frame * 2);
  raw = editAt(raw, CLICK, (f) => { for (const x_ of f) if (x_.field === 1 && x_.wire === 0) x_.value = t2; });
  raw = editAt(raw, [...CLICK, 2, 2, 23, 1, 2, 3], (f) => {
    for (const v of f) {
      if (v.field === 1 && v.wire === 5) v.value.writeFloatLE(x, 0);
      if (v.field === 2 && v.wire === 5) v.value.writeFloatLE(y, 0);
    }
  });
  raw = editAt(raw, [1, 7, 10, { field: 1, where: hasF1(TOOL_REF_FRAME_A) }, 2, 11, 1], (f) => { for (const v of f) if (v.field === 220) v.value = t2; });
  raw = editAt(raw, [1, 7, 10, { field: 1, where: hasF1(TOOL_REF_FRAME_B) }, 2], (f) => { for (const v of f) if (v.field === 2 && v.wire === 0) v.value = t2; });
  if (primaryFromDrx) {
    const praw = decodeBody(bodyHexOf(primaryFromDrx));
    const prim = (readAt(praw, [1, 7, 9]) || []).find((f) => f.field === 1 && f.wire === 2 && hasF1(1)(decodeProtobuf(f.value)));
    if (!prim) throw new Error('placeMagicMaskClick: primaryFromDrx has no Primary corrector');
    raw = editAt(raw, [1, 7, 9], (list) => {
      if (list.some((f) => f.field === 1 && f.wire === 2 && hasF1(1)(decodeProtobuf(f.value)))) throw new Error('placeMagicMaskClick: mask node already has a Primary');
      list.splice(list.findIndex((f) => f.field === 1), 0, prim);
    });
  }
  return withBodyHex(drxXml, encodeBody(raw));
}

module.exports = { placeMagicMaskClick, readMagicMaskClicks };
