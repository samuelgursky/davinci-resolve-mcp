/**
 * Cluster P — provenance / audit. Gallery lineage, grade provenance readback, CDL round-trip +
 * diff, revision history, episode report, and the runner stage-resume. Deterministic.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  galleryLineage,
  makeStillLabel,
  validateStillLabel,
  gradeProvenance,
  cdlExport,
  cdlDiff,
  revisionHistory,
  episodeReport,
} from '../server/provenance-audit.mjs';
import { drxTool } from '../server/tools/drx.mjs';
import { computeSkinMatch } from '../server/skin-match.mjs';
import { openProjectDb, getRun } from '../server/project-db.mjs';
import { compileSpecs } from '../server/spec-compile.mjs';
import { planRun, runAll, rerunStage } from '../server/runner.mjs';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const sharp = require('sharp');

test('gallery_lineage validates labels, assigns next version, plans a TIFF export of approved', () => {
  const r = galleryLineage([
    { id: 's1', scene: 12, status: 'approved', version: 3, album: 'SC12' },
    { id: 's2', label: 'SC12_wip_v04', album: 'SC12' },
    { id: 's3', label: 'garbage-label' },
  ]);
  assert.equal(r.labels.find((l) => l.id === 's1').label, 'SC12_approved_v03');
  assert.equal(r.nextVersions[12], 5); // max(v03→4, v04→5)
  assert.equal(r.exportPlan.length, 1);
  assert.equal(r.exportPlan[0].filename, 'SC12_approved_v03.tif');
  assert.ok(r.invalidLabels.some((x) => x.id === 's3'));
});

test('still label make/validate round-trip', () => {
  const l = makeStillLabel({ scene: 5, status: 'approved', version: 2 });
  assert.equal(l, 'SC05_approved_v02');
  assert.deepEqual(validateStillLabel(l), { valid: true, label: l, scene: 5, status: 'approved', version: 2 });
  assert.equal(validateStillLabel('nope').valid, false);
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

test('grade_provenance reads the AUTO labels a matcher stamped', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'prov-'));
  const hero = path.join(dir, 'h.png');
  const dark = path.join(dir, 'd.png');
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
  const prov = await gradeProvenance({ content: fs.readFileSync(dg.drxPath, 'utf8') });
  assert.equal(prov.autoCount, 1);
  assert.equal(prov.nodes[0].tool, 'skin_match');
  assert.match(prov.summary[0], /skin_match/);
});

test('cdl_export round-trips a non-unity DRX and refuses a silent identity', async () => {
  const g = await drxTool.handler({ action: 'generate', args: { gradeParams: { gain: [1.2, 1.0, 0.9, 1.0], offset: [0.02, 0, -0.01, 0] } } });
  const content = typeof g === 'string' ? g : g.content;
  const out = await cdlExport({ content });
  assert.equal(out.verified, true);
  assert.ok(Math.abs(out.cdl.slope.r - 1.2) < 0.01, JSON.stringify(out.cdl.slope));
});

test('cdl_diff reports per-param deltas', () => {
  const a = { slope: { r: 1, g: 1, b: 1 }, offset: { r: 0, g: 0, b: 0 }, power: { r: 1, g: 1, b: 1 }, saturation: 1 };
  const b = { slope: { r: 1.1, g: 1, b: 1 }, offset: { r: 0, g: 0, b: 0 }, power: { r: 1, g: 1, b: 1 }, saturation: 1.2 };
  const d = cdlDiff(a, b);
  assert.equal(d.identical, false);
  assert.ok(d.deltas.some((x) => x.param === 'slope.r'));
  assert.ok(d.deltas.some((x) => x.param === 'saturation'));
  assert.equal(cdlDiff(a, a).identical, true);
});

test('revision_tracking orders versions and tracks approvals', () => {
  const r = revisionHistory([
    { version: 'v003', label: 'client notes', changes: ['warmer'], approvedBy: null },
    { version: 'v001', label: 'first pass', approvedBy: 'Sam', approvedAt: '2026-07-01' },
    { version: 'v002', changes: ['exposure'], approvedBy: 'Sam', approvedAt: '2026-07-02' },
  ]);
  assert.equal(r.history[0].version, 'v001');
  assert.equal(r.latest, 'v003');
  assert.equal(r.lastApproved, 'v002');
});

test('episode_report renders a structured + markdown readback', () => {
  const rep = episodeReport({
    episode: 'EP012',
    toolVersion: '0.1',
    specVersion: 7,
    stages: [
      { stage: 'conform', status: 'done', gate: 'review', approvedBy: 'Sam', approvedAt: '2026-07-06' },
      { stage: 'grade', status: 'awaiting_gate', gate: 'review' },
    ],
    drift: [],
    deliverables: [
      { name: 'EP012_texted', pass: true },
      { name: 'EP012_textless', pass: false },
    ],
  });
  assert.equal(rep.summary.gatesApproved, 1);
  assert.equal(rep.summary.gatesPending, 1);
  assert.equal(rep.summary.allDeliverablesPass, false);
  assert.match(rep.markdown, /# Episode report — EP012/);
  assert.match(rep.markdown, /EP012_textless: FAIL/);
});

test('stage resume: rerunStage resets a stage + downstream back to pending', async () => {
  const T = '2026-07-06T00:00:00Z';
  const db = openProjectDb(path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'rr-')), 'p.db'));
  compileSpecs(db, [{ slug: 'ep', kind: 'episode', config: { pipeline: ['leveling', 'qc'] } }], { now: T });
  const plan = planRun(db, 'ep', { now: T });
  const executor = async (s) => ({ ran: s.stage });
  await runAll(db, plan.runId, { executor, now: T });
  assert.equal(getRun(db, plan.runId).status, 'done');
  // Re-run leveling (index 0) + downstream → both pending again.
  const rr = rerunStage(db, plan.runId, 0, { now: T });
  assert.deepEqual(rr.reset, [0, 1]);
  const run = getRun(db, plan.runId);
  assert.equal(run.stages.find((s) => s.stage_index === 0).status, 'pending');
  assert.equal(run.stages.find((s) => s.stage_index === 1).status, 'pending');
  // Resume completes again.
  const r2 = await runAll(db, plan.runId, { executor, now: T });
  assert.equal(r2.stopped, 'complete');
  db.close();
});
