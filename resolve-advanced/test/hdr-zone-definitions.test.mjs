/**
 * HDR ZONE_DEFINITIONS — nested structure DECODED by live capture-sweep 2026-07-03
 * (Resolve 19.1.3, HDR palette zone editor, gallery still + .drx):
 *
 *   hdrZone.definitions = repeated F17 { F1: zone record }
 *   zone record = { F1: name (string) · F2: DEFAULT boundary f32 · F3: CURRENT
 *                   boundary/Max-Range f32 · F4: DEFAULT falloff f32 · F5: CURRENT falloff f32 }
 *
 * Disambiguated by two captures: falloff 0.20→0.35 moved only F5 (fixture A);
 * Max Range −1.50→−2.00 moved only F3 (fixture B). F2/F4 hold the zone defaults.
 * Decode-level knowledge only — no write path yet (zone-definition writes stay refused).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const FIX = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures');

async function darkZoneRecord(file) {
  const p = await drxTool.handler({ action: 'parse', args: { drxPath: path.join(FIX, file) } });
  for (const c of p.nodes[0].correctors || [])
    for (const prm of c.parameters || [])
      if (prm.name === 'hdrZone.definitions') {
        const raw = prm.value.F17.F1;
        const buf = Buffer.isBuffer(raw) ? raw : Buffer.from(raw.data ?? raw);
        // walk: F1 len-delimited name, then fixed32 fields F2..F5
        let i = 0;
        const out = {};
        while (i < buf.length) {
          const tag = buf[i], fn = tag >> 3, wt = tag & 7;
          i++;
          if (wt === 2) { const len = buf[i]; i++; out['F' + fn] = buf.slice(i, i + len).toString(); i += len; }
          else if (wt === 5) { out['F' + fn] = buf.readFloatLE(i); i += 4; }
          else break;
        }
        return out;
      }
  throw new Error('no hdrZone.definitions in ' + file);
}

test('zone record: custom falloff lands in F5, defaults in F2/F4 (fixture A)', async () => {
  const z = await darkZoneRecord('hdr-zone-def-falloff035.drx');
  assert.equal(z.F1, 'Dark');
  assert.ok(Math.abs(z.F2 - -1.5) < 1e-6, 'F2 default boundary −1.5');
  assert.ok(Math.abs(z.F3 - -1.5) < 1e-6, 'F3 boundary untouched in fixture A');
  assert.ok(Math.abs(z.F4 - 0.2) < 1e-6, 'F4 default falloff 0.2');
  assert.ok(Math.abs(z.F5 - 0.35) < 1e-6, 'F5 CURRENT falloff 0.35');
});

test('zone record: custom Max Range lands in F3 only (fixture B)', async () => {
  const z = await darkZoneRecord('hdr-zone-def-range-neg2.drx');
  assert.equal(z.F1, 'Dark');
  assert.ok(Math.abs(z.F2 - -1.5) < 1e-6, 'F2 default stays −1.5');
  assert.ok(Math.abs(z.F3 - -2.0) < 1e-6, 'F3 CURRENT boundary −2.0');
  assert.ok(Math.abs(z.F5 - 0.35) < 1e-6, 'F5 falloff still 0.35');
});

test('zone definitions WRITE: generator emits native record structure (round-trip)', async () => {
  const { drxTool } = await import('../server/tools/drx.mjs');
  const r = await drxTool.handler({ action: 'generate', args: { gradeParams: { hdrZones: [{ zone: 'Dark', exposure: 0.1 }], hdrZoneDefinitions: [{ name: 'Dark', boundary: -2.2, falloff: 0.4 }] }, metadata: { label: 'zone def write' } } });
  const p = await drxTool.handler({ action: 'parse', args: { content: r.content } });
  let rec = null;
  for (const c of p.nodes[0].correctors || [])
    for (const prm of c.parameters || [])
      if (prm.name === 'hdrZone.definitions') {
        const raw = prm.value.F17.F1;
        const buf = Buffer.isBuffer(raw) ? raw : Buffer.from(raw.data ?? raw);
        let i = 0; rec = {};
        while (i < buf.length) {
          const tag = buf[i], fn = tag >> 3, wt = tag & 7; i++;
          if (wt === 2) { const len = buf[i]; i++; rec['F' + fn] = buf.slice(i, i + len).toString(); i += len; }
          else if (wt === 5) { rec['F' + fn] = buf.readFloatLE(i); i += 4; }
          else break;
        }
      }
  assert.ok(rec, 'definitions param present');
  assert.equal(rec.F1, 'Dark');
  assert.ok(Math.abs(rec.F2 - -1.5) < 1e-6, 'stock default boundary');
  assert.ok(Math.abs(rec.F3 - -2.2) < 1e-5, 'custom boundary');
  assert.ok(Math.abs(rec.F5 - 0.4) < 1e-6, 'custom falloff');
});
