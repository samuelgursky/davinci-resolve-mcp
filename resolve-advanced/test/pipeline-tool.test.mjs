/**
 * pipeline MCP tool surface — exercises the agent-facing handler end-to-end, including a
 * REAL deterministic stage dispatch through the drx tool (gamut_legal on a synth frame).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pipelineTool } from '../server/tools/pipeline.mjs';

const require = createRequire(import.meta.url);
const sharp = require('sharp');
const T = '2026-06-29T00:00:00Z';
const call = (action, args) => pipelineTool.handler({ action, args });

async function midGray(file) {
  const buf = Buffer.alloc(32 * 32 * 3, 128);
  await sharp(buf, { raw: { width: 32, height: 32, channels: 3 } })
    .png()
    .toFile(file);
}

test('pipeline tool: compile → plan → execute real deterministic stage → readback', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ptool-'));
  const dbPath = path.join(dir, 'project.db');
  const frame = path.join(dir, 'f.png');
  await midGray(frame);

  const compiled = await call('compile', {
    dbPath,
    now: T,
    specs: [
      { slug: 'doc', kind: 'type', config: { color: { science: 'acescct' } } },
      { slug: 'e012', kind: 'episode', parent: 'doc', config: { qc: { maxIllegalPct: 1 }, pipeline: ['qc'] } },
    ],
  });
  assert.equal(compiled.count, 2);

  const ent = await call('get_entity', { dbPath, slug: 'e012' });
  assert.equal(ent.resolved.color.science, 'acescct');

  const cat = await call('catalog', {});
  assert.ok(cat.catalog.some((d) => d.id === 'gamut_legal'));

  const plan = await call('plan', { dbPath, episodeSlug: 'e012', now: T });
  assert.equal(plan.stages[0].stage, 'qc');
  assert.equal(plan.stages[0].mode, 'deterministic');

  // Execute the qc stage for real via the drx gamut_legal action (agent supplies inputs).
  const r = await call('execute_stage', {
    dbPath,
    runId: plan.runId,
    stageIndex: 0,
    now: T,
    toolArgs: { tool: 'gamut_legal', args: { clips: [{ id: 'f', png: frame }] } },
  });
  assert.equal(r.status, 'done');
  assert.equal(r.result.tool, 'gamut_legal');
  assert.equal(r.result.clips.f.pass, true, 'mid-gray frame is legal');

  const run = await call('get_run', { dbPath, runId: plan.runId });
  assert.equal(run.stages[0].status, 'done');

  // Readback + drift via the tool.
  await call('compile', { dbPath, now: T, specs: [{ slug: 'e012.group.Host', kind: 'group', config: { look: { lut: 'Kodak_5219' } } }] });
  const rb = await call('readback', {
    dbPath,
    entitySlug: 'e012.group.Host',
    now: T,
    facts: { 'look.lut': 'Kodak_5219' },
    pushFields: [{ field: 'look.lut' }],
    source: 'route_a',
  });
  assert.equal(rb.drift.length, 0);

  const prov = await call('provenance', { dbPath, runId: plan.runId });
  assert.ok(prov.events.length >= 2, 'plan + execute provenance recorded');
});

test('pipeline tool: unknown action throws', async () => {
  await assert.rejects(() => call('frobnicate', { dbPath: '/x' }), /Unknown pipeline action/);
});
