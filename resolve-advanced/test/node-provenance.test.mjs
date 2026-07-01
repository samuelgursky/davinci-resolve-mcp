/**
 * node-labeling / provenance (Layer-3) — the label that makes auto-apply safe.
 * Asserts the AUTO label format, round-trip parse, the DB record shape, and that the
 * matchers actually STAMP a queryable AUTO provenance label onto the DRX node they emit.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { provenanceLabel, provenanceRecord, parseProvenanceLabel, isAutoLabel, gist, TOOL_VERSIONS } from '../server/node-provenance.mjs';
import { computeSkinMatch } from '../server/skin-match.mjs';
import { drxTool } from '../server/tools/drx.mjs';

const require = createRequire(import.meta.url);
const sharp = require('sharp');

test('provenanceLabel builds the AUTO convention with tool/version/source/gist', () => {
  const l = provenanceLabel('skin_match', { source: 'hero:CU_02', gist: gist('gain', { r: 1.08, g: 1.02, b: 0.97 }) });
  assert.equal(l, `AUTO:skin_match v${TOOL_VERSIONS.skin_match} → hero:CU_02 | gain(1.08,1.02,0.97)`);
  assert.ok(isAutoLabel(l));
});

test('parseProvenanceLabel round-trips and rejects human labels', () => {
  const l = provenanceLabel('exposure_level', { source: 'hero:A001', gist: 'gain(1.10,1.00,0.95)' });
  const p = parseProvenanceLabel(l);
  assert.equal(p.auto, true);
  assert.equal(p.tool, 'exposure_level');
  assert.equal(p.version, TOOL_VERSIONS.exposure_level);
  assert.equal(p.source, 'hero:A001');
  assert.equal(p.gist, 'gain(1.10,1.00,0.95)');
  const human = parseProvenanceLabel('Sam - warm the interview');
  assert.equal(human.auto, false);
});

test('provenanceRecord carries params + source + actor for the DB', () => {
  const rec = provenanceRecord({ tool: 'shot_match', source: 'neutralize', params: { gain: { r: 1, g: 1, b: 1 } }, clipId: 'b12', actor: 'system' });
  assert.equal(rec.tool, 'shot_match');
  assert.equal(rec.version, TOOL_VERSIONS.shot_match);
  assert.equal(rec.clipId, 'b12');
  assert.ok(rec.label.startsWith('AUTO:shot_match'));
});

async function frame(file, skin) {
  const w = 64,
    h = 64;
  const buf = Buffer.alloc(w * h * 3);
  for (let y = 0; y < h; y++) {
    const c = y < 32 ? skin : { r: 20, g: 40, b: 160 };
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 3;
      buf[i] = c.r;
      buf[i + 1] = c.g;
      buf[i + 2] = c.b;
    }
  }
  await sharp(buf, { raw: { width: w, height: h, channels: 3 } })
    .png()
    .toFile(file);
}

test('skin_match stamps an AUTO provenance label the DRX carries (queryable)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'prov-'));
  const hero = path.join(dir, 'hero.png');
  const dark = path.join(dir, 'dark.png');
  await frame(hero, { r: 200, g: 140, b: 110 });
  await frame(dark, { r: 150, g: 100, b: 80 });
  const r = await computeSkinMatch(
    [
      { id: 'hero', png: hero, group: 'Guest' },
      { id: 'dark', png: dark, group: 'Guest' },
    ],
    { outDir: path.join(dir, 'out') },
  );
  const dg = r.grades.find((g) => g.id === 'dark');
  const parsed = await drxTool.handler({ action: 'parse', args: { content: fs.readFileSync(dg.drxPath, 'utf8') } });
  const label = parsed.nodes[0].label;
  const p = parseProvenanceLabel(label);
  assert.equal(p.auto, true, `label was: ${label}`);
  assert.equal(p.tool, 'skin_match');
  assert.equal(p.source, 'hero:hero');
});
