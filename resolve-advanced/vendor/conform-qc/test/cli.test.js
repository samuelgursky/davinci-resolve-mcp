'use strict';

/** CLI entry tests — runCli programmatically + a real subprocess invocation. */

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const { runCli } = require('../cli');

const SYNTH_MODEL = path.join(__dirname, '..', '__fixtures__', 'synthetic', 'golden_oracle.synth.json');
const CLI = path.join(__dirname, '..', 'cli.js');

test('cli: verify on the synthetic model returns a Tier-C report (exit 0)', async () => {
  const r = await runCli(['verify', SYNTH_MODEL]);
  assert.equal(r.code, 0);
  assert.equal(r.report.summary.mathVerified, r.report.perCut.length);
  assert.match(r.output, /conform-qc verify/);
  assert.match(r.output, /math-verified=/);
});

test('cli: bad usage and unreadable model exit non-zero', async () => {
  assert.equal((await runCli([])).code, 2);
  assert.equal((await runCli(['verify', '/no/such/model.json'])).code, 1);
});

test('cli: --json emits the per-cut report', async () => {
  const r = await runCli(['verify', SYNTH_MODEL, '--json']);
  const parsed = JSON.parse(r.output);
  assert.ok(parsed.summary && Array.isArray(parsed.perCut));
  assert.equal(parsed.perCut.length, 4);
});

test('cli: runs as a real subprocess and exits 0', () => {
  const out = execFileSync('node', [CLI, 'verify', SYNTH_MODEL], { encoding: 'utf8' });
  assert.match(out, /conform-qc verify/);
  assert.match(out, /cuts: 4/);
});
