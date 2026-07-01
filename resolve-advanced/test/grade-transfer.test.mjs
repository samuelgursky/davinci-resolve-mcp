/**
 * grade_transfer (C3) — deterministic, no Resolve. Generates a real grade.drx (which
 * carries a <Body> blob), transfers from it, and asserts the body is copied BYTE-FOR-BYTE
 * into the apply-ready GyStill envelope (the lossless property), decodes to ≥1 node, and
 * that empty / bodiless sources are refused.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { drxTool } from '../server/tools/drx.mjs';
import { transferGrade } from '../server/grade-transfer.mjs';

async function makeGradedDrx(file) {
  // Non-identity gain → a real, non-empty grade body.
  await drxTool.handler({ action: 'generate', args: { gradeParams: { gain: [1.1, 1.0, 0.9, 1.0] }, metadata: { label: 'src' }, outputPath: file } });
  return file;
}
const bodyOf = (xml) => (xml.match(/<Body>([0-9a-fA-F]+)<\/Body>/) || [])[1];

test('transfer from a .drx copies the Body byte-for-byte into a GyStill envelope', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gt-'));
  const src = await makeGradedDrx(path.join(dir, 'src.drx'));
  const out = path.join(dir, 'out.drx');
  const r = await transferGrade({ drxPath: src }, { outPath: out, label: 'HostLook' });

  assert.ok(r.nodeCount >= 1, `nodeCount ${r.nodeCount}`);
  assert.ok(fs.existsSync(out), 'wrote output');
  const outXml = fs.readFileSync(out, 'utf8');
  // Apply-ready envelope, and the grade body is identical to the source (lossless).
  assert.match(outXml, /Gallery::GyStill/);
  assert.equal(bodyOf(outXml), bodyOf(fs.readFileSync(src, 'utf8')), 'body copied verbatim');
  assert.match(outXml, /<Label>HostLook<\/Label>/);
});

test('transfer accepts raw content too', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gt-'));
  const src = await makeGradedDrx(path.join(dir, 'src.drx'));
  const content = fs.readFileSync(src, 'utf8');
  const r = await transferGrade({ content }, {});
  assert.ok(r.nodeCount >= 1);
  assert.equal(bodyOf(r.content), bodyOf(content));
});

test('GUARD: a source with no Body is refused', async () => {
  await assert.rejects(() => transferGrade({ content: '<Resolve_Color_Exchange/>' }, {}), /no <Body>/);
});

test('GUARD: missing source spec throws', async () => {
  await assert.rejects(() => transferGrade({}, {}), /provide source\.drpPath\+group/);
});
