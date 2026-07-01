/** Surgical grade-Body label/color patcher (node-convention/provenance spec, 2026-06-22, step 1: build +
 * unit-test, NO live DB writes). Proves we can set/clear a node's label (F6) and color (F15) directly in
 * the compressed grade Body without the lossy generator — every other field stays byte-identical.
 *
 * The patch decompresses → byte-copies untouched fields verbatim → splices only the F6/F15 string →
 * fixes parent length prefixes → recompresses. This is the write half of the DB-patch path (the DB UPDATE
 * + close/reopen round-trip is the separate live step). */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';
import { patchGradeBody, decompressBody, _noopRebuild, _nodeFieldOrder } from '../server/grade-body-patch.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const xml = fs.readFileSync(path.join(here, 'fixtures', 'color-warper.drx'), 'utf8');
const HEX = xml.match(/<Body>([0-9a-f]+)<\/Body>/)[1];

const envelope = (hex) =>
  `<?xml version="1.0"?><Gallery::GyStill DbId="${crypto.randomUUID()}"><FieldsBlob/><pClipFullVer><ListMgt::LmVersion DbId="${crypto.randomUUID()}"><HasCorrection>true</HasCorrection><Body>${hex}</Body></ListMgt::LmVersion></pClipFullVer></Gallery::GyStill>`;
const parseBody = (hex) => drxTool.handler({ action: 'parse', args: { content: envelope(hex) } });

test('no-op rebuild reproduces the decompressed Body byte-for-byte (faithful surgery)', () => {
  const dec = decompressBody(HEX);
  const rebuilt = _noopRebuild(HEX);
  assert.equal(Buffer.compare(dec, rebuilt), 0, 'byte-identical');
});

test('set label (F6) + color (F15) and preserve all other corrections', async () => {
  const out = await patchGradeBody(HEX, 0, { label: 'Balance', color: 'Blue' });
  const r = await parseBody(out);
  const n = r.nodes[0];
  assert.equal(n.label, 'Balance', 'label set');
  assert.equal(n.color, 'Blue', 'color set (F15 ClipColorBlue)');
  // The lossy generator is bypassed: advanced decoded params survive the patch.
  assert.ok(n.params?.colorWarper, 'Color Warper preserved');
  assert.ok(n.params?.curvePoints, 'curve points preserved');
  assert.ok(n.params?.polygonVertices, 'polygon vertices preserved');
});

test('clear color (and label) removes the field; corrections still intact', async () => {
  const set = await patchGradeBody(HEX, 0, { label: 'Balance', color: 'Blue' });
  const cleared = await patchGradeBody(set, 0, { label: null, color: null });
  const r = await parseBody(cleared);
  const n = r.nodes[0];
  assert.equal(n.color, null, 'color cleared');
  assert.ok(!n.label, 'label cleared (empty/absent)');
  assert.ok(n.params?.colorWarper, 'Color Warper still preserved after clear');
});

test('patched node keeps fields in ascending order (Resolve reads label F6 positionally)', async () => {
  // The earlier bug appended F6/F15 at the end; Resolve's loader expects ascending field numbers and
  // reads the label from F6's canonical slot (between F5 and F7). Live-verified byte-identical to Resolve's
  // own native write. Regression guard: the order must stay sorted, with F6 before F7.
  const out = await patchGradeBody(HEX, 0, { label: 'Balance', color: 'Blue' });
  const order = _nodeFieldOrder(out, 0);
  const sorted = [...order].sort((a, b) => a - b);
  assert.deepEqual(order, sorted, `node fields ascending (got ${order})`);
  assert.ok(order.includes(6) && order.includes(15), 'F6 + F15 present');
  assert.ok(order.indexOf(6) < order.indexOf(7), 'label F6 sits before F7');
});

test('color-only edit leaves the label untouched (selective field edit)', async () => {
  const withLabel = await patchGradeBody(HEX, 0, { label: 'Primary' });
  const plusColor = await patchGradeBody(withLabel, 0, { color: 'Blue' });
  const r = await parseBody(plusColor);
  assert.equal(r.nodes[0].label, 'Primary', 'label survived a color-only edit');
  assert.equal(r.nodes[0].color, 'Blue');
});
