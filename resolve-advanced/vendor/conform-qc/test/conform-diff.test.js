'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { diffConform } = require('../ops/conform-diff');

function truthClip(seqstart, zoom, sourceFrame, dur, { retimed = false, conf = 'high', mismatch = false } = {}) {
  return {
    seqstart, seqend: seqstart + dur,
    timing: { duration: dur }, sourceFrame,
    source: { basename: 'x.mov' },
    retime: { retimed },
    transform: { zoomX: zoom, zoomY: zoom },
    flags: { scaleConfidence: conf, aspectMismatch: mismatch },
  };
}

const TRUTH = {
  clips: [
    truthClip(0, 1.06282, 100, 96),
    truthClip(96, 1.11856, 200, 48),
    truthClip(200, 1.06283, 300, 60, { conf: 'low', mismatch: true }), // LoCon
    truthClip(300, 1.0, 400, 24), // generator-ish, dropped on import
  ],
  transitions: [{}, {}],
};

test('diffConform: clean clips pass; LoCon scaling mismatch + dropped clip surface', () => {
  const db = {
    startOffset: 86400,
    clips: [
      { start: 86400, duration: 96, mediaStart: 100, name: 'x.mov', zoomX: 1.06282, retimePresent: false },
      { start: 86496, duration: 48, mediaStart: 200, name: 'x.mov', zoomX: 1.11856, retimePresent: false },
      { start: 86600, duration: 60, mediaStart: 300, name: 'x.mov', zoomX: 1.26671, retimePresent: false }, // wrong scale in DB
      // seq300 clip absent (dropped on import)
    ],
    transitions: [{}, {}],
  };
  const r = diffConform(TRUTH, db);
  assert.equal(r.offset, 86400);
  assert.equal(r.summary.matched, 3);
  assert.equal(r.summary.clean, 2);
  assert.equal(r.summary.withIssues, 1);
  assert.equal(r.summary.missing, 1); // the seq300 clip
  assert.equal(r.summary.byAttr.scaling, 1);
  const loconIssue = r.issues[0].issues.find((i) => i.attr === 'scaling');
  assert.equal(loconIssue.confidence, 'low');
  assert.equal(loconIssue.aspectMismatch, true);
  assert.equal(loconIssue.db, 1.26671);
  assert.equal(r.summary.transitions.match, true);
});

test('diffConform: catches dropped retime + extra DB clip + transition count mismatch', () => {
  const db = {
    startOffset: 0,
    clips: [
      { start: 0, duration: 96, mediaStart: 100, name: 'x.mov', zoomX: 1.06282, retimePresent: false },
      { start: 96, duration: 48, mediaStart: 200, name: 'x.mov', zoomX: 1.11856, retimePresent: false },
      { start: 200, duration: 60, mediaStart: 300, name: 'x.mov', zoomX: 1.06283, retimePresent: false },
      { start: 999, duration: 10, mediaStart: 5, name: 'extra.mov', zoomX: 1, retimePresent: false }, // extra
    ],
    transitions: [{}], // only 1 vs truth 2
  };
  const t2 = { ...TRUTH, clips: [truthClip(0, 1.06282, 100, 96), truthClip(96, 1.11856, 200, 48, { retimed: true }), truthClip(200, 1.06283, 300, 60, { conf: 'low', mismatch: true })] };
  const r = diffConform(t2, db);
  assert.equal(r.summary.byAttr.retime, 1); // clip2 truth retimed but DB has none
  assert.equal(r.summary.extra, 1);
  assert.equal(r.summary.transitions.match, false);
});
