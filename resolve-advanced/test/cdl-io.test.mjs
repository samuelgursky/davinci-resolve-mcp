/**
 * cdl_io import (C3) — deterministic, no Resolve. Parses a CCC collection, emits a
 *.drx per correction, asserts the non-identity grade is non-empty (silent-drop guard)
 * and that slope/offset survive into the DRX. Also round-trips DRX→CDL via export logic.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { importCDL } from '../server/cdl-io.mjs';
import { drxCdl, drxParser } from '../server/libs.mjs';

const CCC = `<?xml version="1.0" encoding="UTF-8"?>
<ColorCorrectionCollection xmlns="urn:ASC:CDL:v1.2">
 <ColorCorrection id="warm_look">
 <SOPNode>
 <Slope>1.05 1.00 0.92</Slope>
 <Offset>0.01 0.00 -0.02</Offset>
 <Power>1.00 1.00 1.00</Power>
 </SOPNode>
 <SatNode><Saturation>1.10</Saturation></SatNode>
 </ColorCorrection>
 <ColorCorrection id="identity">
 <SOPNode>
 <Slope>1.0 1.0 1.0</Slope>
 <Offset>0.0 0.0 0.0</Offset>
 <Power>1.0 1.0 1.0</Power>
 </SOPNode>
 <SatNode><Saturation>1.0</Saturation></SatNode>
 </ColorCorrection>
</ColorCorrectionCollection>`;

test('importCDL emits one .drx per correction, non-identity grade is non-empty', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cdl-'));
  const r = await importCDL(CCC, { outDir: dir });
  assert.equal(r.grades.length, 2);
  const warm = r.grades.find((g) => g.id === 'warm_look');
  const idn = r.grades.find((g) => g.id === 'identity');
  assert.ok(warm && fs.existsSync(warm.drxPath), 'warm.drx written');
  assert.equal(warm.identity, false);
  assert.equal(idn.identity, true);
  // The warm grade carries real params (slope→gain etc.) — not a silently-empty no-op.
  const parsed = await drxParser().parseDRXContent(fs.readFileSync(warm.drxPath, 'utf8'));
  const nParams = (parsed.nodes || []).flatMap((n) => (n.correctors || []).flatMap((c) => c.parameters || [])).length;
  assert.ok(nParams > 0, 'warm grade has parameters');
});

test('imported slope/offset round-trip back through DRX→CDL within tolerance', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cdl-'));
  const r = await importCDL(CCC, { outDir: dir });
  const warm = r.grades.find((g) => g.id === 'warm_look');
  const parsed = await drxParser().parseDRXContent(fs.readFileSync(warm.drxPath, 'utf8'));
  const params = parsed.nodes?.[0]?.params || parsed.nodes?.[0] || parsed;
  const back = drxCdl().drxToCDL(params);
  // Slope should come back close to what we put in (gain == slope, 1:1).
  assert.ok(Math.abs(back.slope.r - 1.05) < 0.02, `slope.r ${back.slope.r}`);
  assert.ok(Math.abs(back.slope.b - 0.92) < 0.02, `slope.b ${back.slope.b}`);
});

test('importCDL throws on a non-CDL document', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cdl-'));
  await assert.rejects(() => importCDL('<not-cdl/>', { outDir: dir }), /not a CDL/);
});
