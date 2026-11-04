/** Power windows in the Resolve 21 form (`resolveVersion: 21`).
 *
 * Resolve 21 stores a circle/linear window transform as corrector type 0x10004 (65540) with the
 * full parameter set. The corrector type 4 form the generator was calibrated on (Resolve 19)
 * loads into the Window palette on Resolve 21 but renders an empty mask, and the node's grade
 * disappears from the frame. The expected layout below is the one Resolve 21.0.4 exports, as
 * measured and pixel-verified by justhung69 (https://github.com/justhung69/resolve-mcp,
 * server/drx_r21.py and COVERAGE.md, MIT). These tests check the generated file against that
 * layout; no Resolve 21 was available to apply it.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { drxTool } from '../server/tools/drx.mjs';
import { decompressBody } from '../server/grade-body-patch.mjs';

const call = (action, args) => drxTool.handler({ action, args });
const near = (a, b, msg, eps = 1e-3) => assert.ok(Math.abs(a - b) <= eps, `${msg}: got ${a}, want ${b}`);

const ROTATE = 0x08500001;
const ASPECT = 0x08500004;
const SOFT_REF = 0x08500005;
const SIZE = 0x08500006;
const PAN = 0x0850000b;
const TILT = 0x0850000c;
const OPACITY = 0x08500012;
const WINDOW_TYPE = 0x88500008;
const REF_WIDTH = 0x8850000d;
const UNK_0E = 0x8850000e;
const UNK_0F = 0x8850000f;
const TRANSFORM_MATRIX = 0x88500010;

const WINDOW = { type: 1, pan: 35, tilt: 88, size: 75, aspect: 30, rotate: 49, soft1: 10, opacity: 66 };

async function generate(window, extra = {}, base = {}) {
  const g = await call('generate', { gradeParams: { space: 'drx', ...base, window }, ...extra });
  const parsed = await call('parse', { content: g.content });
  return { content: g.content, node: parsed.nodes[0] };
}
const windowBlocks = (node, type) => node.correctors.filter((c) => c.type === type);

test('default output is unchanged: corrector type 4 with only the non-neutral parameters', async () => {
  const { node } = await generate(WINDOW);
  assert.equal(windowBlocks(node, 0x10004).length, 0);
  const [block] = windowBlocks(node, 4);
  const ids = block.parameters.map((p) => p.id >>> 0);
  assert.ok(!ids.includes(REF_WIDTH) && !ids.includes(TRANSFORM_MATRIX), 'no Resolve 21 extras');
  assert.deepEqual(new Set(ids), new Set([WINDOW_TYPE, ROTATE, SIZE, ASPECT, PAN, TILT, OPACITY, SOFT_REF]));
});

for (const resolveVersion of [21, '21.0.4']) {
  test(`resolveVersion ${JSON.stringify(resolveVersion)} writes the window as corrector type 65540 in Resolve 21 order`, async () => {
    const { node } = await generate(WINDOW, { resolveVersion });
    assert.equal(windowBlocks(node, 4).length, 0, 'no corrector type 4 window');
    const [block] = windowBlocks(node, 0x10004);
    assert.ok(block, 'corrector type 65540 present');
    assert.deepEqual(
      block.parameters.map((p) => p.id >>> 0),
      [ROTATE, ASPECT, SOFT_REF, SIZE, PAN, TILT, WINDOW_TYPE, REF_WIDTH, UNK_0E, UNK_0F, TRANSFORM_MATRIX, OPACITY],
    );
    const by = Object.fromEntries(block.parameters.map((p) => [p.id >>> 0, p.value]));
    near(by[ROTATE], -49 / 180, 'rotate');
    near(by[ASPECT], (50 - 30) / 50, 'aspect');
    near(by[SOFT_REF], 160, 'softRef');
    near(by[SIZE], 1 + (75 - 50) * 0.08, 'size');
    near(by[PAN], ((35 - 50) / 50) * 4096, 'pan', 0.01);
    near(by[TILT], ((88 - 50) / 50) * 4096, 'tilt', 0.01);
    near(by[OPACITY], 0.66, 'opacity');
    assert.equal(by[WINDOW_TYPE].F2, 2, 'window type is the varint {F2:2}');
    assert.equal(by[REF_WIDTH], 288);
    assert.equal(by[UNK_0E], 0);
    assert.equal(by[UNK_0F], 0);
    const m = by[TRANSFORM_MATRIX].F10;
    assert.deepEqual([m.F1, m.F2, m.F3, m.F4, m.F5, m.F6, m.F7, m.F8, m.F9], [1, 0, 0, 0, 1, 0, 0, 0, 1], 'identity 3x3 matrix');
  });
}

test('neutral parameters are filled in with the values Resolve 21 exports', async () => {
  const { node } = await generate({ type: 1, size: 60 }, { resolveVersion: 21 });
  const [block] = windowBlocks(node, 0x10004);
  const by = Object.fromEntries(block.parameters.map((p) => [p.id >>> 0, p.value]));
  assert.deepEqual([by[ROTATE], by[ASPECT], by[SOFT_REF], by[PAN], by[TILT]], [0, 0, 0, 0, 0]);
  near(by[SIZE], 1.8, 'size 60 -> 1.8');
  assert.equal(by[OPACITY], undefined, 'opacity is only written when it is not 100');
});

test('a linear window keeps its softness mask in corrector type 3', async () => {
  const { node } = await generate({ type: 2, size: 60, soft1: 4, soft2: 5 }, { resolveVersion: 21 });
  assert.equal(windowBlocks(node, 0x10004).length, 1);
  assert.equal(windowBlocks(node, 3).length, 1);
  assert.equal(windowBlocks(node, 4).length, 0);
});

test('resolveVersion below 21 keeps the Resolve 19 form', async () => {
  for (const resolveVersion of [19, 20, '20.3.2']) {
    const { node } = await generate(WINDOW, { resolveVersion });
    assert.equal(windowBlocks(node, 0x10004).length, 0, `resolveVersion ${resolveVersion}`);
    assert.equal(windowBlocks(node, 4).length, 1, `resolveVersion ${resolveVersion}`);
  }
});

test('gradient and polygon windows are not rewritten', async () => {
  const gradient = await generate({ type: 5, pan: 60, soft1: 2 }, { resolveVersion: 21 });
  assert.equal(windowBlocks(gradient.node, 0x10004).length, 0);
  assert.equal(windowBlocks(gradient.node, 65554).length, 1);
  const vertices = [
    { x: -200, y: -100 },
    { x: 200, y: -100 },
    { x: 0, y: 200 },
  ];
  const polygon = await generate({ type: 3, vertices }, { resolveVersion: 21 });
  assert.equal(windowBlocks(polygon.node, 0x10004).length, 0);
  assert.equal(windowBlocks(polygon.node, 6).length, 1);
});

test('the node lists the Resolve 21 window type in its corrector-type list, varint encoded', async () => {
  const base = { gain: { r: 1.1, g: 1, b: 1, master: 1 } };
  const bodyOf = (content) => decompressBody(content.match(/<Body>([0-9a-f]+)<\/Body>/)[1]);
  const list = (content) => bodyOf(content).indexOf(Buffer.from([0x12, 0x05, 3, 4, 5, 6, 18]));
  const r19 = await generate(WINDOW, {}, base);
  assert.ok(list(r19.content) >= 0, 'the Resolve 19 list is 3, 4, 5, 6, 18');
  const r21 = await generate(WINDOW, { resolveVersion: 21 }, base);
  // 65540 = 0x10004 is the varint 0x84 0x80 0x04, so the list grows from 5 to 8 bytes.
  const at = bodyOf(r21.content).indexOf(Buffer.from([0x12, 0x08, 3, 4, 5, 6, 18, 0x84, 0x80, 0x04]));
  assert.ok(at >= 0, 'the Resolve 21 list ends with 65540');
});
