/**
 * Cluster D — deliverable QC / compliance. Pure comparison cores unit-tested with synthetic
 * probe objects + fixtures; real-media actions (deliverable_qc, loudness_qc) gated on ffmpeg.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import {
  checkDeliverable,
  conformCompleteness,
  compareRenders,
  reframeBlankingCheck,
  parseEbur128,
  deliverableQc,
  loudnessQc,
} from '../server/deliverable-qc.mjs';
import { buildManifest, reconcileManifest } from '../server/render-manifest.mjs';
import { expandDeliverable } from '../server/deliverable-entities.mjs';
import { deliverableTool } from '../server/tools/deliverable.mjs';
import { hasFfmpeg, hasFfprobe } from '../server/capabilities.mjs';

const require = createRequire(import.meta.url);
const sharp = require('sharp');
const FF = hasFfmpeg() && hasFfprobe();

const PRORES = {
  video: {
    codec: 'prores',
    profile: '3',
    width: 1920,
    height: 1080,
    fps: 23.976,
    scan: 'progressive',
    colorPrimaries: 'bt709',
    colorTransfer: 'bt709',
    colorMatrix: 'bt709',
    frameCount: 240,
  },
  audio: [{ codec: 'pcm_s24le', channels: 2, channelLayout: 'stereo', sampleRate: 48000 }],
  format: { container: 'mov', duration: 10.0, size: 1000, nbStreams: 2 },
};

test('checkDeliverable passes a matching spec and fails a mismatch per field', () => {
  const spec = {
    video: { codec: 'prores', width: 1920, height: 1080, fps: 23.976, colorTransfer: 'bt709' },
    audio: { channels: 2, sampleRate: 48000 },
    container: 'mov',
  };
  const ok = checkDeliverable(PRORES, spec, { filename: 'EP012_master.mov' });
  assert.equal(ok.pass, true, JSON.stringify(ok.failed));

  const bad = checkDeliverable(PRORES, { video: { width: 3840, fps: 25 } });
  assert.equal(bad.pass, false);
  assert.deepEqual(bad.failed.sort(), ['video.fps', 'video.width']);
});

test('checkDeliverable honors a filename regex', () => {
  const spec = { filenameRegex: '^EP\\d{3}_(texted|textless)\\.mov$' };
  assert.equal(checkDeliverable(PRORES, spec, { filename: 'EP012_texted.mov' }).pass, true);
  assert.equal(checkDeliverable(PRORES, spec, { filename: 'final.mov' }).pass, false);
});

test('conform_completeness flags offline clips, short handles, and duration drift', () => {
  const tl = {
    clips: [
      { id: 'a', online: true, handleIn: 12, handleOut: 12 },
      { id: 'b', online: false, handleIn: 12, handleOut: 12 },
      { id: 'c', online: true, handleIn: 2, handleOut: 12 },
    ],
    timelineFrames: 1000,
  };
  const r = conformCompleteness(tl, { referenceFrames: 1001, minHandle: 8 });
  assert.equal(r.pass, false);
  const online = r.checks.find((c) => c.field === 'all_online');
  assert.deepEqual(online.offline, ['b']);
  const handles = r.checks.find((c) => c.field === 'handles');
  assert.deepEqual(handles.shortHandles, ['c']);
  const dur = r.checks.find((c) => c.field === 'duration_frame_exact');
  assert.equal(dur.pass, false);
});

test('conform_completeness passes a clean conform', () => {
  const tl = { clips: [{ id: 'a', online: true, handleIn: 12, handleOut: 12 }], timelineFrames: 500 };
  assert.equal(conformCompleteness(tl, { referenceFrames: 500, minHandle: 8 }).pass, true);
});

test('compareRenders reports frame delta + spec drift', () => {
  const oldP = PRORES;
  const newP = JSON.parse(JSON.stringify(PRORES));
  newP.video.frameCount = 246;
  newP.video.colorTransfer = 'bt2020-10';
  const d = compareRenders(oldP, newP);
  assert.equal(d.frameDelta, 6);
  assert.equal(d.sameLength, false);
  assert.ok(d.specDrift.some((x) => x.field === 'video.colorTransfer'));
});

test('expandDeliverable models texted/textless/stems entities with the right rules', () => {
  const r = expandDeliverable({
    name: 'EP012',
    spec: { video: { codec: 'prores', width: 1920 }, audio: { channels: 2 } },
    entities: ['texted', 'textless', 'stems_ME'],
  });
  assert.equal(r.entities.length, 3);
  const textless = r.entities.find((e) => e.kind === 'textless');
  assert.ok(textless.rules.includes('no_burned_in_text'));
  const stems = r.entities.find((e) => e.kind === 'stems_ME');
  assert.equal(stems.spec.video, undefined, 'stems are audio-only');
  assert.ok(stems.rules.includes('no_dialogue'));
});

async function barFrame(file, { w = 96, h = 96, barRows = 16 }) {
  const buf = Buffer.alloc(w * h * 3);
  for (let y = 0; y < h; y++) {
    const inBar = y < barRows || y >= h - barRows;
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 3;
      const v = inBar ? 0 : 130;
      buf[i] = v;
      buf[i + 1] = v;
      buf[i + 2] = v;
    }
  }
  await sharp(buf, { raw: { width: w, height: h, channels: 3 } })
    .png()
    .toFile(file);
}

test('reframe_blanking_check detects a letterbox and the active rect', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rf-'));
  const f = path.join(dir, 'lb.png');
  await barFrame(f, { h: 96, barRows: 16 }); // ~1/6 bars top+bottom
  const r = await reframeBlankingCheck(f);
  assert.equal(r.letterboxed, true);
  assert.equal(r.pillarboxed, false);
  assert.ok(r.bars.top > 0.1 && r.bars.bottom > 0.1, JSON.stringify(r.bars));
  assert.ok(r.activeRect.h < r.frameSize.h);
});

test('render_manifest build → reconcile detects a changed file', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rm-'));
  const a = path.join(dir, 'a.bin');
  const b = path.join(dir, 'b.bin');
  fs.writeFileSync(a, 'alpha-content');
  fs.writeFileSync(b, 'bravo-content');
  const manifest = buildManifest([{ path: a }, { path: b }], { probeFrames: false });
  assert.equal(manifest.count, 2);
  // Unchanged → all ok.
  const clean = reconcileManifest(manifest, { probeFrames: false });
  assert.equal(clean.pass, true);
  // Change b → reconcile flags it.
  fs.writeFileSync(b, 'bravo-content-EDITED');
  const dirty = reconcileManifest(manifest, { probeFrames: false });
  assert.equal(dirty.pass, false);
  assert.ok(dirty.results.find((x) => x.name === 'b.bin' && x.status === 'changed'));
});

test('render_manifest guards against an empty (0-byte) output', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rm-'));
  const z = path.join(dir, 'zero.bin');
  fs.writeFileSync(z, '');
  assert.throws(() => buildManifest([{ path: z }], { probeFrames: false }), /0 bytes/);
});

test('parseEbur128 extracts integrated LUFS + true peak from a summary block', () => {
  const stderr = `[Parsed_ebur128_0 @ 0x0] Summary:\n\n  Integrated loudness:\n    I:         -23.0 LUFS\n    Threshold: -33.2 LUFS\n\n  Loudness range:\n    LRA:         5.4 LU\n\n  True peak:\n    Peak:       -2.1 dBFS\n`;
  const m = parseEbur128(stderr);
  assert.equal(m.integratedLufs, -23.0);
  assert.equal(m.lra, 5.4);
  assert.equal(m.truePeakDbtp, -2.1);
});

// ── real media (gated) ────────────────────────────────────────────────
test('deliverable_qc probes a real render and checks its spec', { skip: !FF }, async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'dq-'));
  const f = path.join(dir, 'EP012_master.mp4');
  const r = spawnSync(
    'ffmpeg',
    [
      '-v',
      'error',
      '-f',
      'lavfi',
      '-i',
      'testsrc=duration=1:size=320x240:rate=25',
      '-f',
      'lavfi',
      '-i',
      'sine=frequency=440:duration=1',
      '-c:a',
      'aac',
      '-pix_fmt',
      'yuv420p',
      '-y',
      f,
    ],
    { encoding: 'utf8' },
  );
  assert.equal(r.status, 0, r.stderr);
  const res = deliverableQc(f, { video: { width: 320, height: 240, fps: 25 }, filenameRegex: '^EP\\d{3}_master\\.mp4$' });
  assert.equal(res.pass, true, JSON.stringify(res.failed));
  const bad = deliverableQc(f, { video: { width: 1920 } });
  assert.equal(bad.pass, false);
});

test('loudness_qc measures a real file vs a target', { skip: !FF }, async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lq-'));
  const f = path.join(dir, 'tone.wav');
  const r = spawnSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=1000:duration=3', '-y', f], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  const res = loudnessQc(f, { truePeakMax: 0.0 });
  assert.equal(typeof res.measured.integratedLufs, 'number');
  assert.ok('pass' in res);
});

test('deliverable tool dispatches expand_deliverable', async () => {
  const r = await deliverableTool.handler({
    action: 'expand_deliverable',
    args: { name: 'EP012', spec: { video: { codec: 'prores' } }, entities: ['texted', 'stems_ME'] },
  });
  assert.equal(r.entities.length, 2);
});
