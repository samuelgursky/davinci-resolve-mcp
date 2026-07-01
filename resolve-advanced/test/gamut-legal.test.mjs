/**
 * gamut_legal (C3) — deterministic, no Resolve. Builds frames with known proportions of
 * sub-legal / super-legal / clipped pixels and asserts the QC measurement + pass/fail.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { measureLegal, computeGamutLegal } from '../server/gamut-legal.mjs';

const require = createRequire(import.meta.url);
const sharp = require('sharp');

/** Solid-colour PNG. */
async function solid(file, { r, g, b }, w = 64, h = 64) {
  const buf = Buffer.alloc(w * h * 3);
  for (let i = 0; i < buf.length; i += 3) {
    buf[i] = r;
    buf[i + 1] = g;
    buf[i + 2] = b;
  }
  await sharp(buf, { raw: { width: w, height: h, channels: 3 } })
    .png()
    .toFile(file);
}

test('legal mid-gray frame passes with ~0% illegal', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gl-'));
  const f = path.join(dir, 'mid.png');
  await solid(f, { r: 128, g: 128, b: 128 });
  const m = await measureLegal(f);
  assert.equal(m.illegalPct, 0);
  assert.equal(m.clippedPct, 0);
  assert.equal(m.channels.r.min, 128);
});

test('a crushed-black frame is flagged illegal + clipped', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gl-'));
  const f = path.join(dir, 'black.png');
  await solid(f, { r: 0, g: 0, b: 0 }); // below 16 AND ==0
  const m = await measureLegal(f);
  assert.equal(m.illegalPct, 100);
  assert.equal(m.clippedPct, 100);
  assert.equal(m.channels.r.crushedPct, 100);
});

test('computeGamutLegal pass/fail honors the tolerance', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gl-'));
  const ok = path.join(dir, 'ok.png');
  const blown = path.join(dir, 'blown.png');
  await solid(ok, { r: 100, g: 100, b: 100 });
  await solid(blown, { r: 255, g: 255, b: 255 }); // above 235 AND ==255
  const r = await computeGamutLegal(
    [
      { id: 'ok', png: ok },
      { id: 'blown', png: blown },
    ],
    { maxIllegalPct: 1 },
  );
  assert.equal(r.report.ok.pass, true);
  assert.equal(r.report.blown.pass, false);
  assert.equal(r.report.blown.channels.r.blownPct, 100);
  assert.ok(r.warnings.some((w) => w.startsWith('blown')));
});
