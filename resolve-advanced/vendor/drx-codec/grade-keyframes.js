/**
 * grade-keyframes — WRITE keyframed (animated) grade params into a .drx.
 *
 * Wire layout (decoded from Resolve's own captures, test/fixtures/keyframe-track.drx and
 * keyframed-grade.drx): a keyframed corrector's F6 becomes REPEATED, one block per keyframe:
 *
 *   F6 { F1: frame × 2 (absent at frame 0), F2: { F1: kind, F3: [params …] } }
 *
 * kind 2 = DYNAMIC keyframe (linear interpolation to the next one), kind 1 = STATIC keyframe
 * (holds until the next one). Frames are clip frames when applied with ApplyGradeFromDRX
 * gradeMode 2 ("start frames aligned"); gradeMode 0 drops keyframes.
 *
 * Render-verified on Studio 21.0.4.5 (2026-10-19, 30p barcode clip, Midtone Detail 0→100 over
 * frames 0→100): kind 2 gave 0.0 / 50.1 / 75.1 % of the static-MD-100 detail lift at frames
 * 0 / 50 / 75 and exactly 100 % from frame 100 on; kind 1 gave 0 % through frame 99 and 100 %
 * from frame 100. Resolve stored the blocks unchanged (Project.db readback).
 *
 * Caveat found in the same session: Primary RGB gain written as 0x0600001D–1F shows in the
 * panel but does NOT change the render on 21.0.4.5 (static or keyframed). Midtone Detail
 * (0x86000113) and saturation (0x06000005) do render. Prove other params with a render.
 *
 * @module drx-codec/grade-keyframes
 */

const { decodeProtobuf, encodeProtobuf } = require('../drp-format/protobuf-wire');
const { decodeBody, encodeBody, bodyHexOf, withBodyHex, hasF1, editAt, float32 } = require('./grade-body-wire');

const KIND = { static: 1, dynamic: 2 };

/**
 * Turn one corrector of a generated (or captured) .drx into a keyframe track.
 *
 * Every keyframe block carries the corrector's full param list; params named in a
 * keyframe's `values` get that value, all others keep the base value.
 *
 * @param {string} drxXml - .drx content with a non-keyframed corrector of `correctorType`.
 * @param {object} spec
 * @param {number} [spec.nodeIndex=0]       - 0-based node (F1.F7 entry) to edit.
 * @param {number} [spec.correctorType=1]   - 1 = Primary (lift/gamma/gain/MD/sat …).
 * @param {'dynamic'|'static'|number} [spec.kind='dynamic']
 * @param {Array<{frame:number, values:Object<string|number, number>}>} spec.keyframes -
 *   >= 2 keyframes, frames ascending; `values` maps param id (e.g. 0x86000113) → float.
 * @returns {string} .drx content with the keyframed body.
 */
function keyframeCorrector(drxXml, { nodeIndex = 0, correctorType = 1, kind = 'dynamic', keyframes } = {}) {
  const kindNum = typeof kind === 'number' ? kind : KIND[kind];
  if (!kindNum) throw new TypeError(`keyframeCorrector: kind must be dynamic|static|1|2 (got ${kind})`);
  if (!Array.isArray(keyframes) || keyframes.length < 2) throw new TypeError('keyframeCorrector: need >= 2 keyframes');
  for (let i = 0; i < keyframes.length; i++) {
    const k = keyframes[i];
    if (!(k.frame >= 0) || (i && k.frame <= keyframes[i - 1].frame)) throw new RangeError('keyframeCorrector: frames must be >= 0 and ascending');
  }
  const raw = decodeBody(bodyHexOf(drxXml));
  if (!encodeProtobuf(decodeProtobuf(raw)).equals(raw)) throw new Error('keyframeCorrector: body does not round-trip; refusing');

  let nodeSeen = -1;
  const out = editAt(raw, [1, { field: 7, where: () => (++nodeSeen === nodeIndex) }, 9, { field: 1, where: hasF1(correctorType) }], (corr) => {
    const f6s = corr.filter((f) => f.field === 6);
    if (f6s.length !== 1) throw new Error('keyframeCorrector: corrector is already keyframed');
    const inner = decodeProtobuf(decodeProtobuf(f6s[0].value).find((f) => f.field === 2).value);
    const params = inner.filter((f) => f.field === 3);
    const ids = new Set(params.map((p) => decodeProtobuf(p.value).find((f) => f.field === 1).value));
    for (const k of keyframes) {
      for (const id of Object.keys(k.values)) {
        if (!ids.has(BigInt(id))) throw new Error(`keyframeCorrector: param ${id} is not in the base corrector — write it once statically first`);
      }
    }
    const blocks = keyframes.map((k) => {
      const ps = params.map((p) => {
        const pf = decodeProtobuf(p.value);
        const id = pf.find((f) => f.field === 1).value;
        const key = Object.keys(k.values).find((x) => BigInt(x) === id);
        if (key === undefined) return p;
        const val = encodeProtobuf([{ field: 1, wire: 5, value: float32(k.values[key]) }]);
        return { field: 3, wire: 2, value: encodeProtobuf(pf.map((f) => (f.field === 2 ? { field: 2, wire: 2, value: val } : f))) };
      });
      const rest = inner.filter((f) => f.field !== 1 && f.field !== 3);
      const f2 = encodeProtobuf([{ field: 1, wire: 0, value: BigInt(kindNum) }, ...rest, ...ps]);
      const head = k.frame > 0 ? [{ field: 1, wire: 0, value: BigInt(Math.round(k.frame * 2)) }] : [];
      return { field: 6, wire: 2, value: encodeProtobuf([...head, { field: 2, wire: 2, value: f2 }]) };
    });
    corr.splice(corr.indexOf(f6s[0]), 1, ...blocks);
  });
  return withBodyHex(drxXml, encodeBody(out));
}

module.exports = { keyframeCorrector, KIND };
