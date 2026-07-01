/**
 * P3.1 — smoke test: package resolves + exports the three top-level
 * functions. The functions themselves throw 'not yet implemented' until
 * P3.2/P3.3/P3.4 ship; this test just locks in the scaffold contract.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const drt = require('..');

test('drt-format: package resolves with parseDRT/buildDRT/validateDRT', () => {
  assert.equal(typeof drt.parseDRT, 'function');
  assert.equal(typeof drt.buildDRT, 'function');
  assert.equal(typeof drt.validateDRT, 'function');
});

// All three top-level functions are now real (P3.2/P3.3/P3.4); the
// scaffold-era stub assertions have been retired in favor of behavior
// tests in parse.test.js / build.test.js / validate.test.js.

test('drt-format: workspace dep on drp-format resolves', () => {
  const drp = require('../../drp-format');
  assert.equal(typeof drp.buildDRP, 'function');
  assert.equal(typeof drp.injectGrades, 'function');
  assert.equal(typeof drp.diff, 'function');
});
