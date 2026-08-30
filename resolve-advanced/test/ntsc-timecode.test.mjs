// The conform fixtures were integer-rate only, so the suite could not see
// NTSC timecode bugs — which is how parseEDL ran exact-rate math (0.1% short,
// 108 frames/hour) against a nominal-rate writer for years (fixed v2.104.6,
// convention measured against Resolve's own GetStartFrame). These fixtures
// close that gap: broadcast-start 29.97 NDF, drop-frame, and the write→parse
// round trip.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseEDL, tcToFrames } from '../server/editorial.mjs';
import { eventsToEDL } from '../server/author-interchange.mjs';
import { tcToFrames as invTcToFrames, framesToTc } from '../server/media-inventory.mjs';

const FPS = 30000 / 1001;

test('29.97 NDF counts nominal frames (measured: Resolve GetStartFrame)', () => {
  assert.equal(tcToFrames('01:00:00:00', FPS), 108000);
  assert.equal(tcToFrames('00:01:00:00', FPS), 1800);
  assert.equal(invTcToFrames('01:00:00:00', FPS), 108000);
});

test('29.97 drop-frame subtracts dropped numbers (01:00:00;00 -> 107892)', () => {
  // 2 numbers dropped per minute except every tenth: 2 x 54 = 108 per hour.
  assert.equal(tcToFrames('01:00:00;00', FPS), 107892);
  assert.equal(tcToFrames('00:10:00;00', FPS), 17982);
  assert.equal(invTcToFrames('01:00:00;00', FPS), 107892);
});

test('a broadcast-start 29.97 EDL parses to nominal frames', () => {
  const edl = [
    'TITLE: NTSC_FIXTURE',
    'FCM: NON-DROP FRAME',
    '001  TAPE1 V     C        00:00:10:00 00:01:10:00 01:00:00:00 01:01:00:00',
    '002  TAPE2 V     C        02:00:00:00 02:00:04:15 01:01:00:00 01:01:04:15',
    '',
  ].join('\n');
  const events = parseEDL(edl, { fps: FPS });
  assert.equal(events.length, 2);
  assert.equal(events[0].recIn, 108000);
  assert.equal(events[0].recOut, 109800);
  assert.equal(events[0].recOut - events[0].recIn, 1800, 'an NDF minute is 1800 frames');
  assert.equal(events[0].srcOut - events[0].srcIn, 1800, 'source side counts the same base');
  assert.equal(events[1].recIn, events[0].recOut, 'butt cut stays gapless at NTSC');
  assert.equal(events[1].recOut - events[1].recIn, 4 * 30 + 15);
});

test('EDL write -> parse round trip is frame-identical at 29.97', () => {
  const events = [
    { index: 1, track: 'V', source: 'TAPE1', srcIn: 300, srcOut: 2100, recIn: 108000, recOut: 109800, fps: FPS },
    { index: 2, track: 'V', source: 'TAPE2', srcIn: 215784, srcOut: 215919, recIn: 109800, recOut: 109935, fps: FPS },
  ];
  const text = eventsToEDL(events, { fps: FPS });
  const back = parseEDL(text, { fps: FPS });
  assert.equal(back.length, 2);
  for (let i = 0; i < 2; i++) {
    for (const k of ['srcIn', 'srcOut', 'recIn', 'recOut']) {
      assert.equal(back[i][k], events[i][k], `${k} of event ${i}`);
    }
  }
});

test('media-inventory tc<->frames round trip is the identity at NTSC rates', () => {
  for (const fps of [30000 / 1001, 24000 / 1001, 60000 / 1001]) {
    for (const tc of ['00:00:00:01', '00:59:59:12', '01:00:00:00', '02:03:04:05']) {
      const frames = invTcToFrames(tc, fps);
      assert.equal(framesToTc(frames, fps), tc, `${tc} @ ${fps}`);
    }
  }
});
