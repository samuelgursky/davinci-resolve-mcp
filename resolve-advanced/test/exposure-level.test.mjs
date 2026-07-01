/** Exposure-leveling core: gain-to-hero, round-trip assert, over-correction warning. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { computeLevels } from '../server/exposure-level.mjs';

const require = createRequire(import.meta.url);
let sharp;
try {
  sharp = require('sharp');
} catch {
  /* skip if absent */
}

test('computeLevels: gain to hero + round-trip + over-correction warning', { skip: !sharp }, async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'explvl-'));
  const hero = path.join(dir, 'hero.png');
  const dark = path.join(dir, 'dark.png');
  await sharp({ create: { width: 16, height: 16, channels: 3, background: { r: 128, g: 128, b: 128 } } })
    .png()
    .toFile(hero);
  await sharp({ create: { width: 16, height: 16, channels: 3, background: { r: 100, g: 100, b: 120 } } })
    .png()
    .toFile(dark);

  const { grades, report, warnings } = await computeLevels(
    [
      { id: 'h', png: hero, group: 'g' },
      { id: 'd', png: dark, group: 'g' },
    ],
    { outDir: path.join(dir, 'out') },
  );
  assert.equal(grades.length, 2);
  const hero_g = grades.find((x) => x.id === 'h');
  const dark_g = grades.find((x) => x.id === 'd');
  assert.ok(Math.abs(hero_g.gain.r - 1) < 1e-6, 'hero gain ~1');
  assert.ok(Math.abs(dark_g.gain.r - 1.28) < 0.02, `dark R gain ~1.28 (got ${dark_g.gain.r})`);
  assert.ok(dark_g.gain.b < dark_g.gain.r, 'dark was bluer -> less blue gain');
  for (const gr of grades) assert.ok(fs.existsSync(gr.drxPath) && fs.statSync(gr.drxPath).size > 0, 'DRX written');
  assert.ok(report.g.max_correction_pct > 25, 'reports the ~28% correction');
  assert.ok(
    warnings.some((w) => /over|correction|different shots/i.test(w)),
    'warns over-correction',
  );
});

test('computeLevels: unimplemented modes throw (no silent wrong math)', async () => {
  await assert.rejects(() => computeLevels([], { outDir: '/tmp/x', mode: 'skin_match' }), /not implemented/);
});
