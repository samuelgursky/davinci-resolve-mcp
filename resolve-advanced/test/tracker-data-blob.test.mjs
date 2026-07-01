/**
 * Window TRACKER DATA blob — DECODED 2026-07-03 by live capture against KNOWN synthetic
 * motion (static-noise patch moving exactly 12 px/frame; cloud tracker, Resolve 19.1.3).
 *
 * Wire format (inside the keyframed ct3 window region of the node Body):
 *   repeated record: 0x0A len { F1: frame×2 (varint — the same half-frame convention as
 *   keyframes/framesFlag), F2: { F1: param-id varint, F2: { 0x52 len: nine TAGGED f32
 *   fields f1..f9 } } }
 *   The nine floats are a row-major 3×3 transform RELATIVE TO THE REFERENCE FRAME:
 *   [ m11 m12 tx / m21 m22 ty / m31 m32 m33 ] — pan = f3 (tx), tilt = f6 (ty),
 *   rotation/zoom live in the 2×2 block, perspective row ≈ [0,0,1].
 *
 * Validation on capture: 71 records (frame 0 = reference, no record), tx fits
 * 11.96 px/frame vs 12.0 ground truth, ty ≈ 0, 2×2 ≈ identity; final tx 851.61 matched
 * the Resolve tracker panel readout exactly. Decode-level knowledge — no write path.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

const FIX = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'tracker-linear-motion.drx');

function decompressBody(drxPath) {
  const xml = fs.readFileSync(drxPath, 'utf8');
  const hex = xml.match(/<Body>([0-9a-f]+)<\/Body>/i)[1];
  const raw = Buffer.from(hex, 'hex');
  if (typeof zlib.zstdDecompressSync === 'function') return zlib.zstdDecompressSync(raw.subarray(1));
  // Node <22 fallback — same ladder as the codec
  const fz = require('fzstd');
  return Buffer.from(fz.decompress(raw.subarray(1)));
}

function walkTrackRecords(body) {
  const rows = [];
  let i = 0;
  while (i < body.length - 2) {
    if (body[i] !== 0x0a) { i++; continue; }
    const len = body[i + 1];
    const rec = body.subarray(i + 2, i + 2 + len);
    if (rec[0] !== 0x08) { i++; continue; }
    let j = 1, f = 0, s = 0;
    while (rec[j] & 0x80) { f |= (rec[j] & 0x7f) << s; s += 7; j++; }
    f |= rec[j] << s; j++;
    const k = rec.indexOf(0x52, j);
    if (k < 0 || k + 1 >= rec.length) { i += 2 + len; continue; }
    const m = rec.subarray(k + 2, k + 2 + rec[k + 1]);
    const flt = {};
    let q = 0;
    while (q < m.length - 4) {
      const tag = m[q];
      if ((tag & 7) !== 5) break;
      flt['f' + (tag >> 3)] = m.readFloatLE(q + 1);
      q += 5;
    }
    if (flt.f3 !== undefined) rows.push({ frame: f / 2, tx: flt.f3, ty: flt.f6, m11: flt.f1, m22: flt.f5 });
    i += 2 + len;
  }
  return rows;
}

test('tracker blob: 71 per-frame transform records decode from the captured body', () => {
  const rows = walkTrackRecords(decompressBody(FIX));
  assert.equal(rows.length, 71, 'one record per tracked frame (frame 0 = reference)');
  assert.equal(rows[0].frame, 1);
  assert.equal(rows[rows.length - 1].frame, 71);
});

test('tracker blob: tx matches the known 12 px/frame motion; ty ≈ 0; 2×2 ≈ identity', () => {
  const rows = walkTrackRecords(decompressBody(FIX));
  const xs = rows.map(r => r.frame), ys = rows.map(r => r.tx);
  const n = xs.length, sx = xs.reduce((a, v) => a + v, 0), sy = ys.reduce((a, v) => a + v, 0);
  const sxx = xs.reduce((a, v) => a + v * v, 0), sxy = xs.reduce((a, v, i) => a + v * ys[i], 0);
  const slope = (n * sxy - sx * sy) / (n * sxx - sx * sx);
  assert.ok(Math.abs(slope - 12) < 0.5, `pan slope ${slope.toFixed(3)} ≈ 12 px/frame`);
  assert.ok(Math.abs(rows[rows.length - 1].tx - 851.61) < 0.1, 'final tx matches the panel readout');
  for (const r of rows) {
    assert.ok(Math.abs(r.ty) < 3, `ty stays near 0 (frame ${r.frame}: ${r.ty})`);
    assert.ok(Math.abs(r.m11 - 1) < 0.02 && Math.abs(r.m22 - 1) < 0.02, 'no rotation/zoom drift');
  }
});
