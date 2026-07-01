'use strict';

/** QC report model tests — client-free. */

const test = require('node:test');
const assert = require('node:assert/strict');

const { makeReport, addCut, badgeFor, toMetadataQc } = require('../report');

test('report: summary tallies per-cut verdicts', () => {
  const r = makeReport({ target: 'resolve', tier: 'B' });
  addCut(r, { cutId: 'c1', status: 'MATCH', hasReference: true, refScore: 0.99 });
  addCut(r, { cutId: 'c2', status: 'OFFSET', hasReference: true, refScore: 0.95, offset: { dx: 2, dy: 0, ds: 0 } });
  addCut(r, { cutId: 'c3', status: 'WRONG', hasReference: true, refScore: 0.4 });
  addCut(r, { cutId: 'c4', status: 'REVIEW', hasReference: true, escalated: true });
  addCut(r, { cutId: 'c5', status: 'MATH-VERIFIED', hasReference: false, derivedSourceFrame: 1000 });
  assert.deepEqual(r.summary, { matched: 1, offset: 1, wrong: 1, flagged: 2, review: 1, mathVerified: 1, unreadable: 0 });
  assert.equal(r.perCut.length, 5);
});

test('report: BADGE RULE — no picture, no content-verified', () => {
  // Tier C (no reference) can only be math-verified, never content-verified.
  assert.equal(badgeFor({ status: 'MATH-VERIFIED', hasReference: false }), 'math-verified');
  assert.equal(badgeFor({ status: 'MATCH', hasReference: false }), 'math-verified');
  // With a reference + MATCH => content-verified.
  assert.equal(badgeFor({ status: 'MATCH', hasReference: true }), 'content-verified');
  // A reference that did NOT verify => no positive badge.
  assert.equal(badgeFor({ status: 'WRONG', hasReference: true }), null);
  assert.equal(badgeFor({ status: 'REVIEW', hasReference: true }), null);
  // The guard hard-fails any attempt to mint content-verified without a picture.
  const r = makeReport();
  const entry = addCut(r, { cutId: 'x', status: 'MATH-VERIFIED', hasReference: false });
  assert.equal(entry.badge, 'math-verified');
});

test('report: unknown status is rejected', () => {
  const r = makeReport();
  assert.throws(() => addCut(r, { cutId: 'bad', status: 'PROBABLY', hasReference: true }), /unknown status/);
});

test('report: serializes to the metadata.editorial.qc shape (§11)', () => {
  const r = makeReport({ target: 'resolve', oracleVersion: '1', tier: 'C', runAt: '2026-06-16T00:00:00Z' });
  addCut(r, { cutId: 'seq192', status: 'MATH-VERIFIED', hasReference: false, derivedSourceFrame: 47962, scale: 100 });
  const m = toMetadataQc(r);
  for (const k of ['runAt', 'target', 'oracleVersion', 'tier', 'summary', 'perCut', 'packageKeys']) {
    assert.ok(k in m, `metadata.editorial.qc must have "${k}"`);
  }
  assert.equal(m.perCut[0].cutId, 'seq192');
  assert.equal(m.perCut[0].derivedFrame, 47962);
  assert.equal(m.perCut[0].badge, 'math-verified');
  assert.equal(m.summary.mathVerified, 1);
});
