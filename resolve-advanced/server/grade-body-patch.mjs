/**
 * grade-body-patch — surgically set/clear a node's LABEL (field F6) or COLOR (field F15) inside a DRX
 * grade Body, WITHOUT going through the lossy generator. Node convention/provenance spec (2026-06-22).
 *
 * Why surgical: the drx generator only re-emits primaries (functional test: it drops Color Warper /
 * curves / windows / keyframes on re-encode). So to change a label/color we must edit the COMPRESSED
 * Body in place: decompress → byte-copy every untouched field verbatim, splice only the F6/F15 string,
 * fix the enclosing length prefixes → recompress. Everything other than the edited string stays
 * byte-identical (lossless), the same philosophy as the offline-ref / reel-name DB patches.
 *
 * Body format: [0x81] + zstd(protobuf). Node tree: root → F1 → F7[] (nodes). Node fields: F6 = label
 * (string), F15 = color (string "ClipColor<Name>"). Absent F6/F15 = no label / no color.
 *
 * patchGradeBody(bodyHex, nodeIndex, { label, color }):
 * label/color: undefined = leave unchanged · null = clear (remove the field) · string = set.
 * color "Blue" is written as "ClipColorBlue"; reading strips the prefix (see drx-parser node.color).
 */

import * as fzstd from 'fzstd';
import nodeZlib from 'node:zlib';
import zstdCodecPkg from 'zstd-codec';
import parserPkg from '../vendor/drx-codec/drx-parser.js';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { NODE_LUT_REF } = require('../vendor/drx-parameters');
const { ProtobufParser } = parserPkg;
const { ZstdCodec } = zstdCodecPkg;

const HAS_NATIVE_ZSTD = typeof nodeZlib.zstdCompressSync === 'function';

// ── varint / field encoders ─────────────────────────────────────────────────
function encodeVarint(n) {
  const out = [];
  let v = n >>> 0 === n ? n : Number(n);
  v = Math.trunc(v);
  do {
    let b = v & 0x7f;
    v = Math.floor(v / 128);
    if (v > 0) b |= 0x80;
    out.push(b);
  } while (v > 0);
  return Buffer.from(out);
}
function encodeLenDelimField(fieldNum, content) {
  const tag = (fieldNum << 3) | 2;
  return Buffer.concat([encodeVarint(tag), encodeVarint(content.length), content]);
}

// ── byte-range rebuild of a protobuf container ───────────────────────────────
// fields = a ProtobufParser._fields array (in wire order, each with.pos relative to `content`).
// replaceMap: Map<fieldEntry, Buffer> — emit these bytes instead of the field's original range.
// removeFieldNums: Set<number> — drop these fields entirely. appends: extra field Buffers at the end.
function rebuildContainer(content, fields, { replaceMap = null, removeFieldNums = null, appends = [] } = {}) {
  const parts = [];
  for (let i = 0; i < fields.length; i++) {
    const f = fields[i];
    const start = f.pos;
    const end = i + 1 < fields.length ? fields[i + 1].pos : content.length;
    if (removeFieldNums && removeFieldNums.has(f.fieldNum)) continue;
    if (replaceMap && replaceMap.has(f)) parts.push(replaceMap.get(f));
    else parts.push(content.subarray(start, end));
  }
  for (const a of appends) parts.push(a);
  return Buffer.concat(parts);
}

// Rebuild a node's content, inserting/replacing fields in ASCENDING field-number order. CRITICAL: Resolve
// writes node fields sorted by field number (F1 F2 F4 F5 F6 F7 F8 F9 F10 F12 F15) and its loader reads the
// label (F6) from its canonical slot (between F5 and F7) — appending F6 at the end means Resolve never sees
// it. So we emit a field-number-ordered merge of the kept fields + the new ones (RE'd live 2026-06-22).
function rebuildNodeSorted(content, fields, removeFieldNums, newFields) {
  const items = [];
  for (let i = 0; i < fields.length; i++) {
    const f = fields[i];
    if (removeFieldNums.has(f.fieldNum)) continue;
    const end = i + 1 < fields.length ? fields[i + 1].pos : content.length;
    items.push({ fieldNum: f.fieldNum, buf: content.subarray(f.pos, end) });
  }
  for (const nf of newFields) items.push(nf); // {fieldNum, buf (tag+len+content)}
  items.sort((a, b) => a.fieldNum - b.fieldNum); // stable (ES2019+) → repeats keep relative order
  return Buffer.concat(items.map((x) => x.buf));
}

function asBuf(x) {
  return Buffer.isBuffer(x) ? x : Buffer.from(x);
}
function parseContent(buf) {
  return new ProtobufParser(buf).parse(12);
}

// ── zstd compress (native Node 22+ → zstd-codec WASM fallback, matching the generator) ──
let _wasm = null;
function getWasm() {
  if (_wasm) return Promise.resolve(_wasm);
  return new Promise((resolve) => {
    ZstdCodec.run((z) => {
      _wasm = new z.Simple();
      resolve(_wasm);
    });
  });
}
async function compress(buf) {
  if (HAS_NATIVE_ZSTD) return nodeZlib.zstdCompressSync(buf);
  const w = await getWasm();
  return Buffer.from(w.compress(new Uint8Array(buf)));
}
export function decompressBody(bodyHex) {
  const buf = Buffer.from(bodyHex, 'hex');
  if (buf[0] !== 0x81) throw new Error('not a DRX grade Body (missing 0x81 prefix)');
  return Buffer.from(fzstd.decompress(new Uint8Array(buf.subarray(1))));
}

/**
 * Set/clear a node's label (F6) and/or color (F15) in a grade Body. Returns the new Body hex.
 * Everything except the edited string(s) is preserved byte-for-byte in the decompressed protobuf.
 */
export async function patchGradeBody(bodyHex, nodeIndex, { label, color } = {}) {
  const dec = decompressBody(bodyHex);
  const root = parseContent(dec);
  const f1Entry = root._fields.find((f) => f.fieldNum === 1 && f.wireType === 2);
  if (!f1Entry) throw new Error('grade Body has no F1 (node container)');
  const f1Content = asBuf(f1Entry.rawValue);
  const f1Parsed = parseContent(f1Content);
  const f7Entries = f1Parsed._fields.filter((f) => f.fieldNum === 7 && f.wireType === 2);
  if (nodeIndex < 0 || nodeIndex >= f7Entries.length) throw new Error(`node ${nodeIndex} out of range (have ${f7Entries.length})`);
  const nodeEntry = f7Entries[nodeIndex];
  const nodeContent = asBuf(nodeEntry.rawValue);
  const nodeParsed = parseContent(nodeContent);

  const removeFieldNums = new Set();
  const newFields = [];
  if (label !== undefined) {
    removeFieldNums.add(6);
    if (label !== null) newFields.push({ fieldNum: 6, buf: encodeLenDelimField(6, Buffer.from(String(label), 'utf8')) });
  }
  if (color !== undefined) {
    removeFieldNums.add(15);
    if (color !== null) newFields.push({ fieldNum: 15, buf: encodeLenDelimField(15, Buffer.from(`ClipColor${color}`, 'utf8')) });
  }

  // Insert F6/F15 in canonical (ascending field-number) order — Resolve's loader is position-sensitive.
  const newNodeContent = rebuildNodeSorted(nodeContent, nodeParsed._fields, removeFieldNums, newFields);
  const newF7 = encodeLenDelimField(7, newNodeContent);
  const newF1Content = rebuildContainer(f1Content, f1Parsed._fields, { replaceMap: new Map([[nodeEntry, newF7]]) });
  const newF1 = encodeLenDelimField(1, newF1Content);
  const newRoot = rebuildContainer(dec, root._fields, { replaceMap: new Map([[f1Entry, newF1]]) });

  const compressed = await compress(newRoot);
  return '81' + Buffer.from(compressed).toString('hex');
}

// ── LUT-node WRITE path (P3, RE'd 2026-07-01 from the p5-1 fixtures) ─────────────
// A node's F9 holds [F1 corrector?][F2 5-byte tail]. A LUT attaches an F1 corrector whose nested
// params carry SLOT_META (varint) + LUT_PATH (F5 string). Byte-exact reconstruction of the captured
// with-LUT fixture confirmed the encoding (see lut-apply round-trip test). Constant wire shape:
//   corrector = F1{ 08 01, 18 01, F6{ F2{ 08 01, F3{SLOT_META param}, F3{LUT_PATH param} } } }
//   SLOT_META param = 08 <id> 12{ 10 <slot> }        (value envelope F2 = varint slot)
//   LUT_PATH  param = 08 <id> 12{ 2a <len> <path> }  (value envelope F5 = string)
function buildLutCorrector(lutPath, slotMeta) {
  const slotEnv = encodeLenDelimField(2, Buffer.concat([Buffer.from([0x10]), encodeVarint(slotMeta)]));
  const slotParam = Buffer.concat([Buffer.from([0x08]), encodeVarint(NODE_LUT_REF.SLOT_META), slotEnv]);
  const pathEnv = encodeLenDelimField(2, encodeLenDelimField(5, Buffer.from(lutPath, 'utf8')));
  const pathParam = Buffer.concat([Buffer.from([0x08]), encodeVarint(NODE_LUT_REF.LUT_PATH), pathEnv]);
  const paramsList = Buffer.concat([Buffer.from([0x08, 0x01]), encodeLenDelimField(3, slotParam), encodeLenDelimField(3, pathParam)]);
  const f6 = encodeLenDelimField(6, encodeLenDelimField(2, paramsList));
  const corrector = Buffer.concat([Buffer.from([0x08, 0x01, 0x18, 0x01]), f6]);
  return encodeLenDelimField(1, corrector); // the F9-inner F1 field bytes
}

const DEFAULT_F9_TAIL = Buffer.from('12050304050612', 'hex'); // the F2 common tail all nodes carry

/**
 * Inject a per-node LUT reference (LUT_PATH + SLOT_META) into a grade Body, replacing any existing
 * LUT corrector on that node. Returns the new Body hex. Everything else is preserved byte-for-byte.
 * @param {string} bodyHex
 * @param {number} nodeIndex
 * @param {{lutPath:string, slotMeta?:number}} opts
 */
export async function injectNodeLut(bodyHex, nodeIndex, { lutPath, slotMeta = 6 } = {}) {
  if (!lutPath || typeof lutPath !== 'string') throw new Error('injectNodeLut: lutPath (string) required');
  const dec = decompressBody(bodyHex);
  const root = parseContent(dec);
  const f1Entry = root._fields.find((f) => f.fieldNum === 1 && f.wireType === 2);
  if (!f1Entry) throw new Error('grade Body has no F1 (node container)');
  const f1Content = asBuf(f1Entry.rawValue);
  const f1Parsed = parseContent(f1Content);
  const f7Entries = f1Parsed._fields.filter((f) => f.fieldNum === 7 && f.wireType === 2);
  if (nodeIndex < 0 || nodeIndex >= f7Entries.length) throw new Error(`node ${nodeIndex} out of range (have ${f7Entries.length})`);
  const nodeEntry = f7Entries[nodeIndex];
  const nodeContent = asBuf(nodeEntry.rawValue);
  const nodeParsed = parseContent(nodeContent);

  const corrector = buildLutCorrector(lutPath, slotMeta);
  // Keep the existing F9 TAIL (F2), drop any prior F1 LUT corrector, prepend the new one.
  const f9Entry = nodeParsed._fields.find((f) => f.fieldNum === 9 && f.wireType === 2);
  let tail = DEFAULT_F9_TAIL;
  if (f9Entry) {
    const f9Content = asBuf(f9Entry.rawValue);
    const f9Parsed = parseContent(f9Content);
    tail = rebuildContainer(f9Content, f9Parsed._fields, { removeFieldNums: new Set([1]) });
  }
  const newF9 = encodeLenDelimField(9, Buffer.concat([corrector, tail]));
  const newNodeContent = rebuildNodeSorted(nodeContent, nodeParsed._fields, new Set([9]), [{ fieldNum: 9, buf: newF9 }]);
  const newF7 = encodeLenDelimField(7, newNodeContent);
  const newF1Content = rebuildContainer(f1Content, f1Parsed._fields, { replaceMap: new Map([[nodeEntry, newF7]]) });
  const newF1 = encodeLenDelimField(1, newF1Content);
  const newRoot = rebuildContainer(dec, root._fields, { replaceMap: new Map([[f1Entry, newF1]]) });
  const compressed = await compress(newRoot);
  return '81' + Buffer.from(compressed).toString('hex');
}

// Read a node's label (F6) + color (F15) straight from a Body — used for read-back verification.
export function readNodeMeta(bodyHex, nodeIndex = 0) {
  const dec = decompressBody(bodyHex);
  const root = parseContent(dec);
  const f1Entry = root._fields.find((f) => f.fieldNum === 1 && f.wireType === 2);
  if (!f1Entry) return null;
  const f1Parsed = parseContent(asBuf(f1Entry.rawValue));
  const f7 = f1Parsed._fields.filter((f) => f.fieldNum === 7 && f.wireType === 2)[nodeIndex];
  if (!f7) return null;
  const node = parseContent(asBuf(f7.rawValue));
  const str = (fn) => {
    const e = node._fields.find((f) => f.fieldNum === fn && f.wireType === 2);
    return e ? asBuf(e.rawValue).toString('utf8') : null;
  };
  const label = str(6);
  const rawColor = str(15);
  return { label: label || null, color: rawColor ? rawColor.replace(/^ClipColor/, '') : null };
}

// Exposed for tests: the field-number order of a node (must stay ascending — Resolve reads positionally).
export function _nodeFieldOrder(bodyHex, nodeIndex = 0) {
  const dec = decompressBody(bodyHex);
  const root = parseContent(dec);
  const f1 = parseContent(asBuf(root._fields.find((f) => f.fieldNum === 1 && f.wireType === 2).rawValue));
  const node = parseContent(asBuf(f1._fields.filter((f) => f.fieldNum === 7 && f.wireType === 2)[nodeIndex].rawValue));
  return node._fields.map((f) => f.fieldNum);
}

// Exposed for the faithful-round-trip self-test (no-op rebuild must reproduce the decompressed bytes).
export function _noopRebuild(bodyHex) {
  const dec = decompressBody(bodyHex);
  const root = parseContent(dec);
  return rebuildContainer(dec, root._fields, {});
}
