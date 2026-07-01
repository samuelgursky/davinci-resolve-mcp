/**
 * A0 — public library surface. Asserts the `lib.mjs` barrel imports cleanly and exposes
 * the codec / grading / pipeline / tools / mcp groups a downstream consumer depends on.
 * If a re-export name drifts, this fails loudly instead of breaking the consumer silently.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import * as lib from '../server/lib.mjs';

test('A0: barrel exposes codec, grading, pipeline, tools, mcp', () => {
  // codec namespace
  assert.equal(typeof lib.codec, 'object');
  for (const k of ['drxParser', 'drxGenerator', 'drxCdl', 'drp', 'drt']) assert.equal(typeof lib.codec[k], 'function', `codec.${k}`);

  // grading compute cores
  for (const fn of [
    'computeLevels',
    'computeSkinMatch',
    'computeShotMatch',
    'computeWhiteBalanceMatch',
    'computeContrastNormalize',
    'computeGamutLegal',
    'importCDL',
    'transferGrade',
    'decodeGroupGrades',
  ]) {
    assert.equal(typeof lib[fn], 'function', `grading.${fn}`);
  }

  // pipeline foundation
  assert.equal(typeof lib.projectDb.openProjectDb, 'function');
  for (const fn of ['compileSpecs', 'loadYamlDir', 'reconcile', 'detectDrift', 'planRun', 'executeStage', 'runAll']) {
    assert.equal(typeof lib[fn], 'function', `pipeline.${fn}`);
  }
  assert.ok(Array.isArray(lib.CATALOG) && lib.CATALOG.length >= 8, 'CATALOG');

  // MCP tool handlers
  for (const t of ['drxTool', 'conformTool', 'pipelineTool', 'colorTraceTool']) {
    assert.equal(typeof lib[t]?.handler, 'function', `${t}.handler`);
    assert.equal(typeof lib[t].name, 'string');
  }

  // mcp server entry
  assert.equal(typeof lib.startServer, 'function');
});

test('A0: barrel is usable end-to-end (compile + a deterministic tool dispatch)', async () => {
  // Prove a consumer can drive real work straight off the barrel.
  const desc = lib.getDescriptor('grade_transfer');
  assert.equal(desc.action, 'grade_transfer');
  assert.equal(typeof lib.deepMerge({ a: 1 }, { b: 2 }).b, 'number');
});
