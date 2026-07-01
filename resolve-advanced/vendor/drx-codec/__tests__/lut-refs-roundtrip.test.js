/**
 * P5.1 — extract-lut-refs tests against captured Resolve 21 fixtures.
 *
 * Two fixtures captured 2026-06-19 from a paired Resolve session
 * (Session 30): same clip + same project, one DRX with no LUT on the
 * node and one with a built-in LUT applied. The byte-diff between the
 * two Bodies is what reverse-engineered the encoding.
 *
 *   packages/drx/drx-codec/__tests__/fixtures/p5-1-node-no-lut.drx
 *   packages/drx/drx-codec/__tests__/fixtures/p5-1-node-with-lut.drx
 *
 * Tests parse the real fixtures through parseDRXContent and then
 * extract LUT refs. No synthesis — this is wire-format ground truth.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const { parseDRXContent } = require('../drx-parser');
const {
  extractNodeLutRef,
  extractDrxLutRefs,
  _internals,
} = require('../extract-lut-refs');
const drxParams = require('../../drx-parameters');

const FIXTURES = path.join(__dirname, 'fixtures');
const FIXTURE_LUT_PATH = 'FilmUnlimited_2383_Rec709_Finished.cube';

async function loadAndParse(name) {
  const xml = fs.readFileSync(path.join(FIXTURES, name), 'utf8');
  return parseDRXContent(xml);
}

test('extractDrxLutRefs: no-LUT fixture returns empty array', async () => {
  const parsed = await loadAndParse('p5-1-node-no-lut.drx');
  assert.ok(Array.isArray(parsed.nodes), 'parser surfaces nodes array');
  const refs = extractDrxLutRefs(parsed);
  assert.deepEqual(refs, [], 'no LUT attached → empty array');
});

test('extractDrxLutRefs: with-LUT fixture surfaces the captured LUT path', async () => {
  const parsed = await loadAndParse('p5-1-node-with-lut.drx');
  const refs = extractDrxLutRefs(parsed);
  assert.equal(refs.length, 1, 'one node has a LUT attached');
  const ref = refs[0];
  assert.equal(
    ref.lutPath,
    FIXTURE_LUT_PATH,
    `LUT path round-trips: ${ref.lutPath}`,
  );
  assert.equal(ref.slotMeta, 6, 'slot metadata round-trips to captured value');
  assert.equal(ref.source, 'drx_node');
});

test('extractNodeLutRef: returns null for nodes with no LUT', async () => {
  const parsed = await loadAndParse('p5-1-node-no-lut.drx');
  for (const node of parsed.nodes) {
    assert.equal(extractNodeLutRef(node), null);
  }
});

test('extractNodeLutRef: returns {lutPath, slotMeta} for the LUT-attached node', async () => {
  const parsed = await loadAndParse('p5-1-node-with-lut.drx');
  let found = null;
  for (const node of parsed.nodes) {
    const ref = extractNodeLutRef(node);
    if (ref) { found = ref; break; }
  }
  assert.ok(found, 'at least one node should carry a LUT');
  assert.equal(found.lutPath, FIXTURE_LUT_PATH);
  assert.equal(found.slotMeta, 6);
});

test('extractDrxLutRefs: malformed input returns empty array (defensive)', () => {
  assert.deepEqual(extractDrxLutRefs(null), []);
  assert.deepEqual(extractDrxLutRefs(undefined), []);
  assert.deepEqual(extractDrxLutRefs({}), []);
  assert.deepEqual(extractDrxLutRefs({ nodes: null }), []);
});

test('extractNodeLutRef: malformed input returns null (defensive)', () => {
  assert.equal(extractNodeLutRef(null), null);
  assert.equal(extractNodeLutRef(undefined), null);
  assert.equal(extractNodeLutRef({}), null);
  assert.equal(extractNodeLutRef({ correctors: null }), null);
  assert.equal(extractNodeLutRef({ correctors: [{ parameters: null }] }), null);
});

test('internals.envelopeToString: drops into F5 of value envelope', () => {
  assert.equal(_internals.envelopeToString(null), null);
  assert.equal(_internals.envelopeToString(undefined), null);
  assert.equal(_internals.envelopeToString('direct.cube'), 'direct.cube');
  assert.equal(_internals.envelopeToString({ F5: 'wrapped.cube' }), 'wrapped.cube');
  assert.equal(_internals.envelopeToString({ F1: 0.5 }), null, 'F1 floats are not strings');
});

test('internals.envelopeToNumber: coerces F2 ints and BigInts', () => {
  assert.equal(_internals.envelopeToNumber(null), null);
  assert.equal(_internals.envelopeToNumber(42), 42);
  assert.equal(_internals.envelopeToNumber(42n), 42);
  assert.equal(_internals.envelopeToNumber({ F2: 6 }), 6);
  assert.equal(_internals.envelopeToNumber({ F2: 6n }), 6);
  assert.equal(_internals.envelopeToNumber({ F1: 0.5 }), 0.5);
});

test('registry: NODE_LUT_REF.LUT_PATH and SLOT_META IDs are exposed', () => {
  assert.equal(drxParams.NODE_LUT_REF.LUT_PATH, 2248147105);
  assert.equal(drxParams.NODE_LUT_REF.SLOT_META, 2248147104);
});
