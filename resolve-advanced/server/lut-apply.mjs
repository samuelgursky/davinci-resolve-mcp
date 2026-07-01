/**
 * lut_apply (Phase-3) — the Body-LUT WRITE path. RE'd 2026-07-01 from the paired p5-1 fixtures
 * (no-lut vs with-lut): a node's F9 gains an F1 corrector carrying SLOT_META (varint) + LUT_PATH
 * (F5 string). The encoder in grade-body-patch.mjs (injectNodeLut) reproduces the captured
 * with-LUT corrector BYTE-EXACT, so a named `.cube` (e.g. a Kodak 5219 film look) can be attached
 * to a node offline — no Resolve, no generator (which drops LUT refs).
 *
 * Every write is ROUND-TRIP ASSERTED: decode the patched Body and confirm lutPath + slotMeta come
 * back (refuse-not-fake). Operates on a .drx file (Body hex lives in the GyStill XML). The LUT
 * actually taking effect in Resolve requires a live-confirm pass, like every Resolve-behavior tool.
 *
 * Fallback ladder (if a target needs a NEW .cube the encoder can't express): grade_transfer of a
 * look that already carries the LUT + live-API assignment. This offline path covers named-LUT attach.
 */
import fs from 'node:fs/promises';
import { createRequire } from 'node:module';
import { injectNodeLut } from './grade-body-patch.mjs';
import { drxParser } from './libs.mjs';

const require = createRequire(import.meta.url);
const { extractDrxLutRefs } = require('../vendor/drx-codec/extract-lut-refs.js');

const BODY_RE = /<Body>([0-9a-fA-F\s]*)<\/Body>/;

/** Pull the Body hex (with the 0x81 prefix) out of a GyStill .drx XML. */
export function extractBodyHex(xml) {
  const m = BODY_RE.exec(xml);
  if (!m) throw new Error('lut_apply: no <Body> found in the .drx (not a GyStill grade?)');
  return m[1].replace(/\s+/g, '');
}

/**
 * Attach a named LUT to a node of a .drx, with a round-trip assert.
 * @param {{drxPath?:string, content?:string}} ref
 * @param {{lutPath:string, nodeIndex?:number, slotMeta?:number, outPath?:string}} opts
 * @returns {Promise<{content:string, outPath?:string, lutPath:string, slotMeta:number, nodeIndex:number, verified:true}>}
 */
export async function applyLut(ref, opts = {}) {
  if (!opts.lutPath) throw new Error('lut_apply: opts.lutPath (the .cube name/path) required');
  const nodeIndex = opts.nodeIndex ?? 0;
  const slotMeta = opts.slotMeta ?? 6;
  const xml = ref.content != null ? ref.content : await fs.readFile(ref.drxPath, 'utf8');
  const bodyHex = extractBodyHex(xml);
  const newBodyHex = await injectNodeLut(bodyHex, nodeIndex, { lutPath: opts.lutPath, slotMeta });
  const newXml = xml.replace(BODY_RE, `<Body>${newBodyHex}</Body>`);

  // ROUND-TRIP ASSERT: decode the patched grade and confirm the LUT ref survives.
  const parsed = await drxParser().parseDRXContent(newXml);
  const refs = extractDrxLutRefs(parsed);
  const got = refs.find((r) => r.nodeIndex === nodeIndex) || refs[0];
  if (!got || got.lutPath !== opts.lutPath)
    throw new Error(`lut_apply round-trip assert FAILED: wrote '${opts.lutPath}' but decoded ${got ? `'${got.lutPath}'` : 'nothing'}`);
  if (got.slotMeta !== slotMeta) throw new Error(`lut_apply round-trip assert FAILED: slotMeta wrote ${slotMeta} but decoded ${got.slotMeta}`);

  const out = { content: newXml, lutPath: got.lutPath, slotMeta: got.slotMeta, nodeIndex, verified: true, liveConfirm: 'pending (live validation)' };
  if (opts.outPath) {
    await fs.writeFile(opts.outPath, newXml);
    out.outPath = opts.outPath;
  }
  return out;
}
