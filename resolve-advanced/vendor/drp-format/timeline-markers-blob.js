/**
 * timeline-markers-blob — encode/decode TIMELINE markers as the
 * Sm2SequenceLockableBlob.FieldsBlob that lives in project.xml.
 *
 * Ground truth (harvested live from Studio 19.1.3.7, all 16 colors + custom
 * data + durations, decoded round-trip against the API's own readback):
 *
 *   FieldsBlob = keyed-dict { "BlobData": bytes }
 *   BlobData   = [u32BE 10001][u32BE innerLen][0x81][zstd frame]
 *   zstd frame = magic 28b52ffd + single-segment header + RAW block(s)
 *                (Resolve itself emits raw-block zstd for small payloads —
 *                 accepted on import; no real compressor needed)
 *   payload    = protobuf: field2 { repeated field1 MarkerEntry }
 *   MarkerEntry= f1 varint frameRelative, f2 bytes {
 *                  [u32BE 2][u32BE innerLen] f1 bytes {
 *                    f1 varint colorBit,
 *                    f3 string note, f3 string durationString, f3 string name,
 *                    f6 string customData (present only when non-empty)
 *                  } }
 *
 * Marker frames are RELATIVE to the timeline start (frame 0 = first frame),
 * matching the scripting API's marker frame space. The blob attaches inside
 * project.xml's <LocableBlobSet> (Resolve's own spelling) with
 * <BlobOwner> = the timeline's Sm2Sequence DbId (the same uuid every track's
 * <Sequence> references).
 *
 * Color bits (measured, one marker per color): sequential powers of two with
 * 256 unassigned. This supersedes marker-encoder.js, whose map was wrong for
 * Yellow/Purple/Lavender and whose emitted bytes never matched a real export.
 *
 * @module drp-format/timeline-markers-blob
 */

const { encodeKeyedDict, decodeKeyedDict } = require('./keyed-dict');

const MARKER_COLOR_BITS = {
  Blue: 2, Cyan: 4, Green: 8, Yellow: 16, Red: 32, Pink: 64, Purple: 128,
  Fuchsia: 512, Rose: 1024, Lavender: 2048, Sky: 4096, Mint: 8192,
  Lemon: 16384, Sand: 32768, Cocoa: 65536, Cream: 131072,
};
const BITS_TO_COLOR = Object.fromEntries(Object.entries(MARKER_COLOR_BITS).map(([k, v]) => [v, k]));

function varint(n) {
  const out = [];
  let v = n >>> 0;
  do { out.push((v & 0x7f) | (v > 0x7f ? 0x80 : 0)); v >>>= 7; } while (v);
  return Buffer.from(out);
}
const lenDelim = (field, payload) => Buffer.concat([varint((field << 3) | 2), varint(payload.length), payload]);
const varField = (field, n) => Buffer.concat([varint(field << 3), varint(n)]);

function encodeMarkerEntry(m) {
  const colorBit = MARKER_COLOR_BITS[m.color] ?? MARKER_COLOR_BITS.Blue;
  const strs = [m.note ?? '', String(m.duration ?? 1), m.name ?? ''];
  const body = Buffer.concat([
    varField(1, colorBit),
    ...strs.map((s) => lenDelim(3, Buffer.from(s, 'utf8'))),
    ...(m.customData ? [lenDelim(6, Buffer.from(m.customData, 'utf8'))] : []),
  ]);
  const inner = lenDelim(1, body);
  const head = Buffer.alloc(8);
  head.writeUInt32BE(2, 0);
  head.writeUInt32BE(inner.length, 4);
  const wrapped = Buffer.concat([head, inner]);
  return lenDelim(1, Buffer.concat([varField(1, m.frame), lenDelim(2, wrapped)]));
}

/** zstd single-segment frame with one RAW block (no compression). */
function zstdRawFrame(payload) {
  const magic = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);
  let header;
  if (payload.length <= 255) {
    header = Buffer.from([0x20, payload.length]); // single-segment, 1-byte FCS
  } else {
    header = Buffer.alloc(5);
    header[0] = 0xa0; // single-segment, 4-byte FCS
    header.writeUInt32LE(payload.length, 1);
  }
  const block = Buffer.alloc(3);
  block.writeUIntLE((payload.length << 3) | 1, 0, 3); // last=1, type=raw
  return Buffer.concat([magic, header, block, payload]);
}

function zstdRawInflate(buf) {
  if (buf.readUInt32LE(0) !== 0xfd2fb528) throw new Error('timeline-markers-blob: not a zstd frame');
  const fhd = buf[4];
  const single = (fhd >> 5) & 1;
  const fcsCode = fhd >> 6;
  let o = 5 + (single ? [1, 2, 4, 8][fcsCode] : [0, 2, 4, 8][fcsCode]);
  if (fhd & 0x03) throw new Error('timeline-markers-blob: dictionary frames unsupported');
  const out = [];
  for (;;) {
    const bh = buf.readUIntLE(o, 3); o += 3;
    const last = bh & 1, type = (bh >> 1) & 3, size = bh >> 3;
    if (type === 0) { out.push(buf.subarray(o, o + size)); o += size; }
    else if (type === 1) { out.push(Buffer.alloc(size, buf[o])); o += 1; }
    else throw new Error('timeline-markers-blob: compressed zstd block — use a real zstd decoder');
    if (last) break;
  }
  return Buffer.concat(out);
}

/**
 * Encode timeline markers → Sm2SequenceLockableBlob FieldsBlob buffer.
 * @param {Array<{frame:number,color?:string,name?:string,note?:string,duration?:number,customData?:string}>} markers
 *   frame is timeline-RELATIVE (0 = first frame of the timeline).
 */
function encodeTimelineMarkersBlob(markers) {
  for (const m of markers) {
    if (!Number.isInteger(m.frame) || m.frame < 0) throw new TypeError('encodeTimelineMarkersBlob: marker.frame must be a non-negative integer (timeline-relative)');
    if (m.color && !MARKER_COLOR_BITS[m.color]) {
      throw new Error(`encodeTimelineMarkersBlob: unknown color "${m.color}" (known: ${Object.keys(MARKER_COLOR_BITS).join(', ')})`);
    }
  }
  const entries = [...markers].sort((a, b) => b.frame - a.frame).map(encodeMarkerEntry);
  const pb = lenDelim(2, Buffer.concat(entries));
  const frame = zstdRawFrame(pb);
  const head = Buffer.alloc(8);
  head.writeUInt32BE(10001, 0);
  head.writeUInt32BE(frame.length + 1, 4);
  const blobData = Buffer.concat([head, Buffer.from([0x81]), frame]);
  return encodeKeyedDict({ hdr: 1, entries: [
    { key: 'BlobData', type: 0x0c, subType: 0, value: blobData.toString('hex') },
  ] });
}

/** Decode a Sm2SequenceLockableBlob FieldsBlob → markers (raw/RLE zstd only). */
function decodeTimelineMarkersBlob(buf) {
  const d = decodeKeyedDict(buf);
  const bd = d.entries.find((e) => e.key === 'BlobData');
  if (!bd) throw new Error('decodeTimelineMarkersBlob: no BlobData entry');
  const val = Buffer.from(bd.value, 'hex');
  if (val.readUInt32BE(0) !== 10001 || val[8] !== 0x81) throw new Error('decodeTimelineMarkersBlob: unexpected BlobData framing');
  const pb = zstdRawInflate(val.subarray(9));
  let o = 0;
  const rv = () => { let v = 0, s = 0; for (;;) { const b = pb[o++]; v |= (b & 0x7f) << s; if (!(b & 0x80)) return v >>> 0; s += 7; } };
  const markers = [];
  if (pb[o] === 0x12) { o++; rv(); }
  while (o < pb.length && pb[o] === 0x0a) {
    o++; const el = rv(); const end = o + el;
    const m = { frame: null, color: null, note: '', duration: 1, name: '', customData: '' };
    if (pb[o] === 0x08) { o++; m.frame = rv(); }
    if (pb[o] === 0x12) {
      o++; rv(); o += 8;
      if (pb[o] === 0x0a) { o++; rv(); }
      if (pb[o] === 0x08) { o++; m.color = BITS_TO_COLOR[rv()] ?? null; }
      const strs = [];
      while (o < end && pb[o] === 0x1a) { o++; const sl = rv(); strs.push(pb.subarray(o, o + sl).toString('utf8')); o += sl; }
      [m.note = '', , m.name = ''] = strs;
      m.duration = parseInt(strs[1] ?? '1', 10) || 1;
      if (o < end && pb[o] === 0x32) { o++; const sl = rv(); m.customData = pb.subarray(o, o + sl).toString('utf8'); o += sl; }
    }
    o = end;
    markers.push(m);
  }
  return markers;
}

module.exports = { encodeTimelineMarkersBlob, decodeTimelineMarkersBlob, MARKER_COLOR_BITS };
