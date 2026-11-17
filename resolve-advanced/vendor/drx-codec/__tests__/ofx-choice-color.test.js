/**
 * OFX parameter value encodings beyond float64 / int / string: CHOICE menus and
 * RGB colors, as Resolve 19.1.3 writes them in a node's OFX container (measured
 * on stills exported from a node with a choice parameter set to non-default
 * indices, and a color parameter set to 128/255 grey).
 *
 *   choice: value F2 -> F4 { F1 = zigzag varint(index) }. Index 0 is stored as an
 *           EMPTY F4 (proto3 drops the zero), and a parameter left at its
 *           default is not stored at all (no F5 entry).
 *   color:  value F2 -> F7 { F1, F2, F3 = float32 r, g, b (F4 = a when present) }.
 *
 * Generic: indices and components only. What an index MEANS is the plugin's own
 * menu, which is not this library's business.
 */
const test = require('node:test');
const assert = require('node:assert/strict');

const { extractOFXTools, _internals } = require('../extract-ofx-params');

function encVarint(value) {
  let n = BigInt(value);
  const bytes = [];
  while (n > 0x7fn) {
    bytes.push(Number((n & 0x7fn) | 0x80n));
    n >>= 7n;
  }
  bytes.push(Number(n & 0x7fn));
  return Buffer.from(bytes);
}
const tag = (f, w) => encVarint((f << 3) | w);
const bytesField = (f, buf) => Buffer.concat([tag(f, 2), encVarint(buf.length), buf]);
const varintField = (f, v) => Buffer.concat([tag(f, 0), encVarint(v)]);
const f32 = (f, v) => { const b = Buffer.alloc(4); b.writeFloatLE(v); return Buffer.concat([tag(f, 5), b]); };
const f64 = (f, v) => { const b = Buffer.alloc(8); b.writeDoubleLE(v); return Buffer.concat([tag(f, 1), b]); };
const zigzag = (n) => (n << 1) ^ (n >> 31);
const entry = (name, valueBuf) => Buffer.concat([bytesField(1, Buffer.from(name)), bytesField(2, valueBuf)]);

test('choice: F2.F4.F1 zigzag varint decodes to {choice: index}', () => {
  // The exact bytes Resolve wrote for index 10: 22 02 08 14.
  assert.deepEqual(Buffer.from('22020814', 'hex'), bytesField(4, varintField(1, zigzag(10))));
  assert.deepEqual(_internals.decodeParamEntry(entry('aspect', Buffer.from('22020814', 'hex'))), { name: 'aspect', value: { choice: 10 } });
  assert.deepEqual(_internals.decodeParamEntry(entry('aspect', Buffer.from('22020820', 'hex'))).value, { choice: 16 });
});

test('choice: an empty F4 is index 0, not "no value"', () => {
  assert.deepEqual(_internals.decodeParamEntry(entry('version', Buffer.from('2200', 'hex'))).value, { choice: 0 });
});

test('color: F2.F7 float32 components decode to {rgb: [r, g, b]}', () => {
  // Resolve's bytes for 128/255 grey: 3a 0f 0d <f32> 15 <f32> 1d <f32>.
  const grey = Buffer.from('3a0f0d8180003f158180003f1d8180003f', 'hex');
  const v = _internals.decodeParamEntry(entry('fill', grey)).value;
  assert.ok(v && Array.isArray(v.rgb) && v.rgb.length === 3);
  for (const c of v.rgb) assert.ok(Math.abs(c - 128 / 255) < 1e-6, `component ${c}`);
  const rgba = bytesField(7, Buffer.concat([f32(1, 1), f32(2, 0.5), f32(3, 0.25), f32(4, 0.75)]));
  assert.deepEqual(_internals.decodeParamEntry(entry('fill', rgba)).value, { rgb: [1, 0.5, 0.25], alpha: 0.75 });
});

test('null controls: float64, int and string values decode as before', () => {
  assert.equal(_internals.decodeParamEntry(entry('scale', f64(2, 90))).value, 90);
  assert.deepEqual(_internals.decodeParamEntry(entry('n', varintField(3, 4))).value, { int: 4 });
  assert.equal(_internals.decodeParamEntry(entry('s', bytesField(5, Buffer.from('x')))).value, 'x');
  // An unknown wrapped field is still "no value", never guessed as a choice or color.
  assert.equal(_internals.decodeParamEntry(entry('u', varintField(9, 1))).value, null);
});

test('end to end: a container with a choice and a color comes back through extractOFXTools', () => {
  const container = Buffer.concat([
    varintField(1, 0x4f4659),
    bytesField(2, Buffer.from('com.example.plugin')),
    bytesField(3, Buffer.from('inst-1')),
    varintField(4, 1),
    bytesField(5, entry('aspect', Buffer.from('22020814', 'hex'))),
    bytesField(5, entry('fill', bytesField(7, Buffer.concat([f32(1, 0.5), f32(2, 0.5), f32(3, 0.5)])))),
    bytesField(5, entry('scale', f64(2, 90))),
  ]);
  const toolEntry = Buffer.concat([varintField(1, 2), bytesField(2, bytesField(21, container))]);
  const tools = extractOFXTools(bytesField(1, toolEntry));
  assert.equal(tools.length, 1);
  assert.deepEqual(tools[0].params, { aspect: { choice: 10 }, fill: { rgb: [0.5, 0.5, 0.5] }, scale: 90 });
});
