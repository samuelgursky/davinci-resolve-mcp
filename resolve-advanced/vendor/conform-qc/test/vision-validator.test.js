'use strict';

/** VisionValidator interface tests — client-free (no LLM, no network). */

const test = require('node:test');
const assert = require('node:assert/strict');

const { VisionValidator, FakeVisionValidator, isVisionValidator, normalizeAdvisory } = require('../adapters/vision-validator');

test('VisionValidator: base interface throws until implemented', async () => {
  const base = new VisionValidator();
  assert.equal(isVisionValidator(base), true);
  await assert.rejects(() => base.validate({}, {}, {}), /must be implemented/);
});

test('VisionValidator: fake returns scripted advisory results, keyed by label then mode', async () => {
  const fake = new FakeVisionValidator({
    dark_grade: { verdict: 'MATCH', confidence: 0.8, rationale: 'same scene, darker grade' },
    alignment: { verdict: 'WRONG', confidence: 0.7, rationale: 'different shot' },
    default: { verdict: 'UNSURE', confidence: 0.5, rationale: 'cannot tell' },
  });
  const a = await fake.validate({}, {}, { label: 'dark_grade' });
  assert.equal(a.verdict, 'MATCH');
  assert.equal(a.advisory, true, 'a VisionValidator result is ALWAYS advisory');
  assert.ok(a.provenance && a.provenance.model);
  const b = await fake.validate({}, {}, { mode: 'alignment' });
  assert.equal(b.verdict, 'WRONG');
  const c = await fake.validate({}, {}, {});
  assert.equal(c.verdict, 'UNSURE');
  assert.equal(fake.calls.length, 3, 'records its calls (for cost-gate assertions)');
});

test('VisionValidator: normalizeAdvisory enforces shape + clamps confidence + forces advisory', () => {
  const r = normalizeAdvisory({ verdict: 'MATCH', confidence: 1.7, provenance: { model: 'm', promptVersion: '1' } });
  assert.equal(r.confidence, 1);
  assert.equal(r.advisory, true);
  assert.throws(() => normalizeAdvisory({ verdict: 'DEFINITELY' }), /verdict must be one of/);
});

test('VisionValidator: duck-typed check rejects non-conforming objects', () => {
  assert.equal(isVisionValidator({}), false);
  assert.equal(isVisionValidator(new FakeVisionValidator()), true);
});
