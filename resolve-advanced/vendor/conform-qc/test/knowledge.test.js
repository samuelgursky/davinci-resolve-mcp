'use strict';

/** ConformKnowledge tests — client-free. */

const test = require('node:test');
const assert = require('node:assert/strict');

const { ConformKnowledge, signatureFor, confidenceOf } = require('../knowledge');

test('knowledge: signatureFor builds a stable canonical key', () => {
  assert.equal(signatureFor('scale-double-count'), 'scale-double-count');
  assert.equal(signatureFor({ class: 'per-file-offset', scope: 'file-7' }), 'per-file-offset:file-7');
  assert.equal(signatureFor({ failureMode: 'wrong-source', target: 'resolve' }), 'wrong-source:resolve');
  assert.throws(() => signatureFor({}), /no class\/failureMode/);
});

test('knowledge: a novel pattern is unseen until recorded', () => {
  const k = new ConformKnowledge();
  assert.equal(k.query('subclip-offset'), null);
  const e = k.record('subclip-offset', { strategy: 'add-startoffset', outcome: 'success', exampleRunId: 'run-1' });
  assert.equal(e.strategy, 'add-startoffset');
  assert.equal(e.occurrences, 1);
  assert.deepEqual(e.exampleRunIds, ['run-1']);
  // Now it's recognized immediately.
  assert.equal(k.query('subclip-offset').strategy, 'add-startoffset');
});

test('knowledge: repeated successes RAISE confidence; a failure lowers it', () => {
  const k = new ConformKnowledge();
  const c1 = k.record('scale-double-count', { strategy: 'normalize', outcome: 'success', exampleRunId: 'a' }).confidence;
  const c2 = k.record('scale-double-count', { strategy: 'normalize', outcome: 'success', exampleRunId: 'b' }).confidence;
  assert.ok(c2 > c1, `second success should raise confidence: ${c1} -> ${c2}`);
  const after = k.record('scale-double-count', { strategy: 'normalize', outcome: 'failure', exampleRunId: 'c' });
  assert.ok(after.confidence < c2, `a failure should lower confidence: ${c2} -> ${after.confidence}`);
  assert.equal(after.occurrences, 3);
  assert.deepEqual(after.exampleRunIds, ['a', 'b', 'c']);
  // confidence is the Laplace-smoothed success rate.
  assert.equal(after.confidence, confidenceOf(after.successes, after.failures));
});

test('knowledge: scope keys a recurring pattern per-site (per-file offset learned independently)', () => {
  const k = new ConformKnowledge();
  k.record({ class: 'per-file-offset', scope: 'file-7' }, { strategy: 'apply+111', outcome: 'success' });
  k.record({ class: 'per-file-offset', scope: 'file-9' }, { strategy: 'apply-3', outcome: 'success' });
  assert.equal(k.size, 2);
  assert.equal(k.query({ class: 'per-file-offset', scope: 'file-7' }).strategy, 'apply+111');
  assert.equal(k.query({ class: 'per-file-offset', scope: 'file-9' }).strategy, 'apply-3');
});

test('knowledge: seed round-trips and recomputes confidence', () => {
  const seed = new ConformKnowledge();
  seed.record('ticks-retime', { strategy: 'derive-from-ticks', outcome: 'success' });
  const reloaded = new ConformKnowledge(seed.all());
  assert.equal(reloaded.query('ticks-retime').strategy, 'derive-from-ticks');
  assert.equal(reloaded.query('ticks-retime').confidence, seed.query('ticks-retime').confidence);
});
