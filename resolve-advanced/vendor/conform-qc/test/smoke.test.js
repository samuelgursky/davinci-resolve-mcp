'use strict';

/**
 * Smoke test — the baseline every session (and init.sh) runs first.
 *
 * It does NOT test any feature. It proves the harness itself is intact:
 *  - the package loads and exposes its scaffold surface,
 *  - the committed goldens (golden_oracle.json, golden_compare.json) parse and
 *    have the shape future feature tests rely on,
 *  - raw client material (turnover.xml, frames/) is reported present-or-absent
 *    so feature tests can skip-if-absent on a fresh clone.
 *
 * Run via `node --test test/` (see package.json). No jest, no babel, no network.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const pkg = require('../index');

const SAMPLE = pkg.reelFixtureDir();
const ORACLE = path.join(SAMPLE, 'golden_oracle.json');
const COMPARE = path.join(SAMPLE, 'golden_compare.json');
const TURNOVER = path.join(SAMPLE, 'turnover.xml');
const FRAMES_DIR = path.join(SAMPLE, 'frames');

test('package scaffold loads with planned module surface', () => {
  assert.equal(pkg.PACKAGE, 'conform-qc');
  assert.ok(Array.isArray(pkg.MODULES) && pkg.MODULES.length >= 10);
  for (const m of ['parse', 'oracle', 'compare', 'repair', 'report']) {
    assert.ok(pkg.MODULES.includes(m), `MODULES should list "${m}"`);
  }
});

test('golden_oracle.json — committed answer key for the Oracle (327 clips)', () => {
  const g = JSON.parse(fs.readFileSync(ORACLE, 'utf8'));
  assert.equal(g.clipCount, 327, 'clipCount must be 327');
  assert.equal(g.clips.length, 327, 'clips array must hold 327 entries');
  assert.equal(g.ticksPerFrame, 10584000000, 'ticks/frame @24 = 254016000000/24');
  assert.ok(g.sequence && g.sequence.width === 3600 && g.sequence.height === 2160);
  // Every clip must carry the inputs + the verified expected answers so the
  // Oracle is fully testable from this file alone (no raw XML required).
  const requiredKeys = [
    'seqstart', 'xml_in', 'subclip_startoffset', 'is_subclip', 'pproTicksIn',
    'scale_premiere', 'srcW', 'srcH', 'expected_source_start', 'expected_scale_corrected',
  ];
  for (const c of g.clips) {
    for (const k of requiredKeys) {
      assert.ok(k in c, `clip @${c.seqstart} missing "${k}"`);
    }
  }
});

test('golden_compare.json — committed answer key for the comparator (4 verdicts)', () => {
  const g = JSON.parse(fs.readFileSync(COMPARE, 'utf8'));
  assert.ok(Array.isArray(g.cases) && g.cases.length === 4);
  const byLabel = Object.fromEntries(g.cases.map((c) => [c.label, c]));
  // The four named ground-truth cases the comparator must satisfy, incl. the trap.
  assert.equal(byLabel.clean_match_hermes.expected_verdict, 'MATCH');
  assert.equal(byLabel.dark_grade_match.expected_verdict, 'MATCH'); // the brightness trap
  assert.equal(byLabel.genuine_wrong.expected_verdict, 'WRONG');
  assert.equal(byLabel.slowmo_via_ticks.expected_verdict, 'MATCH');
  for (const c of g.cases) {
    assert.ok(c.reference && c.derived, `${c.label} needs reference+derived paths`);
  }
});

test('raw client material presence is reported (skip-if-absent contract)', () => {
  // These are git-ignored: present in this working tree, gone on a fresh clone.
  // Feature tests that need them must skip when absent — this test only records
  // the state and never fails on absence.
  const haveXml = fs.existsSync(TURNOVER);
  const frames = fs.existsSync(FRAMES_DIR)
    ? fs.readdirSync(FRAMES_DIR).filter((f) => f.endsWith('.png'))
    : [];
  // eslint-disable-next-line no-console
  console.log(
    `[smoke] raw fixtures: turnover.xml=${haveXml ? 'present' : 'ABSENT'}, ` +
      `frames=${frames.length} png`,
  );
  if (haveXml && frames.length) {
    assert.equal(frames.length, 8, 'expect 8 reference/derived frame pairs when present');
  }
  assert.ok(true);
});
