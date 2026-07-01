'use strict';

/**
 * Reversed-clip source-frame derivation — fixture-free (synthetic inputs only),
 * so it runs on any machine without the golden answer key.
 *
 * The rule under test: a reversed clip anchors its range at the END of its
 * available source media and mirrors in/out about that end, rather than growing
 * downward from the start. This is fully derivable from the XML (in/out,
 * endoffset) plus the source media's frame count — no reference render needed.
 *
 *   forward subclip:  source_start = startoffset + in
 *   reversed subclip: source_start = (masterFrames - 1 - endoffset) - in
 *
 * The forward path used to be applied to reversed clips too, landing the frame at
 * the wrong (mirrored) position. Values below are validated against a live
 * Resolve readback (get_source_start/end_frame).
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const resolve = require('../oracle/resolve');

const TPF = 254016000000 / 24; // ticks/frame @24

test('reversed subclip end-anchors its range', () => {
  const ctx = { ticksPerFrame: TPF, masterFrames: 47849 };
  const rev = {
    xml_in: 589,
    xml_out: 604,
    pproTicksIn: 589 * TPF,
    is_subclip: true,
    subclip_startoffset: 34727,
    subclip_endoffset: 11832,
    reverse: true,
  };
  // source_start = (masterFrames - 1 - endoffset) - in = 47849 - 1 - 11832 - 589
  // = 35427 (Resolve's get_source_start_frame), NOT the forward start-anchor
  // 34727 + 589 = 35316, nor the out-anchored/off-by-one 35413.
  assert.equal(resolve.deriveSourceFrame(rev, ctx), 35427);
  assert.equal(resolve.deriveSampleFrame(rev, ctx), 35427);
});

test('forward subclip with identical offsets still start-anchors', () => {
  const ctx = { ticksPerFrame: TPF, masterFrames: 47849 };
  const fwd = {
    xml_in: 589,
    xml_out: 604,
    pproTicksIn: 589 * TPF,
    is_subclip: true,
    subclip_startoffset: 34727,
    subclip_endoffset: 11832,
    reverse: false,
  };
  assert.equal(resolve.deriveSourceFrame(fwd, ctx), 34727 + 589); // 35316
});

test('full-master reverse (no subclip): (masterFrames - 1) - in', () => {
  const fullRev = {
    xml_in: 100,
    xml_out: 250,
    pproTicksIn: 100 * TPF,
    is_subclip: false,
    reverse: true,
    master_frames: 1000, // per-source override (clip-level) when ctx has none
  };
  // (1000 - 1 - 0) - 100 = 899
  assert.equal(resolve.deriveSourceFrame(fullRev, { ticksPerFrame: TPF }), 899);
});

test('reverse without any frame count fails loudly (no silent start-anchor)', () => {
  const rev = {
    xml_in: 589,
    xml_out: 604,
    pproTicksIn: 589 * TPF,
    is_subclip: true,
    subclip_startoffset: 34727,
    subclip_endoffset: 11832,
    reverse: true,
  };
  assert.throws(
    () => resolve.deriveSourceFrame(rev, { ticksPerFrame: TPF }),
    /needs a source frame count/,
  );
});
