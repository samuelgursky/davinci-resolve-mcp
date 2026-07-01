'use strict';

/**
 * Geometry-capture tests — verified END-TO-END against the RAW turnover.xml and
 * the committed golden_oracle.json answer key.
 *
 * turnover.xml is git-ignored raw client material (present locally, gone on a
 * fresh clone), so these SKIP-IF-ABSENT. The portable synthetic fixture (a later
 * P0 feature) gives the suite client-free coverage of the same parser.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const pkg = require('../index');
const { parseGeometry } = require('../parse/xmeml-geometry');
const resolveTarget = require('../oracle/resolve');

const DIR = pkg.reelFixtureDir();
const XML_PATH = path.join(DIR, 'turnover.xml');
const HAVE_XML = fs.existsSync(XML_PATH);
const SKIP = HAVE_XML ? false : 'turnover.xml absent (git-ignored raw material) — skipping';

const GOLDEN = JSON.parse(fs.readFileSync(path.join(DIR, 'golden_oracle.json'), 'utf8'));

// Parse once (only if present).
const PARSED = HAVE_XML ? parseGeometry(fs.readFileSync(XML_PATH, 'utf8')) : null;
const BY_SEQ = PARSED ? new Map(PARSED.clips.map((c) => [c.seqstart, c])) : new Map();

/** Run fn over every golden clip's matching parsed clip; collect field mismatches. */
function compareField(field) {
  const mismatches = [];
  for (const gc of GOLDEN.clips) {
    const pc = BY_SEQ.get(gc.seqstart);
    assert.ok(pc, `parser missing golden clip @seq${gc.seqstart}`);
    if (JSON.stringify(pc[field]) !== JSON.stringify(gc[field])) {
      mismatches.push({ seq: gc.seqstart, parser: pc[field], golden: gc[field] });
    }
  }
  return mismatches;
}

test('geometry: file-ids resolved — source_basename for all 327 (no self-closing leaks)', { skip: SKIP }, () => {
  // Every golden clip's source resolves to the right basename via the file-id map
  // (most clips reference a self-closing <file id=".."/> — proves pass-1 resolution).
  const mismatches = compareField('source_basename');
  assert.deepEqual(mismatches, [], `source_basename mismatches: ${JSON.stringify(mismatches.slice(0, 5))}`);
  // No golden clip may be left with an unresolved (null) fileId/basename.
  for (const gc of GOLDEN.clips) {
    const pc = BY_SEQ.get(gc.seqstart);
    assert.ok(pc.fileId, `clip @seq${gc.seqstart} has no resolved fileId`);
    assert.ok(pc.source_basename, `clip @seq${gc.seqstart} has no resolved source_basename`);
  }
  // eslint-disable-next-line no-console
  console.log(`[geometry] file-ids resolved: 327/327 source_basename (parsed ${PARSED.clips.length} clips, ${Object.keys(PARSED.fileDefs).length} file defs)`);
});

test('geometry: pproTicksIn captured for all 327 (Resolve reads ticks)', { skip: SKIP }, () => {
  const mismatches = compareField('pproTicksIn');
  assert.deepEqual(mismatches, [], `pproTicksIn mismatches: ${JSON.stringify(mismatches.slice(0, 5))}`);
  // eslint-disable-next-line no-console
  console.log('[geometry] pproTicksIn: 327/327 match golden');
});

test('geometry: subclip startoffset + is_subclip captured for all 327', { skip: SKIP }, () => {
  const offMismatch = compareField('subclip_startoffset');
  const flagMismatch = compareField('is_subclip');
  assert.deepEqual(offMismatch, [], `subclip_startoffset mismatches: ${JSON.stringify(offMismatch.slice(0, 5))}`);
  assert.deepEqual(flagMismatch, [], `is_subclip mismatches: ${JSON.stringify(flagMismatch.slice(0, 5))}`);
  const subs = GOLDEN.clips.filter((c) => c.is_subclip).length;
  // eslint-disable-next-line no-console
  console.log(`[geometry] subclip: 327/327 (is_subclip + startoffset); ${subs} subclips`);
});

test('geometry: scale (basic-motion filter) captured for all 327', { skip: SKIP }, () => {
  const mismatches = compareField('scale_premiere');
  assert.deepEqual(mismatches, [], `scale_premiere mismatches: ${JSON.stringify(mismatches.slice(0, 5))}`);
  // eslint-disable-next-line no-console
  console.log('[geometry] scale_premiere: 327/327 match golden');
});

test('geometry: source samplecharacteristics W/H captured for all 327', { skip: SKIP }, () => {
  const w = compareField('srcW');
  const h = compareField('srcH');
  assert.deepEqual(w, [], `srcW mismatches: ${JSON.stringify(w.slice(0, 5))}`);
  assert.deepEqual(h, [], `srcH mismatches: ${JSON.stringify(h.slice(0, 5))}`);
  // eslint-disable-next-line no-console
  console.log('[geometry] srcW/srcH: 327/327 match golden (resolved via file-id, not sequence dims)');
});

test('geometry: speed (Time Remap) captured + agrees with ticks-based retime', { skip: SKIP }, () => {
  const ctx = { ticksPerFrame: GOLDEN.ticksPerFrame, sequenceWidth: GOLDEN.sequence.width };
  let retimes = 0;
  const disagreements = [];
  for (const gc of GOLDEN.clips) {
    const pc = BY_SEQ.get(gc.seqstart);
    assert.equal(typeof pc.speed, 'number', `clip @seq${gc.seqstart} has no captured speed`);
    const ticksRetimed = resolveTarget.isRetimed(gc, ctx);
    if (ticksRetimed) retimes += 1;
    // The two independent retime signals (Time-Remap speed != 100 and
    // ticks/tpf != <in>) MUST agree — that consistency is the whole point.
    if (ticksRetimed !== (pc.speed !== 100)) {
      disagreements.push({ seq: gc.seqstart, speed: pc.speed, ticksRetimed });
    }
  }
  assert.ok(retimes >= 1, 'fixture must contain at least one retimed (slow-mo) clip');
  assert.deepEqual(disagreements, [], `speed<->ticks disagreements: ${JSON.stringify(disagreements)}`);
  // eslint-disable-next-line no-console
  console.log(`[geometry] speed: captured for 327/327; ${retimes} retimes; speed<->ticks agree 327/327`);
});
