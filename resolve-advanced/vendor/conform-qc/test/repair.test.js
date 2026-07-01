'use strict';

/** Repair ladder + §9 deterministic strategies — verified against golden_oracle. */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const pkg = require('../index');
const { makeRepairLadder, strategies } = require('../repair');
const { ConformKnowledge } = require('../knowledge');

const GOLDEN = JSON.parse(fs.readFileSync(path.join(pkg.reelFixtureDir(), 'golden_oracle.json'), 'utf8'));
const CTX = { ticksPerFrame: GOLDEN.ticksPerFrame, sequenceWidth: GOLDEN.sequence.width };

test('repair: scale-double-count normalizes per source width for all 327 (== expected)', () => {
  let checked = 0;
  for (const c of GOLDEN.clips) {
    assert.equal(strategies.scaleDoubleCount.detect(c, CTX), true, `@${c.seqstart} should detect double-count`);
    const p = strategies.scaleDoubleCount.propose(c, CTX);
    assert.ok(Math.abs(p.fix.scale - c.expected_scale_corrected) < 0.001, `@${c.seqstart} ${p.fix.scale} != ${c.expected_scale_corrected}`);
    checked += 1;
  }
  assert.equal(checked, 327);
});

test('repair: subclip-offset reproduces source_start for subclip clips', () => {
  const subs = GOLDEN.clips.filter((c) => c.is_subclip);
  assert.ok(subs.length > 0);
  for (const c of subs) {
    assert.equal(strategies.subclipOffset.detect(c), true);
    assert.equal(strategies.subclipOffset.propose(c).fix.sourceFrame, c.expected_source_start);
  }
});

test('repair: ticks-retime detects only retimes and derives the ticks sample frame', () => {
  const retimes = GOLDEN.clips.filter((c) => strategies.ticksRetime.detect(c, CTX));
  assert.ok(retimes.length >= 1 && retimes.length < GOLDEN.clips.length, 'some but not all clips are retimes');
  for (const c of retimes) {
    const p = strategies.ticksRetime.propose(c, CTX);
    assert.equal(p.fix.sampleFrame, Math.round(c.pproTicksIn / CTX.ticksPerFrame));
    assert.notEqual(p.fix.sampleFrame, c.xml_in); // ticks != in for a retime
  }
});

test('repair: stale-relink re-resolves by exact basename via the media index', () => {
  const mediaIndex = { byBasename: (n) => (n === 'A.mov' ? '/vol/online/A.mov' : null) };
  const cut = { source_basename: 'A.mov', pathMissing: true };
  assert.equal(strategies.staleRelink.detect(cut, { mediaIndex }), true);
  assert.equal(strategies.staleRelink.propose(cut, { mediaIndex }).fix.path, '/vol/online/A.mov');
  // No match => no fix.
  const miss = strategies.staleRelink.propose({ source_basename: 'Z.mov', pathMissing: true }, { mediaIndex });
  assert.equal(miss.fix, null);
});

test('repair ladder: auto-applies a deterministic fix and records to ConformKnowledge', async () => {
  const knowledge = new ConformKnowledge();
  const ladder = makeRepairLadder({ knowledge });
  // A subclip cut with scale already normalized (so subclip is the matching strategy).
  const cut = { cutId: 'c1', is_subclip: true, subclip_startoffset: 5146, xml_in: 406, pproTicksIn: 406 * CTX.ticksPerFrame, scale_premiere: 100, srcW: CTX.sequenceWidth };
  const res = await ladder.repair(cut, CTX);
  assert.equal(res.klass, 'subclip-offset');
  assert.equal(res.accepted, true);
  assert.equal(res.mode, 'auto-apply');
  assert.equal(res.proposal.fix.sourceFrame, 5552); // 5146 + 406
  assert.ok(knowledge.query({ class: 'subclip-offset' }).confidence > 0.5);
});

test('repair ladder: an unmatched cut flags to V2', async () => {
  const ladder = makeRepairLadder({});
  const clean = { cutId: 'ok', is_subclip: false, xml_in: 1000, pproTicksIn: 1000 * CTX.ticksPerFrame, scale_premiere: 100, srcW: CTX.sequenceWidth };
  const res = await ladder.repair(clean, CTX);
  assert.equal(res.mode, 'flag-v2');
  assert.equal(res.klass, 'unrepairable');
});

test('repair ladder: re-verify can reject a deterministic fix (propose -> auto-rejected)', async () => {
  const ladder = makeRepairLadder({ reverify: async () => ({ ok: false, confidence: 0.2 }) });
  const cut = { cutId: 'c', is_subclip: true, subclip_startoffset: 100, xml_in: 5, pproTicksIn: 5 * CTX.ticksPerFrame, scale_premiere: 100, srcW: CTX.sequenceWidth };
  const res = await ladder.repair(cut, CTX);
  assert.equal(res.accepted, false, 'a fix that fails re-verify must not auto-apply');
  assert.equal(res.mode, 'auto-rejected');
});
