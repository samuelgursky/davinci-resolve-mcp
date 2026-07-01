/**
 * P1.6 — extractOFXParams tests.
 *
 * Round-trips the F7.F10 OFX tool-list encoding from the generator's
 * buildOFXToolEntry through extractOFXParams / extractOFXTools.
 *
 * Strategy: drive the encoder helpers directly (protoBytes / protoVarint
 * / protoFloat64), assemble the wire bytes the way buildOFXToolEntry
 * does, then verify the decoder recovers pluginId, instanceId, enabled,
 * and each named param.
 *
 * Film Grain coverage at minimum per ledger; other plugins land when
 * P2.1 expands the tool registry.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { extractOFXParams, extractOFXTools, _internals } = require('../extract-ofx-params');

// ─── Mini protobuf encoder helpers (mirror drx-generator.js) ─────────────

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

function protoVarint(fieldNum, value) {
  const tag = (fieldNum << 3) | 0;
  return Buffer.concat([encVarint(tag), encVarint(value)]);
}

function protoFloat64(fieldNum, value) {
  const tag = (fieldNum << 3) | 1;
  const buf = Buffer.alloc(8);
  buf.writeDoubleLE(value, 0);
  return Buffer.concat([encVarint(tag), buf]);
}

function protoBytes(fieldNum, data) {
  const tag = (fieldNum << 3) | 2;
  return Buffer.concat([encVarint(tag), encVarint(data.length), data]);
}

// Encode one OFX tool's F7.F10 entry (the F1-wrapped form), matching
// the generator's buildOFXToolEntry F2.F21 container.
function encodeOFXEntry(pluginId, params, opts = {}) {
  const instanceId = opts.instanceId || 'OfxImageEffectContext_test_abc';
  const enabled = opts.enabled === undefined ? 1 : (opts.enabled ? 1 : 0);

  const paramEntries = [];
  for (const [name, value] of Object.entries(params)) {
    const nameBuf = Buffer.from(name, 'utf-8');
    let valueBuf;
    if (typeof value === 'string') {
      valueBuf = protoBytes(5, Buffer.from(value, 'utf-8'));
    } else {
      valueBuf = protoFloat64(2, value);
    }
    paramEntries.push(protoBytes(5, Buffer.concat([
      protoBytes(1, nameBuf),
      protoBytes(2, valueBuf),
    ])));
  }

  const ofxContainer = protoBytes(21, Buffer.concat([
    protoVarint(1, 0x4F4659),
    protoBytes(2, Buffer.from(pluginId, 'utf-8')),
    protoBytes(3, Buffer.from(instanceId, 'utf-8')),
    protoVarint(4, enabled),
    ...paramEntries,
  ]));

  // Each F10 entry is wrapped in F1 (the F1=2 marker is a separate entry).
  return protoBytes(1, Buffer.concat([
    protoBytes(2, ofxContainer),
  ]));
}

function encodeToolList(entries) {
  return Buffer.concat(entries);
}

// Standard node marker — not an OFX tool, should be ignored by extractor.
const NODE_MARKER = protoBytes(1, Buffer.concat([
  protoVarint(1, 0xC0000001),
  protoBytes(2, protoVarint(2, 2)),
]));

test('extractOFXParams: Film Grain plugin round-trips', () => {
  const input = {
    pluginId: 'com.blackmagicdesign.resolvefx.filmgrain',
    params: {
      inMean: 0.5,
      inSize: 1.0,
      inResponse: 'linear',
    },
  };
  const toolList = encodeToolList([
    NODE_MARKER,
    encodeOFXEntry(input.pluginId, input.params),
  ]);
  const out = extractOFXParams(toolList);
  assert.ok(out);
  assert.equal(out.pluginId, input.pluginId);
  assert.ok(out.enabled);
  assert.equal(out.params.inMean, 0.5);
  assert.equal(out.params.inSize, 1.0);
  assert.equal(out.params.inResponse, 'linear');
});

test('extractOFXTools: returns all tools (node marker filtered out)', () => {
  const list = encodeToolList([
    NODE_MARKER,
    encodeOFXEntry('com.blackmagicdesign.resolvefx.filmgrain', { inMean: 0.5 }),
    encodeOFXEntry('com.blackmagicdesign.resolvefx.beauty', { intensity: 0.3 }),
  ]);
  const tools = extractOFXTools(list);
  assert.equal(tools.length, 2);
  assert.equal(tools[0].pluginId, 'com.blackmagicdesign.resolvefx.filmgrain');
  assert.equal(tools[1].pluginId, 'com.blackmagicdesign.resolvefx.beauty');
});

test('extractOFXParams: enabled=false flag round-trips', () => {
  const list = encodeToolList([
    encodeOFXEntry('com.blackmagicdesign.resolvefx.filmgrain', { inMean: 0.5 }, { enabled: false }),
  ]);
  const out = extractOFXParams(list);
  assert.equal(out.enabled, false);
});

test('extractOFXParams: instanceId round-trips', () => {
  const customId = 'OfxImageEffectContext_2026_xyz';
  const list = encodeToolList([
    encodeOFXEntry('com.blackmagicdesign.resolvefx.filmgrain', {},
      { instanceId: customId }),
  ]);
  const out = extractOFXParams(list);
  assert.equal(out.instanceId, customId);
});

test('extractOFXParams: float64 + string params coexist', () => {
  const params = {
    inMean: 0.42,
    inResponse: 'sRGB',
    inSize: 1.5,
    inLayer: 'green',
  };
  const list = encodeToolList([
    encodeOFXEntry('com.blackmagicdesign.resolvefx.filmgrain', params),
  ]);
  const out = extractOFXParams(list);
  for (const [k, v] of Object.entries(params)) {
    assert.equal(out.params[k], v, `${k}: got ${out.params[k]}`);
  }
});

test('extractOFXParams: returns null on empty tool list', () => {
  assert.equal(extractOFXParams(Buffer.alloc(0)), null);
});

test('extractOFXParams: returns null on tool list with only node marker', () => {
  const list = encodeToolList([NODE_MARKER]);
  assert.equal(extractOFXParams(list), null);
});

test('extractOFXParams: rejects buffers without OFY marker', () => {
  const noMarker = protoBytes(1, Buffer.concat([
    protoBytes(2, protoBytes(21, Buffer.concat([
      protoBytes(2, Buffer.from('com.fake', 'utf-8')),
    ]))),
  ]));
  const list = encodeToolList([noMarker]);
  assert.equal(extractOFXParams(list), null);
});

test('extractOFXParams: handles malformed input gracefully', () => {
  assert.equal(extractOFXParams(null), null);
  assert.equal(extractOFXParams(undefined), null);
  assert.equal(extractOFXParams('not a buffer'), null);
  assert.equal(extractOFXParams(42), null);
});

test('extractOFXTools: empty tool list returns []', () => {
  assert.deepEqual(extractOFXTools(Buffer.alloc(0)), []);
  assert.deepEqual(extractOFXTools(null), []);
});

test('internals.OFY_MARKER: matches the registry constant', () => {
  assert.equal(_internals.OFY_MARKER, 0x4F4659);
});

test('internals.decodeParamEntry: float64 + string round-trip', () => {
  const entry = Buffer.concat([
    protoBytes(1, Buffer.from('inMean', 'utf-8')),
    protoBytes(2, protoFloat64(2, 0.5)),
  ]);
  const { name, value } = _internals.decodeParamEntry(entry);
  assert.equal(name, 'inMean');
  assert.equal(value, 0.5);

  const strEntry = Buffer.concat([
    protoBytes(1, Buffer.from('inResponse', 'utf-8')),
    protoBytes(2, protoBytes(5, Buffer.from('sRGB', 'utf-8'))),
  ]);
  const { name: n2, value: v2 } = _internals.decodeParamEntry(strEntry);
  assert.equal(n2, 'inResponse');
  assert.equal(v2, 'sRGB');
});
