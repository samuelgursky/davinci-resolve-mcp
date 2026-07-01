'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const { emulateClip, fitFactor, MODE } = require('../oracle/emulate');

const TPF = 254016000000 / 24;
const CTX = { ticksPerFrame: TPF, seqW: 3600, seqH: 2160, mode: MODE.FIT };
// an un-retimed clip at scale S with proxy dims; ticks consistent with in
const clip = (S, pw, ph, inF = 100) => ({
  seqstart: 0, seqend: 96, xml_in: inF, pproTicksIn: inF * TPF, is_subclip: false,
  scale_premiere: S, srcW: pw, srcH: ph, source_basename: 'x.mov', speed: 100,
});
const HR_1568 = { ok: true, width: 4096, height: 2612, codec: 'prores', bitDepth: 12 };

test('emulate: same-aspect clip -> proxy-aspect zoom 1.06282, high confidence', () => {
  const t = emulateClip(clip(175.781, 2048, 1306), CTX, HR_1568);
  assert.equal(t.transform.zoomX, 1.06282); // 175.781*1306/2160
  assert.equal(t.transform.basis, 'proxy');
  assert.equal(t.flags.aspectMismatch, false);
  assert.equal(t.flags.scaleConfidence, 'high');
  assert.equal(t.sourceFrame, 100);
});

test('emulate: proxy/highres ASPECT MISMATCH keeps the proxy zoom but flags for reference review (LoCon)', () => {
  const t = emulateClip(clip(253.343, 1421, 1080), CTX, HR_1568);
  assert.equal(t.flags.aspectMismatch, true);
  assert.equal(t.flags.scaleConfidence, 'review');
  // the proxy is what the editor framed + what the reference renders: 253.343*1080/2160
  assert.ok(Math.abs(t.transform.zoomX - 1.26671) < 0.001, `got ${t.transform.zoomX}`);
});

test('emulate: zoom is the proxy-aspect correction with or without highres analysis', () => {
  const withHr = emulateClip(clip(180, 2048, 1306), CTX, HR_1568).transform.zoomX;
  const noHr = emulateClip(clip(180, 2048, 1306), CTX, null).transform.zoomX;
  assert.equal(withHr, 1.08833); // 180*1306/2160
  assert.equal(noHr, 1.08833);
});

test('emulate: without highres analysis, basis is proxy and confidence stays high', () => {
  const t = emulateClip(clip(175.781, 2048, 1306), CTX, null);
  assert.equal(t.transform.basis, 'proxy');
  assert.equal(t.flags.scaleConfidence, 'high');
  assert.equal(t.transform.zoomX, 1.06282);
});

test('fitFactor: fit vs fill pick the binding dimension', () => {
  // narrower-than-timeline source: fit binds on height, fill binds on width
  assert.ok(fitFactor(4096, 2612, 3600, 2160, MODE.FIT) < fitFactor(4096, 2612, 3600, 2160, MODE.FILL));
});
