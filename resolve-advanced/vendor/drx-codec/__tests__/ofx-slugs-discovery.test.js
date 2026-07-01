/**
 * P2.1 + P2.2 — OFX plugin slug discovery against captured fixtures.
 *
 * Each fixture is a Resolve-exported DRX gallery still with one
 * ResolveFX plugin applied. The test parses the DRX body, locates
 * the F7.F10 tool list, runs extractOFXTools, and asserts the
 * pluginId (slug) matches what RESOLVEFX.SLUGS exposes.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const zlib = require('node:zlib');

const drxParams = require('../../drx-parameters');
const { extractOFXTools } = require('../extract-ofx-params');

const FIXTURES = path.join(__dirname, 'fixtures');

// Tiny inline proto walker — locates F1.F7.F10 buffer in the body so
// extractOFXTools has its expected input shape.
function readVarint(buf, off) {
  let v = 0n, shift = 0n, b;
  do {
    if (off >= buf.length) throw new Error('truncated varint');
    b = buf[off++];
    v |= BigInt(b & 0x7f) << shift;
    shift += 7n;
  } while (b & 0x80);
  return [v, off];
}

function readFields(buf) {
  const out = [];
  let off = 0;
  while (off < buf.length) {
    let tag;
    try { [tag, off] = readVarint(buf, off); }
    catch (e) { break; }
    const fieldNum = Number(tag >> 3n);
    const wireType = Number(tag & 7n);
    if (wireType === 0) {
      const [v, o2] = readVarint(buf, off);
      out.push({ fieldNum, wireType, value: v });
      off = o2;
    } else if (wireType === 2) {
      const [len, o2] = readVarint(buf, off);
      const L = Number(len);
      out.push({ fieldNum, wireType, value: buf.slice(o2, o2 + L) });
      off = o2 + L;
    } else if (wireType === 1) {
      out.push({ fieldNum, wireType, value: buf.slice(off, off + 8) });
      off += 8;
    } else if (wireType === 5) {
      out.push({ fieldNum, wireType, value: buf.slice(off, off + 4) });
      off += 4;
    } else { break; }
  }
  return out;
}

function findF10Buffer(decompressedBody) {
  const root = readFields(decompressedBody);
  for (const rootField of root) {
    if (rootField.fieldNum !== 1 || rootField.wireType !== 2) continue;
    const nodeBlock = readFields(rootField.value);
    for (const nodeField of nodeBlock) {
      if (nodeField.fieldNum !== 7 || nodeField.wireType !== 2) continue;
      const toolList = readFields(nodeField.value);
      for (const tf of toolList) {
        if (tf.fieldNum === 10 && tf.wireType === 2) return tf.value;
      }
    }
  }
  return null;
}

async function loadOfx(fixtureName) {
  const xml = fs.readFileSync(path.join(FIXTURES, fixtureName), 'utf8');
  const m = xml.match(/<Body>([0-9a-f]+)<\/Body>/);
  if (!m) throw new Error('no Body in fixture');
  const raw = Buffer.from(m[1], 'hex');
  const zstdPayload = raw[0] === 0x81 ? raw.slice(1) : raw;
  // Node 18+ has zstdDecompressSync via node:zlib.
  const decompressed = typeof zlib.zstdDecompressSync === 'function'
    ? zlib.zstdDecompressSync(zstdPayload)
    : await zstdDecompressViaCodec(zstdPayload);
  const f10 = findF10Buffer(decompressed);
  if (!f10) throw new Error('no F7.F10 buffer found');
  return extractOFXTools(f10);
}

async function zstdDecompressViaCodec(payload) {
  const { ZstdCodec } = require('zstd-codec');
  return new Promise((res) => {
    ZstdCodec.run((zstd) => {
      const simple = new zstd.Simple();
      res(Buffer.from(simple.decompress(payload)));
    });
  });
}

// ─── Slug discovery tests ────────────────────────────────────────────────

const SLUG_FIXTURES = [
  { fixture: 'p2-1-filmgrain.drx',       expectedSlug: drxParams.RESOLVEFX.SLUGS.FILM_GRAIN },
  { fixture: 'p2-1-face-refinement.drx', expectedSlug: drxParams.RESOLVEFX.SLUGS.FACE_REFINEMENT2 },
  { fixture: 'p2-1-lens-flare.drx',      expectedSlug: drxParams.RESOLVEFX.SLUGS.LENS_FLARE_V2 },
  { fixture: 'p2-1-glow.drx',            expectedSlug: drxParams.RESOLVEFX.SLUGS.GLOW },
  { fixture: 'p2-3-beauty-25.drx',       expectedSlug: drxParams.RESOLVEFX.SLUGS.BEAUTY },
  { fixture: 'p2-3-beauty-75.drx',       expectedSlug: drxParams.RESOLVEFX.SLUGS.BEAUTY },
];

for (const { fixture, expectedSlug } of SLUG_FIXTURES) {
  test(`slug discovery: ${fixture} → ${expectedSlug}`, async () => {
    const tools = await loadOfx(fixture);
    assert.equal(tools.length, 1, 'one OFX tool per fixture');
    assert.equal(tools[0].pluginId, expectedSlug);
    assert.equal(tools[0].enabled, true);
    assert.equal(tools[0].marker, 0x4F4659, 'OFY marker present');
  });
}

// ─── Known-params smoke (P2.2 partial coverage) ─────────────────────────

test('KNOWN_PARAMS: each slug entry maps to a parameter list', () => {
  for (const slug of Object.values(drxParams.RESOLVEFX.SLUGS)) {
    const params = drxParams.RESOLVEFX.KNOWN_PARAMS[slug];
    assert.ok(Array.isArray(params), `slug "${slug}" has KNOWN_PARAMS`);
    assert.ok(params.length >= 1, `slug "${slug}" has at least one param`);
    assert.ok(params.includes('resolvefxVersion'),
      `slug "${slug}" should include the resolvefxVersion canary param`);
  }
});

// ─── Beauty round-trip canary (P2.3 — proves the encoding side) ─────────

test('beauty round-trip: 25 and 75 produce same slug + same param set', async () => {
  const tools25 = await loadOfx('p2-3-beauty-25.drx');
  const tools75 = await loadOfx('p2-3-beauty-75.drx');
  assert.equal(tools25[0].pluginId, tools75[0].pluginId);
  assert.equal(tools25[0].marker, tools75[0].marker);
  // The params keys should match exactly (only values should differ).
  const keys25 = Object.keys(tools25[0].params).sort();
  const keys75 = Object.keys(tools75[0].params).sort();
  assert.deepEqual(keys25, keys75,
    'same plugin with different param values yields same key set');
});
