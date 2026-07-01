'use strict';

/**
 * P2 — Resolve-in-the-loop, verified against the REAL tool (non-negotiable #1).
 *
 * Gated on a reachable headless Resolve AND the raw turnover.xml (git-ignored).
 * Imports the SAMPLE turnover headless (media OFFLINE), reads back each clip's
 * conformed source_start via GetLeftOffset, and asserts it equals the Oracle for
 * all 327 — the calibration that PROVES the Oracle ruleset. Then exports a DRP
 * and re-opens it.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const pkg = require('../index');
const oracle = require('../oracle');
const { isResolveDriver } = require('../adapters/resolve-driver');
const { HeadlessResolveDriver } = require('../adapters/resolve-headless-driver');

const SAMPLE = pkg.reelFixtureDir();
const XML = path.join(SAMPLE, 'turnover.xml');
const GOLDEN = JSON.parse(fs.readFileSync(path.join(SAMPLE, 'golden_oracle.json'), 'utf8'));
const CTX = { ticksPerFrame: GOLDEN.ticksPerFrame, sequenceWidth: GOLDEN.sequence.width };

const driver = new HeadlessResolveDriver();
const resolveUp = !!driver.ping();
const haveXml = fs.existsSync(XML);
const SKIP = resolveUp && haveXml ? false : `Resolve ${resolveUp ? 'up' : 'unreachable'} / turnover ${haveXml ? 'present' : 'absent'} — skipping P2`;

test('P2: HeadlessResolveDriver satisfies the ResolveDriver interface', () => {
  assert.equal(isResolveDriver(driver), true);
});

test('P2 read-back + ACCEPTANCE: Resolve clip_where == Oracle for all 327 (offline import)', { skip: SKIP }, async () => {
  await driver.importTimeline(XML);
  const rows = await driver.clipWhere();
  const bySeq = new Map(rows.map((r) => [r.seqstart, r]));

  let checked = 0;
  const mismatches = [];
  for (const c of GOLDEN.clips) {
    const row = bySeq.get(c.seqstart);
    assert.ok(row, `Resolve read-back missing clip @seq${c.seqstart}`);
    const oracleSrc = oracle.derive(c, CTX).derivedSourceFrame;
    // The real tool == the golden == the Oracle.
    if (row.source_start !== c.expected_source_start || oracleSrc !== row.source_start) {
      mismatches.push({ seq: c.seqstart, resolve: row.source_start, golden: c.expected_source_start, oracle: oracleSrc });
    }
    checked += 1;
  }
  assert.equal(checked, 327);
  assert.deepEqual(mismatches, [], `Oracle-vs-Resolve mismatches: ${JSON.stringify(mismatches.slice(0, 5))}`);
  // eslint-disable-next-line no-console
  console.log(`[P2] CALIBRATION: Resolve clip_where == Oracle for 327/327 (headless, media offline)`);
}, { timeout: 180000 });

test('P2 DRP export: import -> export .drp -> re-open clean', { skip: SKIP }, async () => {
  const out = path.join(os.tmpdir(), `conformqc_${process.pid}.drp`);
  try {
    const res = await driver.authorDrp(XML, out);
    assert.ok(res.drpPath, 'a .drp path is returned');
    assert.equal(res.validArchive, true, 'the exported .drp is a well-formed archive');
    assert.ok(res.entryCount > 0 && res.size > 0, 'the .drp is non-trivial');
  } finally {
    fs.rmSync(out, { force: true });
  }
}, { timeout: 180000 });
