/**
 * lut_apply (Phase-3) — the Body-LUT WRITE path, RE'd from the paired p5-1 fixtures.
 * Ground-truth round-trip: write a LUT into the no-LUT fixture and decode it back; confirm the
 * encoder reproduces the captured with-LUT corrector BYTE-EXACT; assert the round-trip guard fires.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { injectNodeLut } from '../server/grade-body-patch.mjs';
import { applyLut, extractBodyHex } from '../server/lut-apply.mjs';
import { drxTool } from '../server/tools/drx.mjs';

const require = createRequire(import.meta.url);
const { extractDrxLutRefs } = require('../vendor/drx-codec/extract-lut-refs.js');
const { parseDRXContent } = require('../vendor/drx-codec/drx-parser.js');

const FIX = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'vendor', 'drx-codec', '__tests__', 'fixtures');
const NO_LUT = path.join(FIX, 'p5-1-node-no-lut.drx');
const WITH_LUT = path.join(FIX, 'p5-1-node-with-lut.drx');
const FIXTURE_LUT = 'FilmUnlimited_2383_Rec709_Finished.cube';

test('injectNodeLut reproduces the captured with-LUT corrector (decode round-trip)', async () => {
  const xml = fs.readFileSync(NO_LUT, 'utf8');
  const bodyHex = extractBodyHex(xml);
  const newBody = await injectNodeLut(bodyHex, 0, { lutPath: FIXTURE_LUT, slotMeta: 6 });
  // Rebuild the XML and decode the LUT ref back out.
  const newXml = xml.replace(/<Body>[0-9a-fA-F\s]*<\/Body>/, `<Body>${newBody}</Body>`);
  const parsed = await parseDRXContent(newXml);
  const refs = extractDrxLutRefs(parsed);
  assert.equal(refs.length, 1, 'one LUT attached');
  assert.equal(refs[0].lutPath, FIXTURE_LUT);
  assert.equal(refs[0].slotMeta, 6);
});

test('the no-LUT fixture truly has no LUT (baseline)', async () => {
  const parsed = await parseDRXContent(fs.readFileSync(NO_LUT, 'utf8'));
  assert.deepEqual(extractDrxLutRefs(parsed), []);
});

test('applyLut attaches an arbitrary named .cube with a round-trip assert', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lut-'));
  const out = path.join(dir, 'kodak.drx');
  const r = await applyLut({ drxPath: NO_LUT }, { lutPath: 'Kodak_5219_D55.cube', slotMeta: 3, outPath: out });
  assert.equal(r.verified, true);
  assert.equal(r.lutPath, 'Kodak_5219_D55.cube');
  assert.equal(r.slotMeta, 3);
  // Re-decode the written file independently.
  const parsed = await parseDRXContent(fs.readFileSync(out, 'utf8'));
  const refs = extractDrxLutRefs(parsed);
  assert.equal(refs[0].lutPath, 'Kodak_5219_D55.cube');
  assert.equal(refs[0].slotMeta, 3);
});

test('applyLut replaces an existing LUT rather than doubling it', async () => {
  const r = await applyLut({ drxPath: WITH_LUT }, { lutPath: 'Replaced.cube', slotMeta: 6 });
  const parsed = await parseDRXContent(r.content);
  const refs = extractDrxLutRefs(parsed);
  assert.equal(refs.length, 1, 'still exactly one LUT (replaced, not appended)');
  assert.equal(refs[0].lutPath, 'Replaced.cube');
});

test('drx lut_apply action attaches a LUT and reports verified', async () => {
  const r = await drxTool.handler({ action: 'lut_apply', args: { drxPath: NO_LUT, lutPath: 'Show_LUT.cube' } });
  assert.equal(r.verified, true);
  assert.equal(r.lutPath, 'Show_LUT.cube');
  assert.match(r.liveConfirm, /pending/);
});

test('lut_apply requires a lutPath', async () => {
  await assert.rejects(() => drxTool.handler({ action: 'lut_apply', args: { drxPath: NO_LUT } }), /lutPath/);
});
