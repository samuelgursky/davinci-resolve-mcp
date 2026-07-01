'use strict';

/**
 * Advisory escalation policy tests — client-free. These encode the SAMPLE
 * non-negotiable: vision may raise a flag but can NEVER override the math.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { shouldConsultVision, reconcile, actionFor } = require('../compare/advisory');
const { FakeVisionValidator } = require('../adapters/vision-validator');

test('advisory: cost gate — borderline / alignment / propose-only are consulted; clear MATCH is not', () => {
  // Clear MATCH (above band): do NOT consult.
  assert.equal(shouldConsultVision({ verdict: 'MATCH', structure: 0.99 }, { mode: 'content-identity' }), false);
  // Clear WRONG (below band): do NOT consult.
  assert.equal(shouldConsultVision({ verdict: 'WRONG', structure: 0.40 }, { mode: 'content-identity' }), false);
  // Borderline: consult.
  assert.equal(shouldConsultVision({ verdict: 'MATCH', structure: 0.90 }, { mode: 'content-identity' }), true);
  // Alignment mode: always consult (metric doesn't apply).
  assert.equal(shouldConsultVision({ verdict: 'MATCH', structure: 0.99 }, { mode: 'alignment' }), true);
  // Stubborn propose-only repair: consult.
  assert.equal(shouldConsultVision({ verdict: 'WRONG', structure: 0.40 }, { proposeOnlyRepair: true }), true);
});

test('advisory: corroboration does NOT change the deterministic verdict or force auto-apply', () => {
  const det = { verdict: 'MATCH', structure: 0.90 };
  const adv = { verdict: 'MATCH', confidence: 0.8, advisory: true, provenance: { model: 'fake' } };
  const out = reconcile(det, adv);
  assert.equal(out.verdict, 'MATCH');
  assert.equal(out.finalAction, 'auto-apply-eligible'); // eligibility from the metric, not from vision
  assert.equal(out.reason, 'corroborated');
  assert.equal(out.escalated, false);
});

test('advisory: vision can NEVER flip a deterministic WRONG to MATCH — it escalates to human', () => {
  const det = { verdict: 'WRONG', structure: 0.40 };
  const adv = { verdict: 'MATCH', confidence: 0.9, advisory: true, provenance: { model: 'fake' } };
  const out = reconcile(det, adv);
  assert.notEqual(out.verdict, 'MATCH', 'must NOT become MATCH on vision say-so');
  assert.equal(out.verdict, 'REVIEW');
  assert.equal(out.finalAction, 'human-review');
  assert.equal(out.escalated, true);
});

test('advisory: vision RAISES a flag on a deterministic MATCH it disputes → human REVIEW', () => {
  const det = { verdict: 'MATCH', structure: 0.91 };
  const adv = { verdict: 'WRONG', confidence: 0.7, advisory: true, provenance: { model: 'fake' } };
  const out = reconcile(det, adv);
  assert.equal(out.verdict, 'REVIEW');
  assert.equal(out.escalated, true);
});

test('advisory: with no validator injected, the deterministic verdict stands unchanged', () => {
  const det = { verdict: 'MATCH', structure: 0.99 };
  const out = reconcile(det, null);
  assert.equal(out.verdict, 'MATCH');
  assert.equal(out.advisory, null);
  assert.equal(out.finalAction, 'auto-apply-eligible');
});

test('advisory: reconcile rejects a non-advisory result (cannot smuggle authority)', () => {
  const det = { verdict: 'MATCH', structure: 0.90 };
  assert.throws(() => reconcile(det, { verdict: 'WRONG', advisory: false }), /must be marked advisory/);
});

test('advisory: end-to-end with FakeVisionValidator on a borderline dark-grade-style cut', async () => {
  const det = { verdict: 'MATCH', structure: 0.90 }; // borderline
  const fake = new FakeVisionValidator({ dark_grade: { verdict: 'MATCH', confidence: 0.85, rationale: 'same scene' } });
  // Only consult because it's borderline.
  assert.equal(shouldConsultVision(det, { mode: 'content-identity' }), true);
  const adv = await fake.validate({}, {}, { label: 'dark_grade' });
  const out = reconcile(det, adv);
  assert.equal(out.verdict, 'MATCH');
  assert.equal(out.reason, 'corroborated');
  assert.equal(fake.calls.length, 1);
});

test('advisory: actionFor maps verdicts to the §15 policy', () => {
  assert.equal(actionFor('MATCH'), 'auto-apply-eligible');
  assert.equal(actionFor('OFFSET'), 'propose');
  assert.equal(actionFor('WRONG'), 'flag-v2');
  assert.equal(actionFor('REVIEW'), 'human-review');
});
