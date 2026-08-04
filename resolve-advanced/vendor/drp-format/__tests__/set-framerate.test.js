const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const JSZip = require('jszip');
const { setTimelineFrameRate, readTimelineFrameRates } = require('../set-framerate');

// A real Resolve export with one media clip — carries a timeline <FrameRate> blob
// and a clip-level <MediaFrameRate> that a relabel must NOT touch.
const TEMPLATE = path.join(__dirname, '..', 'templates', 'media-clip-h264.drp');

async function countTag(buf, tag) {
  const zip = await JSZip.loadAsync(buf);
  let n = 0;
  for (const name of Object.keys(zip.files)) {
    if (!name.endsWith('.xml')) continue;
    const xml = await zip.files[name].async('string');
    n += (xml.match(new RegExp(`<${tag}>[0-9a-fA-F]{32}</${tag}>`, 'g')) || []).length;
  }
  return n;
}

test('readTimelineFrameRates reports the template timeline rate', async () => {
  const rates = await readTimelineFrameRates(TEMPLATE);
  assert.ok(rates.length > 0, 'expected at least one timeline FrameRate blob');
  for (const r of rates) {
    assert.ok(Number.isFinite(r.fps) && r.fps > 0, `decoded fps should be positive, got ${r.fps}`);
  }
});

test('setTimelineFrameRate relabels every timeline FrameRate blob', async () => {
  const before = await readTimelineFrameRates(TEMPLATE);
  const target = Math.abs(before[0].fps - 25) < 1e-6 ? 24 : 25;

  const { buffer, changes, timelineFrameRates } = await setTimelineFrameRate(TEMPLATE, target);
  assert.ok(changes.length > 0, 'a real rate change must be recorded');
  assert.deepStrictEqual(timelineFrameRates, before.map(r => r.fps));

  const after = await readTimelineFrameRates(buffer);
  assert.strictEqual(after.length, before.length, 'blob count must not change');
  for (const r of after) assert.ok(Math.abs(r.fps - target) < 1e-6, `expected ${target}, got ${r.fps}`);
});

test('relabel leaves clip-level MediaFrameRate blobs untouched', async () => {
  const original = fs.readFileSync(TEMPLATE);
  const mediaBefore = await countTag(original, 'MediaFrameRate');
  const { buffer } = await setTimelineFrameRate(original, 30);
  const mediaAfter = await countTag(buffer, 'MediaFrameRate');
  assert.strictEqual(mediaAfter, mediaBefore, 'MediaFrameRate must be left alone');
});

test('relabel is idempotent: same target twice yields no recorded change the second time', async () => {
  const first = await setTimelineFrameRate(TEMPLATE, 25);
  const second = await setTimelineFrameRate(first.buffer, 25);
  assert.strictEqual(second.changes.length, 0, 'second pass at same fps records no change');
});

test('rejects invalid targets', async () => {
  await assert.rejects(() => setTimelineFrameRate(TEMPLATE, 0), /positive finite number/);
  await assert.rejects(() => setTimelineFrameRate(TEMPLATE, NaN), /positive finite number/);
  await assert.rejects(() => setTimelineFrameRate(TEMPLATE, 'fast'), /positive finite number/);
});
