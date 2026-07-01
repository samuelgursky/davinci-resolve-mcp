/**
 * Cluster M — media front-end / AE. fs-based ops tested with real temp files; TC math + sync
 * tested purely; media_inventory gated on ffmpeg.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { sealFiles, verifyFiles, findDupesByHash, relinkManifest, renamePlan, reelNormalize, projectHygiene, turnoverPackage } from '../server/media-ops.mjs';
import { mediaInventory, syncByTC, tcToFrames, framesToTc } from '../server/media-inventory.mjs';
import { hasFfmpeg, hasFfprobe } from '../server/capabilities.mjs';

const FF = hasFfmpeg() && hasFfprobe();

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'media-'));
}

test('ingest_verify: seal then verify detects a changed + missing file', () => {
  const dir = tmp();
  const a = path.join(dir, 'A001C001.mov');
  const b = path.join(dir, 'A001C002.mov');
  fs.writeFileSync(a, 'clip-one-bytes');
  fs.writeFileSync(b, 'clip-two-bytes');
  const seal = sealFiles([a, b]);
  assert.equal(seal.count, 2);
  assert.ok(seal.totalBytes > 0);
  // Clean verify.
  assert.equal(verifyFiles(seal).pass, true);
  // Corrupt one, delete the other.
  fs.writeFileSync(b, 'clip-two-bytes-CORRUPT');
  fs.unlinkSync(a);
  const v = verifyFiles(seal);
  assert.equal(v.pass, false);
  assert.equal(v.results.find((r) => r.name === 'A001C001.mov').status, 'missing');
  assert.equal(v.results.find((r) => r.name === 'A001C002.mov').status, 'changed');
});

test('ingest_verify: seal refuses a 0-byte file (empty-green guard)', () => {
  const dir = tmp();
  const z = path.join(dir, 'zero.mov');
  fs.writeFileSync(z, '');
  assert.throws(() => sealFiles([z]), /0 bytes/);
});

test('dupes are found by HASH, not name', () => {
  const dir = tmp();
  const a = path.join(dir, 'A001C001.mov');
  const b = path.join(dir, 'copy_of_A001C001.mov');
  const c = path.join(dir, 'different.mov');
  fs.writeFileSync(a, 'same-content');
  fs.writeFileSync(b, 'same-content'); // dup content, different name
  fs.writeFileSync(c, 'other');
  const r = findDupesByHash([a, b, c]);
  assert.equal(r.dupeGroups, 1);
  assert.deepEqual(r.dupes[0].names.sort(), ['A001C001.mov', 'copy_of_A001C001.mov']);
});

test('relink_manifest: longest-prefix wins, missing target stays offline', () => {
  const dir = tmp();
  const present = path.join(dir, 'new', 'A001C001.mov');
  fs.mkdirSync(path.dirname(present), { recursive: true });
  fs.writeFileSync(present, 'x');
  const r = relinkManifest(['/old/vol/A001C001.mov', '/old/vol/A001C002.mov', '/unmapped/x.mov'], [{ from: '/old/vol', to: path.join(dir, 'new') }]);
  assert.equal(r.relinkableCount, 1);
  assert.equal(r.relinkable[0].to, present);
  assert.ok(r.stillOffline.some((s) => s.from.endsWith('A001C002.mov')));
  assert.deepEqual(r.unmapped, ['/unmapped/x.mov']);
});

test('rename_plan REFUSES camera originals and flags collisions', () => {
  const r = renamePlan(['A001C001.mov', 'interview_wide.mov', 'interview_cu.mov'], { find: 'interview_.*', replace: 'EP012_INT.mov' });
  const cam = r.plan.find((p) => p.from === 'A001C001.mov');
  assert.equal(cam.action, 'refuse-camera-original');
  // Both interviews map to the same target → collision.
  assert.equal(r.collisions, 2);
});

test('reel_normalize uppercases and zero-pads', () => {
  const r = reelNormalize(['a1', 'a02', 'B003']);
  assert.equal(r.plan.find((p) => p.from === 'a1').to, 'A001');
  assert.equal(r.plan.find((p) => p.from === 'B003').action, 'noop');
});

test('project_hygiene finds offline, dupes, mixed-fps, empty bins, unlabeled versions', () => {
  const r = projectHygiene({
    clips: [
      { id: 'c1', online: false, hash: 'h1' },
      { id: 'c2', online: true, hash: 'h2' },
      { id: 'c3', online: true, hash: 'h2' }, // dup of c2 by hash
    ],
    timelines: [{ name: 'TL1', fps: 24, clipFps: [24, 25] }],
    bins: [
      { name: 'Empty', clipCount: 0 },
      { name: 'Full', clipCount: 3 },
    ],
    versions: [{ name: 'v1', label: 'approved' }, { name: 'v2' }],
  });
  assert.equal(r.clean, false);
  assert.deepEqual(r.findings.offlineClips, ['c1']);
  assert.equal(r.findings.dupes[0].ids.sort().join(','), 'c2,c3');
  assert.deepEqual(r.findings.mixedFpsTimelines, ['TL1']);
  assert.deepEqual(r.findings.emptyBins, ['Empty']);
  assert.deepEqual(r.findings.unlabeledVersions, ['v2']);
});

test('turnover_package assembles a dated, checksummed, categorized manifest', () => {
  const dir = tmp();
  const grade = path.join(dir, 'shot.mov');
  const ref = path.join(dir, 'ref.mov');
  fs.writeFileSync(grade, 'graded');
  fs.writeFileSync(ref, 'reference');
  const r = turnoverPackage(
    [
      { path: grade, category: 'color', role: 'hero' },
      { path: ref, category: 'reference' },
    ],
    { date: '20260101', name: 'EP012_COLOR', handles: 12 },
  );
  assert.equal(r.folder, '20260101_EP012_COLOR_TransferFiles');
  assert.equal(r.fileCount, 2);
  assert.equal(r.categories.color.length, 1);
  assert.ok(r.categories.color[0].sha256);
  assert.equal(r.handles, 12);
});

// ── TC + sync (pure) ──────────────────────────────────────────────────
test('tcToFrames / framesToTc round-trip at 24fps', () => {
  assert.equal(tcToFrames('01:00:00:00', 24), 24 * 3600);
  assert.equal(tcToFrames('00:00:02:12', 24), 60);
  assert.equal(framesToTc(60, 24), '00:00:02:12');
});

test('sync pairs picture↔sound by TC and flags MOS + drift on long takes', () => {
  const r = syncByTC(
    [
      { id: 'P1', type: 'picture', tcStart: '01:00:00:00', durationFrames: 5000, fps: 24 },
      { id: 'S1', type: 'sound', tcStart: '01:00:00:05', durationFrames: 5010, fps: 24 }, // +5f offset, +10f drift
      { id: 'P2', type: 'picture', tcStart: '02:00:00:00', durationFrames: 100, fps: 24, hasAudio: false }, // MOS
    ],
    { driftToleranceFrames: 2, longTakeFrames: 3600 },
  );
  const pair = r.pairs.find((p) => p.picture === 'P1');
  assert.equal(pair.sound, 'S1');
  assert.equal(pair.offsetFrames, 5);
  assert.equal(pair.drift.flagged, true, 'long-take drift flagged');
  assert.ok(r.mos.some((m) => m.id === 'P2'));
});

// ── media_inventory (gated) ───────────────────────────────────────────
test('media_inventory probes cards and flags mixed fps', { skip: !FF }, async () => {
  const dir = tmp();
  const c24 = path.join(dir, 'A001C001.mp4');
  const c25 = path.join(dir, 'A001C003.mp4'); // note: C002 missing → card gap
  for (const [f, rate] of [
    [c24, 24],
    [c25, 25],
  ]) {
    const r = spawnSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', `testsrc=duration=1:size=160x120:rate=${rate}`, '-pix_fmt', 'yuv420p', '-y', f], {
      encoding: 'utf8',
    });
    assert.equal(r.status, 0, r.stderr);
  }
  const inv = mediaInventory([c24, c25]);
  assert.equal(inv.count, 2);
  assert.equal(inv.consistency.mixedFps, true);
  assert.ok(inv.consistency.cardGaps.some((g) => g.reel === 'A001' && g.missing.includes(2)));
});
