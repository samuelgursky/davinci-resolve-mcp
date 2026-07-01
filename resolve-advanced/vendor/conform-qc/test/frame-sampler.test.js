'use strict';

/** FrameSampler interface tests — client-free. */

const test = require('node:test');
const assert = require('node:assert/strict');

const { FrameSampler, FakeFrameSampler, isFrameSampler } = require('../adapters/frame-sampler');

test('FrameSampler: base interface throws until implemented', async () => {
  const base = new FrameSampler();
  assert.equal(isFrameSampler(base), true);
  await assert.rejects(() => base.sample('media', 0, { width: 4, height: 4 }), /must be implemented/);
});

test('FrameSampler: fake conforms — right dims, deterministic, content varies by frame', async () => {
  const s = new FakeFrameSampler();
  assert.equal(isFrameSampler(s), true);
  const size = { width: 8, height: 6 };
  const a = await s.sample('clipA.mov', 100, size);
  assert.equal(a.width, 8);
  assert.equal(a.height, 6);
  assert.equal(a.data.length, 48);
  const aAgain = await s.sample('clipA.mov', 100, size);
  assert.deepEqual(Array.from(a.data), Array.from(aAgain.data), 'same request => same pixels');
  const b = await s.sample('clipA.mov', 101, size);
  assert.notDeepEqual(Array.from(a.data), Array.from(b.data), 'different frame => different pixels');
  // A non-conforming object is rejected by the duck-typed check.
  assert.equal(isFrameSampler({}), false);
});
