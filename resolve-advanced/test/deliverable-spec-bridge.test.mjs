/**
 * deliverable-spec-bridge — authored vocabulary → ffprobe-shaped QC spec.
 * Hermetic: the bridge is pure (no ffprobe, no fs, no Resolve).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  codecToFfprobe,
  deliverableSpecFromAuthored,
  deliverableSpecsFromAuthored,
  inferContainer,
  namingToRegex,
  parseColor,
  parseFps,
  parseLoudness,
  parseRaster,
} from '../server/deliverable-spec-bridge.mjs';
import { checkDeliverable } from '../server/deliverable-qc.mjs';
import { toApplyContract } from '../server/runner-apply-contract.mjs';
import { deliverableTool } from '../server/tools/deliverable.mjs';

// The canonical authored shape, mirroring the committed type-default YAML.
const PRORES_MASTER = {
  id: 'prores_master',
  video: { codec: 'ProRes 422 HQ', res: '1920x1080', fps: 23.976, color: 'Rec.709 Gamma 2.4' },
  audio: { config: 'stereo', loudness: '-16 LUFS' },
  naming: '<SHOW>_<EP>_MASTER_<YYYYMMDD>.mov',
};

const YOUTUBE_MAIN = {
  id: 'youtube_main',
  video: { codec: 'H.264', res: '1920x1080', color: 'Rec.709 Gamma 2.4' },
  audio: { config: 'stereo', loudness: '-14 LUFS' },
  naming: '<SHOW>_<EP>_YT_<YYYYMMDD>.mp4',
};

test('codecToFfprobe maps display names to ffprobe codec_names', () => {
  assert.equal(codecToFfprobe('ProRes 422 HQ'), 'prores');
  assert.equal(codecToFfprobe('Apple ProRes 4444 XQ'), 'prores');
  assert.equal(codecToFfprobe('DNxHR HQX'), 'dnxhd');
  assert.equal(codecToFfprobe('H.264'), 'h264');
  assert.equal(codecToFfprobe('H.265'), 'hevc');
  assert.equal(codecToFfprobe('HEVC'), 'hevc');
  assert.equal(codecToFfprobe('JPEG 2000'), 'jpeg2000');
});

test('codecToFfprobe returns null for an unknown codec rather than guessing', () => {
  assert.equal(codecToFfprobe('Cinepak'), null);
  assert.equal(codecToFfprobe(''), null);
  assert.equal(codecToFfprobe(undefined), null);
});

test('parseRaster handles explicit WxH and named rasters', () => {
  assert.deepEqual(parseRaster('1920x1080'), { width: 1920, height: 1080 });
  assert.deepEqual(parseRaster('3840 X 2160'), { width: 3840, height: 2160 });
  assert.deepEqual(parseRaster('UHD'), { width: 3840, height: 2160 });
  assert.deepEqual(parseRaster({ width: 1080, height: 1920 }), { width: 1080, height: 1920 });
  assert.equal(parseRaster('enormous'), null);
});

test('parseFps handles decimals and ratios', () => {
  assert.equal(parseFps(23.976), 23.976);
  assert.equal(parseFps('23.976'), 23.976);
  assert.ok(Math.abs(parseFps('24000/1001') - 23.976) < 0.001);
  assert.equal(parseFps('soon'), null);
});

test('parseLoudness strips the unit', () => {
  assert.equal(parseLoudness('-16 LUFS'), -16);
  assert.equal(parseLoudness('-14LUFS'), -14);
  assert.equal(parseLoudness(-23), -23);
  assert.equal(parseLoudness('quiet'), null);
});

test('parseColor maps primaries/matrix but refuses to invent a transfer for display gamma', () => {
  const r = parseColor('Rec.709 Gamma 2.4');
  assert.equal(r.tags.colorPrimaries, 'bt709');
  assert.equal(r.tags.colorMatrix, 'bt709');
  assert.equal(r.tags.colorTransfer, undefined, 'display gamma is not an ffprobe transfer value');
  assert.ok(r.unmapped.some((u) => /transfer left unasserted/.test(u)), JSON.stringify(r.unmapped));
});

test('parseColor maps HDR transfers that DO have ffprobe values', () => {
  assert.equal(parseColor('Rec.2020 PQ').tags.colorTransfer, 'smpte2084');
  assert.equal(parseColor('Rec.2020 HLG').tags.colorTransfer, 'arib-std-b67');
});

test('namingToRegex anchors, escapes literals, and shapes date tokens', () => {
  const re = namingToRegex('<SHOW>_<EP>_MASTER_<YYYYMMDD>.mov');
  assert.ok(re.startsWith('^') && re.endsWith('$'));
  assert.ok(new RegExp(re).test('ACME_EP012_MASTER_20260727.mov'));
  assert.ok(!new RegExp(re).test('ACME_EP012_MASTER_2026.mov'), 'date token must be 8 digits');
  assert.ok(!new RegExp(re).test('ACME_EP012_MASTER_20260727Xmov'), 'the dot must be literal');
});

test('inferContainer collapses mp4 to mov, matching ffprobe first-token behavior', () => {
  // ffprobe reports format_name=mov,mp4,m4a,... for BOTH; ffprobe-media takes the first token.
  assert.equal(inferContainer(null, 'X_YT.mp4'), 'mov');
  assert.equal(inferContainer(null, 'X_MASTER.mov'), 'mov');
  assert.equal(inferContainer(null, 'X.mxf'), 'mxf');
  assert.equal(inferContainer('wav', null), 'wav');
  assert.equal(inferContainer(null, 'no-extension'), null);
});

test('deliverableSpecFromAuthored projects the canonical ProRes master', () => {
  const r = deliverableSpecFromAuthored(PRORES_MASTER);
  assert.equal(r.id, 'prores_master');
  assert.equal(r.spec.video.codec, 'prores');
  assert.equal(r.spec.video.width, 1920);
  assert.equal(r.spec.video.height, 1080);
  assert.equal(r.spec.video.fps, 23.976);
  assert.equal(r.spec.video.colorPrimaries, 'bt709');
  assert.equal(r.spec.audio.channels, 2);
  assert.equal(r.spec.container, 'mov');
  assert.ok(new RegExp(r.spec.filenameRegex).test('ACME_EP012_MASTER_20260727.mov'));
});

test('loudness is projected as a separate target, never into the QC spec', () => {
  const r = deliverableSpecFromAuthored(PRORES_MASTER);
  assert.equal(r.loudnessTarget.integrated, -16);
  assert.equal(r.spec.audio.loudness, undefined, 'loudness is not a deliverable_qc field');
  assert.ok(/loudness_qc/.test(r.note));
});

test('unmapped values are reported, never silently dropped', () => {
  const r = deliverableSpecFromAuthored({
    video: { codec: 'Cinepak', res: 'gigantic', fps: 'soon' },
    audio: { config: 'ambisonic', loudness: 'quiet' },
  });
  assert.equal(r.spec.video, undefined, 'nothing mappable means no video block at all');
  assert.equal(r.loudnessTarget, null);
  const joined = r.unmapped.join('|');
  for (const needle of ['Cinepak', 'gigantic', 'soon', 'ambisonic', 'quiet']) {
    assert.ok(joined.includes(needle), `${needle} missing from unmapped: ${joined}`);
  }
});

test('the projected spec is actually consumable by checkDeliverable', () => {
  const { spec } = deliverableSpecFromAuthored(YOUTUBE_MAIN);
  const probe = {
    video: { codec: 'h264', width: 1920, height: 1080, colorPrimaries: 'bt709', colorMatrix: 'bt709' },
    audio: [{ channels: 2 }],
    format: { container: 'mov', duration: 60 },
  };
  const r = checkDeliverable(probe, spec, { filename: 'ACME_EP012_YT_20260727.mp4' });
  assert.equal(r.pass, true, `unexpected failures: ${JSON.stringify(r.failed)}`);
  assert.ok(r.fieldCount > 0);
});

test('checkDeliverable catches a wrong-codec render through the projected spec', () => {
  const { spec } = deliverableSpecFromAuthored(YOUTUBE_MAIN);
  const probe = {
    video: { codec: 'prores', width: 1920, height: 1080, colorPrimaries: 'bt709', colorMatrix: 'bt709' },
    audio: [{ channels: 2 }],
    format: { container: 'mov', duration: 60 },
  };
  const r = checkDeliverable(probe, spec, { filename: 'ACME_EP012_YT_20260727.mp4' });
  assert.equal(r.pass, false);
  assert.ok(r.failed.includes('video.codec'), JSON.stringify(r.failed));
});

test('container alone cannot discriminate mp4 from mov — codec must', () => {
  const yt = deliverableSpecFromAuthored(YOUTUBE_MAIN).spec;
  const master = deliverableSpecFromAuthored(PRORES_MASTER).spec;
  assert.equal(yt.container, master.container, 'ffprobe reports "mov" for both');
  assert.notEqual(yt.video.codec, master.video.codec);
});

test('deliverableSpecsFromAuthored reports a non-object entry instead of dropping it', () => {
  const r = deliverableSpecsFromAuthored([PRORES_MASTER, 'nope']);
  assert.equal(r.length, 2);
  assert.ok(r[1].unmapped[0].includes('not an object'));
});

test('the deliver apply-contract carries the QC spec for each deliverable', () => {
  const contract = toApplyContract({
    stage: 'deliver',
    config: { deliverables: [PRORES_MASTER, YOUTUBE_MAIN] },
  });
  const args = contract.actions[0].args;
  assert.equal(contract.actions[0].action, 'render.add_job');
  assert.equal(args.qc.length, 2);
  assert.equal(args.qc[0].id, 'prores_master');
  assert.equal(args.qc[0].spec.video.codec, 'prores');
  assert.equal(args.qc[0].loudnessTarget.integrated, -16);
  assert.equal(args.qc[1].spec.video.codec, 'h264');
  assert.ok(/deliverable_qc/.test(args.note));
});

test('the deliver contract surfaces unmapped fields rather than emitting a silent gap', () => {
  const contract = toApplyContract({
    stage: 'deliver',
    config: { deliverables: [{ id: 'weird', video: { codec: 'Cinepak' } }] },
  });
  assert.ok(contract.actions[0].args.unmapped.some((u) => u.startsWith('weird: ')));
});

test('the deliver contract still tolerates a null/absent config', () => {
  const contract = toApplyContract({ stage: 'deliver', config: null });
  assert.equal(contract.actions[0].action, 'render.add_job');
  assert.deepEqual(contract.actions[0].args.qc, []);
});

test('deliverable tool dispatches spec_from_authored for one and for many', async () => {
  const one = await deliverableTool.handler({
    action: 'spec_from_authored',
    args: { deliverable: PRORES_MASTER },
  });
  assert.equal(one.spec.video.codec, 'prores');

  const many = await deliverableTool.handler({
    action: 'spec_from_authored',
    args: { deliverables: [PRORES_MASTER, YOUTUBE_MAIN] },
  });
  assert.equal(many.deliverables.length, 2);
});

test('spec_from_authored rejects passing both or neither input', async () => {
  await assert.rejects(() =>
    deliverableTool.handler({ action: 'spec_from_authored', args: { deliverable: PRORES_MASTER, deliverables: [] } }),
  );
  await assert.rejects(() => deliverableTool.handler({ action: 'spec_from_authored', args: {} }));
});
