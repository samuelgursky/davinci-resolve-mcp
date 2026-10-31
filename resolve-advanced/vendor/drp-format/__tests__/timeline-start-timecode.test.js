// SeqContainer timeline start: <StartFrame> and <StartTC> must describe the
// same frame, and a start timecode the rate cannot count is refused instead of
// being turned into a wrong frame number.
//
//  - An explicit startFrame wins (issue #168), but <StartTC> kept the caller's
//    (or the default 01:00:00:00) label, so the file named two different
//    starts. It is now the label of that frame.
//  - ';' (drop-frame) at a rate without drop-frame (24, 25, 23.976, 30) had
//    dropped numbers subtracted anyway: 01:00:00;00 at 24 -> 86292.
//  - A malformed label became frame 0 and was still written as <StartTC>.
//  - Fields past their range (ff >= the timebase, mm/ss > 59) and drop-frame
//    labels that do not exist (00:01:00;00) were counted as if they did.
const { test } = require('node:test');
const assert = require('node:assert');
const {
  buildSeqContainerFile,
  timecodeToFrames,
  framesToTimecode,
} = require('../seq-container-builder');

const NTSC30 = 30000 / 1001;
const NTSC60 = 60000 / 1001;
const NTSC24 = 24000 / 1001;
const tl = { name: 'T', videoTracks: [], audioTracks: [] };

function start(xml) {
  return {
    frame: Number(xml.match(/<StartFrame>([^<]*)<\/StartFrame>/)[1]),
    tc: xml.match(/<StartTC>([^<]*)<\/StartTC>/)[1],
  };
}

// Reference drop-frame labeller, written from SMPTE 12M independently of the
// module under test (whole 10-minute blocks, then the first undropped minute).
function refDropFrameLabel(frames, nominal) {
  const drop = nominal / 15;
  const perMin = nominal * 60 - drop;
  const per10 = perMin * 10 + drop;
  const blocks = Math.floor(frames / per10);
  let rem = frames % per10;
  let minutes = blocks * 10;
  if (rem >= nominal * 60) {
    rem -= nominal * 60;
    minutes += 1 + Math.floor(rem / perMin);
    rem = (rem % perMin) + drop;
  }
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  const s = Math.floor(rem / nominal);
  const f = rem % nominal;
  const p = (n) => String(n).padStart(2, '0');
  return `${p(h)}:${p(m)}:${p(s)};${p(f)}`;
}

test('NULL CONTROL: valid starts count exactly as before', async () => {
  assert.strictEqual(timecodeToFrames('01:00:00:00', NTSC30), 108000);
  assert.strictEqual(timecodeToFrames('01:00:00:00', NTSC24), 86400);
  assert.strictEqual(timecodeToFrames('10:00:00:00', 25), 900000);
  assert.strictEqual(timecodeToFrames('00:01:00;02', NTSC30), 1800);
  assert.strictEqual(timecodeToFrames('01:00:00;00', NTSC30), 107892);
  assert.strictEqual(timecodeToFrames('01:00:00;00', NTSC60), 215784);
  // No startFrame: the caller's label is written as given, frame from it.
  assert.deepStrictEqual(
    start(await buildSeqContainerFile(tl, { frameRate: NTSC30, startTimecode: '01:00:00;00' })),
    { frame: 107892, tc: '01:00:00;00' },
  );
  assert.deepStrictEqual(
    start(await buildSeqContainerFile(tl, { frameRate: NTSC24 })),
    { frame: 86400, tc: '01:00:00:00' },
  );
  // A startFrame that agrees with the label leaves both unchanged.
  assert.deepStrictEqual(
    start(await buildSeqContainerFile(tl, { frameRate: NTSC30, startTimecode: '01:00:00;00', startFrame: 107892 })),
    { frame: 107892, tc: '01:00:00;00' },
  );
});

test('an explicit startFrame is written with its own label in <StartTC>', async () => {
  // 90000 / 24 = 3750 s = 01:02:30:00.
  assert.deepStrictEqual(
    start(await buildSeqContainerFile(tl, { frameRate: 24, startFrame: 90000 })),
    { frame: 90000, tc: '01:02:30:00' },
  );
  // 99999 at the 30 timebase = 3333 s + 9 f = 00:55:33:09 (non-drop: ':' given).
  assert.deepStrictEqual(
    start(await buildSeqContainerFile(tl, { frameRate: NTSC30, startTimecode: '01:00:00:00', startFrame: 99999 })),
    { frame: 99999, tc: '00:55:33:09' },
  );
  // Drop-frame stays drop-frame: 125874 = 107892 + 17982 (ten DF minutes).
  assert.deepStrictEqual(
    start(await buildSeqContainerFile(tl, { frameRate: NTSC30, startTimecode: '01:00:00;00', startFrame: 125874 })),
    { frame: 125874, tc: '01:10:00;00' },
  );
});

test('drop-frame labels are refused at rates that have no drop-frame', async () => {
  for (const fps of [24, 25, NTSC24, 30, 50]) {
    assert.throws(() => timecodeToFrames('01:00:00;00', fps), RangeError, `fps ${fps}`);
    await assert.rejects(buildSeqContainerFile(tl, { frameRate: fps, startTimecode: '01:00:00;00' }), RangeError);
  }
});

test('malformed and out-of-range labels are refused, not counted as frame 0', async () => {
  for (const tc of ['garbage', '01:00:00', '', '01:00:00:00:00', '01:60:00:00', '01:00:60:00', '01:00:00:30', '1:2:3:4']) {
    assert.throws(() => timecodeToFrames(tc, NTSC30), RangeError, JSON.stringify(tc));
  }
  assert.throws(() => timecodeToFrames('01:00:00:24', 24), RangeError);
  assert.throws(() => timecodeToFrames(null, 24), RangeError);
  await assert.rejects(buildSeqContainerFile(tl, { frameRate: 24, startTimecode: 'garbage' }), RangeError);
});

test('drop-frame labels that do not exist are refused', () => {
  // Minute 1 has no ;00 or ;01 at 29.97 (no ;00-;03 at 59.94); minute 10 keeps them.
  assert.throws(() => timecodeToFrames('00:01:00;00', NTSC30), RangeError);
  assert.throws(() => timecodeToFrames('00:01:00;01', NTSC30), RangeError);
  assert.throws(() => timecodeToFrames('00:01:00;03', NTSC60), RangeError);
  assert.strictEqual(timecodeToFrames('00:10:00;00', NTSC30), 17982);
  assert.strictEqual(timecodeToFrames('00:01:00;04', NTSC60), 3600);
});

test('SECOND CHANNEL: labels match an independent SMPTE 12M labeller and round-trip', () => {
  // Hand values first.
  assert.strictEqual(framesToTimecode(1800, NTSC30, true), '00:01:00;02');
  assert.strictEqual(framesToTimecode(17982, NTSC30, true), '00:10:00;00');
  assert.strictEqual(framesToTimecode(107892, NTSC30, true), '01:00:00;00');
  assert.strictEqual(framesToTimecode(86400, NTSC24, false), '01:00:00:00');
  for (const [fps, nominal] of [[NTSC30, 30], [NTSC60, 60]]) {
    for (let f = 0; f < nominal * 3600 * 2; f += 7) {
      const label = framesToTimecode(f, fps, true);
      assert.strictEqual(label, refDropFrameLabel(f, nominal), `frame ${f} @ ${nominal}`);
      assert.strictEqual(timecodeToFrames(label, fps), f);
    }
  }
  for (const fps of [NTSC24, 24, 25, NTSC30]) {
    for (let f = 0; f < 200000; f += 13) {
      assert.strictEqual(timecodeToFrames(framesToTimecode(f, fps, false), fps), f);
    }
  }
});
