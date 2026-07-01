/**
 * tone_curve_transfer (P1d) — luma CDF matching → a monotonic, round-trip-asserted tone curve.
 * Also guards the Phase-0 fix: node.customCurves reads back through the drx tool's parse.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { measureLumaCDF, computeToneCurve, computeToneCurveTransfer } from '../server/tone-curve-transfer.mjs';
import { drxTool } from '../server/tools/drx.mjs';

const require = createRequire(import.meta.url);
const sharp = require('sharp');

/** Horizontal gray ramp from `lo` to `hi` (luma spread controls contrast). */
async function ramp(file, lo, hi, w = 128, h = 32) {
  const buf = Buffer.alloc(w * h * 3);
  for (let x = 0; x < w; x++) {
    const v = Math.round(lo + ((hi - lo) * x) / (w - 1));
    for (let y = 0; y < h; y++) {
      const i = (y * w + x) * 3;
      buf[i] = v;
      buf[i + 1] = v;
      buf[i + 2] = v;
    }
  }
  await sharp(buf, { raw: { width: w, height: h, channels: 3 } })
    .png()
    .toFile(file);
}

const monotonic = (pts) => pts.every((p, i) => i === 0 || p.y >= pts[i - 1].y - 1e-9);

test('Phase 0: node.customCurves.y reads back through the drx parse (arg-bug fix)', async () => {
  const g = await drxTool.handler({
    action: 'generate',
    args: {
      gradeParams: {
        customCurves: {
          y: [
            { x: 0, y: 0 },
            { x: 0.5, y: 0.62 },
            { x: 1, y: 1 },
          ],
        },
      },
    },
  });
  const content = typeof g === 'string' ? g : g.content;
  const back = await drxTool.handler({ action: 'parse', args: { content: typeof content === 'string' ? content : content.content } });
  const y = back.nodes[0].customCurves && back.nodes[0].customCurves.y;
  assert.ok(Array.isArray(y) && y.length, 'curve read back through the tool');
  const mid = y.find((p) => Math.abs(p.x - 0.5) < 0.02);
  assert.ok(mid && Math.abs(mid.y - 0.62) < 0.01, `mid point ${JSON.stringify(mid)}`);
});

test('computeToneCurve expands a compressed source toward a full-range reference', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'tc-'));
  const src = path.join(dir, 'src.png');
  const ref = path.join(dir, 'ref.png');
  await ramp(src, 60, 180); // compressed (low contrast)
  await ramp(ref, 0, 255); // full range (high contrast)
  const sc = await measureLumaCDF(src);
  const rc = await measureLumaCDF(ref);
  const pts = computeToneCurve(sc, rc, { strength: 1 });
  assert.ok(monotonic(pts), 'curve is monotonic non-decreasing');
  const shadow = pts.find((p) => Math.abs(p.x - 0.25) < 0.02);
  const highlight = pts.find((p) => Math.abs(p.x - 0.75) < 0.02);
  assert.ok(shadow.y < shadow.x - 0.05, `shadows pulled down: x=${shadow.x} y=${shadow.y}`);
  assert.ok(highlight.y > highlight.x + 0.05, `highlights pushed up: x=${highlight.x} y=${highlight.y}`);
});

test('computeToneCurve on identical source/reference is ~identity', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'tc-'));
  const f = path.join(dir, 'r.png');
  await ramp(f, 0, 255);
  const c = await measureLumaCDF(f);
  const pts = computeToneCurve(c, c, { strength: 1 });
  assert.ok(
    pts.every((p) => Math.abs(p.y - p.x) < 0.03),
    `near-identity: ${JSON.stringify(pts)}`,
  );
});

test('strength scales the correction toward identity', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'tc-'));
  const src = path.join(dir, 's.png');
  const ref = path.join(dir, 'r.png');
  await ramp(src, 60, 180);
  await ramp(ref, 0, 255);
  const sc = await measureLumaCDF(src);
  const rc = await measureLumaCDF(ref);
  const maxDelta = (pts) => Math.max(...pts.map((p) => Math.abs(p.y - p.x)));
  const strong = maxDelta(computeToneCurve(sc, rc, { strength: 1.0 }));
  const soft = maxDelta(computeToneCurve(sc, rc, { strength: 0.3 }));
  assert.ok(soft < strong, `soft ${soft} < strong ${strong}`);
});

test('computeToneCurveTransfer emits a round-trip-asserted curve DRX', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'tc-'));
  const src = path.join(dir, 's.png');
  const ref = path.join(dir, 'r.png');
  await ramp(src, 70, 170);
  await ramp(ref, 0, 255);
  const r = await computeToneCurveTransfer([{ id: 'shot1', png: src, reference: ref }], { outDir: path.join(dir, 'out'), strength: 0.9 });
  assert.equal(r.grades.length, 1);
  const g = r.grades[0];
  assert.ok(fs.existsSync(g.drxPath));
  assert.ok(monotonic(g.points));
  // Independently decode the written curve.
  const back = await drxTool.handler({ action: 'parse', args: { content: fs.readFileSync(g.drxPath, 'utf8') } });
  assert.ok(back.nodes[0].customCurves.y.length, 'curve present in the DRX');
});

test('near-identity and intent-tagged clips are skipped, not faked', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'tc-'));
  const same = path.join(dir, 'same.png');
  const src = path.join(dir, 'src.png');
  const ref = path.join(dir, 'ref.png');
  await ramp(same, 0, 255);
  await ramp(src, 60, 180);
  await ramp(ref, 0, 255);
  const r = await computeToneCurveTransfer(
    [
      { id: 'identity', png: same, reference: same }, // already matches → near-identity skip
      { id: 'intentional', png: src, reference: ref },
    ],
    { outDir: path.join(dir, 'out'), intentTags: { intentional: ['low_key'] } },
  );
  assert.ok(r.skipped.some((s) => s.id === 'identity' && /near-identity/.test(s.reason)));
  assert.ok(r.skipped.some((s) => s.id === 'intentional' && /intent/.test(s.reason)));
  assert.equal(r.grades.length, 0);
});

test('drx tone_curve_transfer action dispatches', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'tc-'));
  const src = path.join(dir, 's.png');
  const ref = path.join(dir, 'r.png');
  await ramp(src, 80, 160);
  await ramp(ref, 0, 255);
  const r = await drxTool.handler({ action: 'tone_curve_transfer', args: { clips: [{ id: 'c1', png: src, reference: ref }], outDir: path.join(dir, 'out') } });
  assert.equal(r.gradeCount, 1);
  assert.ok(r.grades[0].maxDeltaPct > 0);
});
