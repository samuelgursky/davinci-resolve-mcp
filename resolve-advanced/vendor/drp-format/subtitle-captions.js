/** Resolve 21 caption FieldsBlob codec. Times exposed in timeline frames;
 * f15/16 and f19/20 store 60 ticks/second; f21 is the original frame anchor.
 * Unknown protobuf fields survive byte-for-byte. No source media is touched.
 */
const { unwrapEffectFilters, wrapEffectFilters } = require('./subtitle-style.js');

function varint(value) {
  let n = BigInt(value);
  if (n < 0n) throw new Error('negative protobuf integer');
  const bytes = [];
  do { bytes.push(Number(n & 127n) | (n > 127n ? 128 : 0)); n >>= 7n; } while (n);
  return Buffer.from(bytes);
}
function parse(buf) {
  let p = 0;
  const read = () => {
    let n = 0n;
    for (let i = 0; i < 10 && p < buf.length; i++) {
      const b = buf[p++];
      if (i === 9 && b > 1) throw new Error('protobuf integer overflow');
      n |= BigInt(b & 127) << BigInt(i * 7);
      if (!(b & 128)) return n;
    }
    throw new Error('truncated protobuf integer');
  };
  const out = [];
  while (p < buf.length) {
    const start = p, tag = Number(read()), field = Math.floor(tag / 8), wire = tag % 8;
    if (!Number.isSafeInteger(tag) || !field || field > 536870911) throw new Error('invalid protobuf tag');
    let value, bytes;
    if (wire === 0) value = read();
    else {
      const size = wire === 2 ? Number(read()) : wire === 1 ? 8 : wire === 5 ? 4 : -1;
      if (!Number.isSafeInteger(size) || size < 0 || size > buf.length - p) throw new Error('truncated/unsupported protobuf field');
      bytes = buf.subarray(p, p + size); p += size;
    }
    out.push({ field, wire, value, bytes, raw: buf.subarray(start, p) });
  }
  return out;
}
function field(id, value) {
  return typeof value === 'number'
    ? Buffer.concat([varint(id * 8), varint(value)])
    : Buffer.concat([varint(id * 8 + 2), varint(value.length), value]);
}
function safeNumber(n) {
  const v = Number(n);
  if (!Number.isSafeInteger(v) || v < 0) throw new Error('caption integer outside safe range');
  return v;
}
function message(blob) {
  const env = unwrapEffectFilters(Buffer.from(blob));
  if (env.version !== 2) throw new Error('unsupported caption FieldsBlob version');
  const outer = parse(env.protobuf), entries = outer.filter((r) => r.field === 1 && r.wire === 2);
  if (entries.length !== 1) throw new Error('expected exactly one caption message');
  return { outer, entry: entries[0], inner: parse(entries[0].bytes) };
}
function decodeCaption(blob, { name = '', start, end, fps }) {
  if (!Number.isFinite(fps) || fps <= 0) throw new Error('positive timeline fps required');
  if (!blob || !blob.length) return { text: name.trimStart(), start, end, words: [], originalWords: [], anchor: null };
  const { inner } = message(blob);
  const anchors = inner.filter((r) => r.field === 21 && r.wire === 0);
  if (anchors.length > 1) throw new Error('multiple caption anchors');
  const anchor = anchors.length ? safeNumber(anchors[0].value) : start;
  const readWords = (textField, startField, endField) => {
    const strings = inner.filter((r) => r.field === textField && r.wire === 2).map((r) => r.bytes.toString('utf8'));
    const times = (id) => inner.filter((r) => r.field === id).flatMap((r) => {
      if (r.wire === 0) return [safeNumber(r.value)];
      throw new Error(`unsupported caption timing wire type for field ${id}`);
    });
    const starts = times(startField), ends = times(endField);
    return { strings, starts, ends, words: strings.map((text, i) => ({ text: text.trimStart(),
      start: starts[i] == null ? null : starts[i] * fps / 60 + start - anchor,
      end: ends[i] == null ? null : ends[i] * fps / 60 + start - anchor })) };
  };
  const current = readWords(14, 15, 16), original = readWords(18, 19, 20);
  const issues = [];
  for (const [label, data] of [['current', current], ['original', original]]) {
    if (data.strings.length !== data.starts.length || data.strings.length !== data.ends.length) issues.push(`${label}_word_count_mismatch`);
  }
  return { text: current.strings.length ? current.strings.join('').trimStart() : name.trimStart(),
    start, end, words: current.words, originalWords: original.words, anchor, decodeIssues: issues };
}
function encodeCaption(blob, caption, fps, { fresh = false } = {}) {
  const { outer, entry, inner } = message(blob);
  const replaced = new Set([14, 15, 16, 21, ...(fresh ? [18, 19, 20] : [])]);
  const parts = inner.filter((r) => !replaced.has(r.field)).map((r) => r.raw);
  for (const w of caption.words) parts.push(field(14, Buffer.from(` ${w.text}`, 'utf8')));
  for (const w of caption.words) parts.push(field(15, Math.round(w.start * 60 / fps)));
  for (const w of caption.words) parts.push(field(16, Math.round(w.end * 60 / fps)));
  parts.push(field(21, caption.start));
  return wrapEffectFilters(Buffer.concat(outer.map((r) => r === entry ? field(1, Buffer.concat(parts)) : r.raw)));
}

function checkCaptions(captions, { maxCharacters = 24, fps = 30 } = {}) {
  const issues = [], epsilon = 1e-6;
  const sorted = [...captions].sort((a, b) => a.start - b.start);
  for (let i = 0; i < sorted.length; i++) {
    const c = sorted[i], add = (code, extra = {}) => issues.push({ id: c.id, code, ...extra });
    const boundaryTolerance = fps / 120 + epsilon; // nearest 60 Hz tick
    if (!(c.end > c.start)) add('invalid_caption_duration');
    if (i && c.start < sorted[i - 1].end) add('caption_overlap', { previousId: sorted[i - 1].id });
    const length = Math.max(...c.text.split(/\r?\n/).map((line) => [...line].length));
    if (length > maxCharacters) add('overflow_length', { characters: length, maxCharacters, severity: 'warning' });
    for (const code of c.decodeIssues || []) add(code);
    if (!c.words.length) add('missing_word_timings');
    let cursor = c.start;
    c.words.forEach((w, word) => {
      if (!Number.isFinite(w.start) || !Number.isFinite(w.end)) { add('missing_word_timing', { word }); return; }
      if (w.end <= w.start) add('zero_or_negative_word_duration', { word });
      const tolerance = word === 0 ? boundaryTolerance : epsilon;
      if (w.start > cursor + tolerance) add('word_gap', { word, start: cursor, end: w.start });
      if (w.start < cursor - tolerance) add('word_overlap', { word });
      if (w.start < c.start - boundaryTolerance || w.end > c.end + boundaryTolerance) add('word_outside_caption', { word });
      cursor = Math.max(cursor, w.end);
    });
    if (c.words.length && cursor < c.end - boundaryTolerance) add('word_gap', { start: cursor, end: c.end });
  }
  return { ok: issues.length === 0, issues, fps, maxCharacters,
    note: 'Length is a heuristic, not a pixel-boundary or render check. Review burned-in frames.' };
}
module.exports = { decodeCaption, encodeCaption, checkCaptions, parse, field };
