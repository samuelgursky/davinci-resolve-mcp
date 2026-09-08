/** color_trace identity tiers — pure match engine, no DB, no Resolve. */

import test from 'node:test';
import assert from 'node:assert/strict';
import { matchClips, normalize } from '../server/tools/color_trace.mjs';
import { dedupeVersionRows } from '../server/tools/project_read.mjs';

const clip = (o) => ({ itemId: o.itemId || `${o.name}|${o.start}`, trackType: 0, duration: 24, reel: '', mediaPath: '', poolId: null, ...o });
const P = '/Volumes/online/show/A001C003_240101_R1AB.mov';

test('media-exact beats a name match: same file, same in-point, same duration', () => {
  const src = [clip({ name: 'SHOT_010', start: 1000, sourceIn: 48, mediaPath: P, gradeBody: 'aa' })];
  const tgt = [clip({ name: 'renamed clip', start: 5000, sourceIn: 48, mediaPath: P })];
  const [m] = matchClips(src, tgt);
  assert.equal(m.method, 'media-exact');
  assert.equal(m.confidence, 1);
  assert.equal(m.src.name, 'SHOT_010');
  assert.equal(m.ambiguous, false);
});

test('stringout: same name + same file, sections told apart by source-range overlap', () => {
  // one long file cut into three graded sections — the case native ColorTrace loses
  const src = [
    clip({ itemId: 's1', name: 'MASTER.mov', start: 0, duration: 100, sourceIn: 0, mediaPath: P, gradeBody: 'g1' }),
    clip({ itemId: 's2', name: 'MASTER.mov', start: 100, duration: 100, sourceIn: 100, mediaPath: P, gradeBody: 'g2' }),
    clip({ itemId: 's3', name: 'MASTER.mov', start: 200, duration: 100, sourceIn: 200, mediaPath: P, gradeBody: 'g3' }),
  ];
  // the new cut trims into the middle section and reorders it first
  const tgt = [clip({ name: 'MASTER.mov', start: 0, duration: 40, sourceIn: 130, mediaPath: P })];
  const [m] = matchClips(src, tgt);
  assert.equal(m.method, 'media-overlap');
  assert.equal(m.src.itemId, 's2');
  assert.deepEqual(m.sourceOverlap, { frames: 40, fraction: 1 });
  assert.equal(m.ambiguous, false);
});

test('a target straddling two sections takes the larger overlap and reports the fraction', () => {
  const src = [
    clip({ itemId: 's1', name: 'M', start: 0, duration: 100, sourceIn: 0, mediaPath: P, gradeBody: 'g1' }),
    clip({ itemId: 's2', name: 'M', start: 100, duration: 100, sourceIn: 100, mediaPath: P, gradeBody: 'g2' }),
  ];
  const tgt = [clip({ name: 'M', start: 0, duration: 50, sourceIn: 70, mediaPath: P })]; // 30 in s1, 20 in s2
  const [m] = matchClips(src, tgt);
  assert.equal(m.src.itemId, 's1');
  assert.equal(m.sourceOverlap.frames, 30);
  assert.equal(m.sourceOverlap.fraction, 0.6);
});

test('identical candidates tie → nearest record start wins and the match is flagged ambiguous', () => {
  const src = [
    clip({ itemId: 's1', name: 'M', start: 0, duration: 100, sourceIn: 0, mediaPath: P, gradeBody: 'g1' }),
    clip({ itemId: 's2', name: 'M', start: 900, duration: 100, sourceIn: 0, mediaPath: P, gradeBody: 'g2' }),
  ];
  const tgt = [clip({ name: 'M', start: 880, duration: 100, sourceIn: 0, mediaPath: P })];
  const [m] = matchClips(src, tgt);
  assert.equal(m.method, 'media-exact');
  assert.equal(m.src.itemId, 's2');
  assert.equal(m.ambiguous, true);
  assert.equal(m.candidates, 2);
});

test('pool id identifies media when the file path differs (relinked to another volume)', () => {
  const src = [clip({ name: 'A', start: 0, sourceIn: 10, mediaPath: '/Volumes/nearline/x.mov', poolId: 'uuid-1', gradeBody: 'g' })];
  const tgt = [clip({ name: 'B', start: 0, sourceIn: 10, mediaPath: '/Volumes/online/x.mov', poolId: 'uuid-1' })];
  const [m] = matchClips(src, tgt);
  assert.equal(m.method, 'media-exact');
});

test('reel name + overlap catches a re-conform from a different path with a different pool id', () => {
  const src = [
    clip({
      name: 'A001C003',
      start: 0,
      duration: 50,
      sourceIn: 100,
      reel: 'A001C003_240101_R1AB',
      mediaPath: '/old/A001C003_240101_R1AB.mxf',
      poolId: 'p1',
      gradeBody: 'g',
    }),
  ];
  const tgt = [
    clip({
      name: 'V2_A001C003',
      start: 0,
      duration: 30,
      sourceIn: 110,
      reel: 'A001C003_240101_R1AB',
      mediaPath: '/new/A001C003_240101_R1AB.mov',
      poolId: 'p2',
    }),
  ];
  const [m] = matchClips(src, tgt);
  assert.equal(m.method, 'reel-overlap');
  assert.equal(m.confidence, 0.9);
});

test('basename + overlap catches relocated media with no reel', () => {
  const src = [clip({ name: 'A', start: 0, duration: 50, sourceIn: 100, mediaPath: '/old/dir/clip.mov', gradeBody: 'g' })];
  const tgt = [clip({ name: 'B', start: 0, duration: 30, sourceIn: 110, mediaPath: '/new/place/CLIP.MOV' })];
  const [m] = matchClips(src, tgt);
  assert.equal(m.method, 'basename-overlap');
});

test('same media but an unreadable in-point degrades to media-only, below the name tiers', () => {
  const src = [clip({ name: 'A', start: 0, sourceIn: null, mediaPath: P, gradeBody: 'g' })];
  const tgt = [clip({ name: 'B', start: 0, sourceIn: null, mediaPath: P })];
  const [m] = matchClips(src, tgt);
  assert.equal(m.method, 'media-only');
  assert.equal(m.confidence, 0.7);
});

test('name tiers remain the fallback when no media identity lines up', () => {
  const src = [
    clip({ name: 'Shot_020_v3', start: 0, sourceIn: 0, mediaPath: '/a.mov', gradeBody: 'g' }),
    clip({ name: 'Exact', start: 0, sourceIn: 0, mediaPath: '/b.mov', gradeBody: 'g' }),
  ];
  const tgt = [
    clip({ name: 'Exact', start: 0, sourceIn: 0, mediaPath: '/c.mov' }),
    clip({ name: 'shot-020_v7', start: 0, sourceIn: 0, mediaPath: '/d.mov' }),
    clip({ name: 'Nothing like it', start: 0, sourceIn: 0, mediaPath: '/e.mov' }),
  ];
  const r = matchClips(src, tgt);
  assert.equal(r[0].method, 'exact-name');
  assert.equal(r[1].method, 'normalized-name');
  assert.equal(r[2].src, null);
  assert.equal(r[2].confidence, 0);
});

test('normalize strips extension, separators and a trailing version token', () => {
  assert.equal(normalize('/x/Shot_020_v3.mov'), 'shot 020');
  assert.equal(normalize('SHOT-020.01'), 'shot 020');
});

test('dedupeVersionRows keeps the active version row of an item with several corrected versions', () => {
  const rows = [
    { itemId: 'i1', gradeIsActive: 0, gradeBody: 'old' },
    { itemId: 'i1', gradeIsActive: 1, gradeBody: 'active' },
    { itemId: 'i2', gradeIsActive: 0, gradeBody: 'only' },
  ];
  const out = dedupeVersionRows(rows);
  assert.equal(out.length, 2);
  assert.equal(out.find((r) => r.itemId === 'i1').gradeBody, 'active');
});
