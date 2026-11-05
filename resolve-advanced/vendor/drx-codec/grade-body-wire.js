/**
 * grade-body-wire — path-directed edits of a decompressed grade body (.drx <Body>, or
 * Project.db ListMgt::LmVersion.Body). Everything outside the edited path is carried
 * byte-exact; parents are re-encoded with their new lengths.
 *
 * Shared by grade-keyframes.js and magic-mask-author.js.
 *
 * @module drx-codec/grade-body-wire
 */

const zlib = require('zlib');
const { decodeProtobuf, encodeProtobuf } = require('../drp-format/protobuf-wire');

/** <Body> hex (0x81 = zstd, 0x80 = stored) → raw protobuf Buffer. */
function decodeBody(hex) {
  const b = Buffer.from(String(hex).replace(/[^0-9a-fA-F]/g, ''), 'hex');
  if (b[0] === 0x80) return b.slice(1);
  if (b[0] !== 0x81) throw new Error(`grade body: unknown magic 0x${b[0].toString(16)}`);
  if (typeof zlib.zstdDecompressSync !== 'function') throw new Error('grade body: needs Node 22+ (zlib zstd)');
  return zlib.zstdDecompressSync(b.slice(1));
}

/** raw protobuf Buffer → <Body> hex (0x81 + zstd), upper-case like Resolve writes it. */
function encodeBody(raw) {
  if (typeof zlib.zstdCompressSync !== 'function') throw new Error('grade body: needs Node 22+ (zlib zstd)');
  return Buffer.concat([Buffer.from([0x81]), zlib.zstdCompressSync(raw)]).toString('hex').toUpperCase();
}

const bodyHexOf = (xml) => {
  const m = String(xml).match(/<Body>([0-9a-fA-F]+)<\/Body>/);
  if (!m) throw new Error('no <Body> in .drx');
  return m[1];
};
const withBodyHex = (xml, hex) => String(xml).replace(/<Body>[0-9a-fA-F]+<\/Body>/, `<Body>${hex}</Body>`);

/** True when a decoded message carries varint field 1 == n (corrector type, tool id, ...). */
const hasF1 = (n) => (fields) => fields.some((x) => x.field === 1 && x.wire === 0 && Number(x.value) === n);

/**
 * Edit the message at `path` inside `buf`. A path step is a field number, or
 * { field, where(fields) } to pick among repeated fields. `fn(fields)` mutates the
 * leaf's field list in place. Every match of a step is visited; a step that matches
 * nothing throws (so a layout drift fails loudly instead of writing nothing).
 */
function editAt(buf, path, fn) {
  const fields = decodeProtobuf(buf);
  if (!path.length) { fn(fields); return encodeProtobuf(fields); }
  const [step, ...rest] = path;
  const field = typeof step === 'number' ? step : step.field;
  const where = typeof step === 'number' ? () => true : step.where;
  let hits = 0;
  for (const f of fields) {
    if (f.field !== field || f.wire !== 2) continue;
    if (!where(decodeProtobuf(f.value))) continue;
    f.value = editAt(f.value, rest, fn);
    hits++;
  }
  if (!hits) throw new Error(`grade body: path step F${field} not found`);
  return encodeProtobuf(fields);
}

/** Read the field list of the (first) message at `path`. */
function readAt(buf, path) {
  let out = null;
  editAt(buf, path, (fields) => { if (!out) out = fields.map((f) => ({ ...f })); });
  return out;
}

const float32 = (v) => { const b = Buffer.alloc(4); b.writeFloatLE(v, 0); return b; };

module.exports = { decodeBody, encodeBody, bodyHexOf, withBodyHex, hasF1, editAt, readAt, float32 };
