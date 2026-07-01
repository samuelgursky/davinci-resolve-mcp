/**
 * Pipeline foundation (A1–B1 + a B2 end-to-end slice) — deterministic, no Resolve.
 * Proves the DB-as-truth spine: compile YAML→DB with inheritance, plan+run a pipeline
 * with gates and the Node-can't-drive-Resolve boundary, readback actual + detect drift.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { openProjectDb, upsertEntity, getEntity, listEntities, ancestry, getFacts, listDrift } from '../server/project-db.mjs';
import { deepMerge, compileSpecs, validateResolved, loadYamlDir } from '../server/spec-compile.mjs';
import { recordReadback, detectDrift, reconcile, driftReport } from '../server/readback.mjs';
import { CATALOG, getDescriptor, listCatalog, STAGE_PLAN } from '../server/tool-catalog.mjs';
import { planRun, executeStage, runAll, approveGate, markStageApplied } from '../server/runner.mjs';
import { getRun } from '../server/project-db.mjs';

const T = '2026-06-29T00:00:00Z';
const tmpDb = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'pdb-')), 'project.db');

// ── A1: canonical DB ───────────────────────────────────────────────────────────
test('A1: entities upsert, hierarchy ancestry, idempotent upsert', () => {
  const db = openProjectDb(tmpDb());
  upsertEntity(db, { slug: 'doc-interview', kind: 'type', resolved: { color: { science: 'acescct' } }, now: T });
  upsertEntity(db, { slug: 'demo-series', kind: 'series', parentSlug: 'doc-interview', resolved: {}, now: T });
  upsertEntity(db, { slug: 'e050', kind: 'episode', parentSlug: 'demo-series', resolveRef: 'REF001', resolved: {}, now: T });
  const chain = ancestry(db, 'e050').map((e) => e.slug);
  assert.deepEqual(chain, ['e050', 'demo-series', 'doc-interview']);
  assert.equal(listEntities(db, { kind: 'episode' }).length, 1);
  const h1 = getEntity(db, 'e050').content_hash;
  upsertEntity(db, { slug: 'e050', kind: 'episode', parentSlug: 'demo-series', resolved: {}, now: T });
  assert.equal(getEntity(db, 'e050').content_hash, h1, 'same content → same hash');
  db.close();
});

// ── A2: compile + inheritance + validation ──────────────────────────────────────
test('A2: deepMerge — override, deep-merge, list replace, +append', () => {
  assert.equal(deepMerge({ a: 1 }, { a: 2 }).a, 2);
  assert.deepEqual(deepMerge({ m: { x: 1, y: 2 } }, { m: { y: 9 } }).m, { x: 1, y: 9 });
  assert.deepEqual(deepMerge({ l: [1, 2] }, { l: [3] }).l, [3], 'lists replace');
  assert.deepEqual(deepMerge({ l: [1, 2] }, { '+l': [3] }).l, [1, 2, 3], '+key appends');
});

test('A2: compileSpecs resolves type→series→episode and writes resolved rows', () => {
  const db = openProjectDb(tmpDb());
  const specs = [
    { slug: 'doc-interview', kind: 'type', config: { color: { science: 'acescct', odt: 'Rec.709' }, node_model: 'log' } },
    { slug: 'demo-series', kind: 'series', parent: 'doc-interview', config: { host: { name: 'Host' }, color: { odt: 'Rec.709 G2.4' } } },
    {
      slug: 'e050',
      kind: 'episode',
      parent: 'demo-series',
      config: { sources: ['/vol/x'], pipeline: ['conform', { stage: 'leveling', gate: 'review' }, 'qc'] },
    },
  ];
  const { compiled } = compileSpecs(db, specs, { now: T });
  assert.deepEqual(compiled, ['doc-interview', 'demo-series', 'e050']);
  const e050 = getEntity(db, 'e050').resolved;
  assert.equal(e050.color.science, 'acescct', 'inherited from type');
  assert.equal(e050.color.odt, 'Rec.709 G2.4', 'series override wins');
  assert.equal(e050.host.name, 'Host', 'inherited from series');
  assert.equal(e050.node_model, 'log');
  db.close();
});

test('A2: deliverable inherits a sibling deliverable', () => {
  const db = openProjectDb(tmpDb());
  compileSpecs(
    db,
    [
      { slug: 'ep', kind: 'episode', config: {} },
      {
        slug: 'ep.deliverable.yt',
        kind: 'deliverable',
        parent: 'ep',
        config: { video: { codec: 'H.264', res: '1920x1080' }, audio: { loudness: '-14 LUFS' } },
      },
      { slug: 'ep.deliverable.bonus', kind: 'deliverable', parent: 'ep', inherits: 'ep.deliverable.yt', config: { naming: 'bonus_{ep}' } },
    ],
    { now: T },
  );
  const bonus = getEntity(db, 'ep.deliverable.bonus').resolved;
  assert.equal(bonus.video.codec, 'H.264', 'inherited from sibling');
  assert.equal(bonus.naming, 'bonus_{ep}');
  db.close();
});

test('A2: validation fails fast on the silent-failure class', () => {
  assert.throws(() => validateResolved('type', 't', { color: { science: 'nonsense' } }), /science/);
  assert.throws(() => validateResolved('deliverable', 'd', { audio: {} }), /video\.codec/);
  assert.throws(() => validateResolved('episode', 'e', { pipeline: ['frobnicate'] }), /stage 'frobnicate' unknown/);
  assert.ok(validateResolved('episode', 'e', { pipeline: ['conform', { stage: 'qc', gate: 'pass' }] }));
});

test('A2: loadYamlDir reads files; deliverables stay in config (inheritance-friendly)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'yml-'));
  fs.writeFileSync(
    path.join(dir, 'ep.yml'),
    ['slug: ep1', 'kind: episode', 'parent: showX', 'sources: ["/v/a"]', 'deliverables:', '  - id: master', '    video: { codec: "ProRes 422 HQ" }'].join('\n'),
  );
  const specs = loadYamlDir(dir);
  const ep = specs.find((s) => s.slug === 'ep1');
  assert.equal(ep.kind, 'episode');
  assert.equal(ep.parent, 'showx');
  assert.equal(ep.config.deliverables[0].id, 'master', 'deliverables kept in config');
  assert.equal(specs.filter((s) => s.kind === 'deliverable').length, 0, 'not extracted to entities');
});

// ── A3: readback + drift ─────────────────────────────────────────────────────────
test('A3: recordReadback + detectDrift flags mismatch, matches equal', () => {
  const db = openProjectDb(tmpDb());
  upsertEntity(db, { slug: 'g.host', kind: 'group', resolved: { look: { lut: 'Kodak_5219' }, color: { science: 'acescct' } }, now: T });
  recordReadback(db, 'g.host', { 'color.science': 'acescct', 'look.lut': 'WRONG_LUT' }, { source: 'route_a', now: T });
  assert.equal(getFacts(db, 'g.host').length, 2);
  const { drift, matched } = detectDrift(db, 'g.host', [{ field: 'color.science' }, { field: 'look.lut' }], { now: T });
  assert.deepEqual(matched, ['color.science']);
  assert.equal(drift.length, 1);
  assert.equal(drift[0].field, 'look.lut');
  assert.equal(driftReport(db, 'g.host').openCount, 1);
  db.close();
});

test('A3: reconcile writes facts + returns drift in one call', () => {
  const db = openProjectDb(tmpDb());
  upsertEntity(db, { slug: 'seq.main', kind: 'sequence', resolved: { clip_count: 305 }, now: T });
  const r = reconcile(db, 'seq.main', { facts: { clip_count: 304 }, pushFields: [{ field: 'clip_count' }], source: 'live', now: T });
  assert.equal(r.written.length, 1);
  assert.equal(r.drift.length, 1, 'count drift 305≠304');
  db.close();
});

// ── B0: catalog ──────────────────────────────────────────────────────────────────
test('B0: catalog descriptors are valid + routable; stage map covers pipeline stages', () => {
  assert.ok(CATALOG.length >= 8);
  assert.equal(getDescriptor('skin_match').action, 'skin_match');
  assert.ok(getDescriptor('shot_match').not_for.includes('exposure_level'));
  const compact = listCatalog();
  assert.ok(
    compact.every((d) => d.id && d.summary && !('inputs' in d)),
    'compact list omits heavy fields',
  );
  assert.equal(STAGE_PLAN.leveling.mode, 'deterministic');
  assert.equal(STAGE_PLAN.conform.mode, 'resolve');
});

// ── B1 + B2: plan, run, gates, resolve boundary, end-to-end ──────────────────────
test('B2: end-to-end — compile, plan, run deterministic stage, gate, resolve boundary, readback', async () => {
  const db = openProjectDb(tmpDb());
  compileSpecs(
    db,
    [
      { slug: 'doc-interview', kind: 'type', config: { color: { science: 'acescct' } } },
      { slug: 'demo-series', kind: 'series', parent: 'doc-interview', config: { host: { name: 'Host' } } },
      {
        slug: 'e012',
        kind: 'episode',
        parent: 'demo-series',
        resolveRef: '2600xx',
        config: {
          grade: { leveling: { mode: 'within_camera_mean', groups: ['Host'], clamp_gain: [0.5, 2] } },
          qc: { conform: { structure_min: 0.9 } },
          pipeline: ['conform', { stage: 'leveling', gate: 'review' }, 'qc'],
        },
      },
    ],
    { now: T },
  );

  const plan = planRun(db, 'e012', { now: T });
  assert.equal(plan.stages.length, 3);
  assert.equal(plan.stages[0].mode, 'resolve', 'conform = resolve-apply');
  assert.equal(plan.stages[1].mode, 'deterministic', 'leveling = deterministic');
  assert.deepEqual(plan.stages[1].config.groups, ['Host'], 'stage carries resolved config');

  // Injected executor stands in for "extract frames + run the drx tool".
  const calls = [];
  const executor = async (stage) => {
    calls.push(stage.stage);
    return { ran: stage.stage, tools: stage.tools, gradeCount: 3 };
  };

  // First pass: conform is a Resolve stage → runner emits a plan and stops (Node can't apply).
  let r = await runAll(db, plan.runId, { executor, now: T });
  assert.equal(r.stopped, 'planned_resolve');
  assert.equal(r.at, 0);
  assert.equal(getRun(db, plan.runId).status, 'awaiting_apply');

  // Agent applies conform live, marks it done; resume.
  markStageApplied(db, plan.runId, 0, { result: { imported: true }, now: T });
  r = await runAll(db, plan.runId, { executor, now: T });
  assert.equal(r.stopped, 'awaiting_gate', 'leveling pauses on its review gate');
  assert.equal(r.at, 1);

  // Sign off the gate; resume → leveling executes deterministically, qc runs, done.
  approveGate(db, plan.runId, 1, { now: T });
  r = await runAll(db, plan.runId, { executor, now: T });
  assert.equal(r.stopped, 'complete');
  assert.deepEqual(calls, ['leveling', 'qc'], 'both deterministic stages ran via executor');

  const run = getRun(db, plan.runId);
  assert.equal(run.status, 'done');
  assert.equal(run.stages.find((s) => s.stage === 'leveling').result.gradeCount, 3);

  // Readback: record decoded look actual + detect drift vs intent.
  upsertEntity(db, { slug: 'e012.group.Host', kind: 'group', resolved: { look: { lut: 'Kodak_5219' } }, now: T });
  const rec = reconcile(db, 'e012.group.Host', { facts: { 'look.lut': 'Kodak_5219' }, pushFields: [{ field: 'look.lut' }], source: 'route_a', now: T });
  assert.equal(rec.drift.length, 0, 'decoded look matches intent → no drift');
  assert.equal(listDrift(db, { entitySlug: 'e012.group.Host', status: 'resolved' }).length, 1);
  db.close();
});
