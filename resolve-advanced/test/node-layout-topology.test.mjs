/** Topology-aware "Cleanup Node Graph" (2026-09-14): positions from the graph's wiring.
 *
 * Bodies are authored with the drx tool (real corrector content), then their F8
 * connection messages are REWRITTEN here to build shapes the generator cannot
 * (fan-out, merge, key links, cycles) — the layout planner only reads ids and
 * ports, so this exercises exactly what it consumes. The x row (290 + 495·rank at
 * y 428) is the measured native cleanup; the lane pitch (178) is Resolve's own
 * vertical placement grid and is NOT yet measured against native cleanup on a
 * mixer graph — pin it here when it is. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { drxTool } from '../server/tools/drx.mjs';

const require = createRequire(import.meta.url);
const layout = require('../vendor/drx-codec/node-layout.js');
const drx = (action, args) => drxTool.handler({ action, args });
const bodyHex = (xml) => xml.match(/<Body>([0-9a-fA-F]+)<\/Body>/)[1];

async function chainBody(n) {
  const base = (await drx('generate', { gradeParams: { saturation: 60, label: 'N1' } })).content;
  const xml = n === 1 ? base : (await drx('merge', { baseContent: base, newNodes: Array.from({ length: n - 1 }, (_, i) => ({ label: `N${i + 2}`, params: { contrast: 1.1 + i / 10 } })) })).content;
  return Buffer.from(bodyHex(xml), 'hex');
}

// --- minimal protobuf writer for rewriting the F8 edges of a body ---
const { encodeVarint, unwrapBody, wrapBody } = layout;
const tag = (f, wt) => encodeVarint((f << 3) | wt);
const vint = (f, v) => Buffer.concat([tag(f, 0), encodeVarint(v)]);
const msg = (f, inner) => Buffer.concat([tag(f, 2), encodeVarint(inner.length), inner]);
function rv(b, p) { let v = 0n, s = 0n, i = p; for (;;) { const x = b[i++]; v |= BigInt(x & 0x7f) << s; if (!(x & 0x80)) break; s += 7n; } return [v, i]; }
function fieldsOf(b) { const o = []; let p = 0; while (p < b.length) { const st = p; let t; [t, p] = rv(b, p); const f = Number(t >> 3n), wt = Number(t & 7n); let e = p; if (wt === 0) [, e] = rv(b, p); else if (wt === 1) e = p + 8; else if (wt === 5) e = p + 4; else { let l; [l, p] = rv(b, p); e = p + Number(l); } o.push({ f, wt, raw: b.subarray(st, e), inner: wt === 2 ? b.subarray(p, e) : null }); p = e; } return o; }
/** Replace every connection with `edges` [{from,to,fromPort?,toPort?,toSlot?}] (creation order = array order). */
async function rewire(body, edges) {
  const { magic, proto } = await unwrapBody(body);
  const top = fieldsOf(proto);
  const rebuilt = top.map((t) => {
    if (t.f !== 1 || t.wt !== 2) return t.raw;
    const keep = fieldsOf(t.inner).filter((g) => !(g.f === 8 && g.wt === 2)).map((g) => g.raw);
    const conns = edges.map((e, i) => msg(8, Buffer.concat([vint(1, e.from), ...(e.toSlot ? [vint(2, 1)] : []), vint(3, e.to), ...(e.toSlot ? [vint(4, e.toSlot)] : []), vint(5, e.fromPort ?? 64), vint(6, e.toPort ?? 64), vint(7, i + 1)])));
    return msg(1, Buffer.concat([...keep, ...conns]));
  });
  return wrapBody(magic, Buffer.concat(rebuilt));
}
const ids = async (body) => (await layout.readTopology(body)).nodes.map((n) => n.id);
const posById = (topo, positions) => Object.fromEntries(topo.nodes.map((n, i) => [n.id, positions[i]]));

test('a plain chain lands on the measured row in CHAIN order, not list order', async () => {
  const body = await chainBody(3);
  const [a, b, c] = await ids(body);
  const rewired = await rewire(body, [{ from: c, to: a }, { from: a, to: b }]); // chain c → a → b
  const t = await layout.readTopology(rewired);
  assert.equal(t.meta.kind, 'chain');
  assert.deepEqual(posById(t, t.planned), { [c]: [290, 428], [a]: [785, 428], [b]: [1280, 428] });
  const r = await layout.relayoutBody(rewired);
  assert.deepEqual(await layout.readNodePositions(r.body), t.planned, 'written positions = planned (list order)');
  assert.equal(r.meta.kind, 'chain');
});

test('generator chains (list order = chain order) still get the old row exactly', async () => {
  const body = await chainBody(4);
  const r = await layout.relayoutBody(body);
  assert.deepEqual(r.positions, layout.cleanRowPositions(4));
  assert.equal(r.meta.kind, 'chain');
});

test('a fan-out stacks its branches into lanes and the merge comes back to the main line', async () => {
  const body = await chainBody(5);
  const [a, b, c, d, e] = await ids(body);
  // a → b, a → c, a → d (three branches), b/c/d → e (mixer)
  const rewired = await rewire(body, [{ from: a, to: b }, { from: a, to: c }, { from: a, to: d }, { from: b, to: e, toSlot: 1 }, { from: c, to: e, toSlot: 2 }, { from: d, to: e, toSlot: 3 }]);
  const t = await layout.readTopology(rewired);
  assert.deepEqual(t.meta, { kind: 'dag', ranks: 3, lanes: 3, keyLinks: 0 });
  assert.deepEqual(posById(t, t.planned), { [a]: [290, 428], [b]: [785, 428], [c]: [785, 606], [d]: [785, 784], [e]: [1280, 428] });
  // Lane pitch is tunable (it is the one unmeasured constant).
  const t2 = await layout.readTopology(rewired, { spacingY: 200 });
  assert.deepEqual(posById(t2, t2.planned)[d], [785, 828]);
});

test('branch order follows the mixer input slot, not creation order', async () => {
  const body = await chainBody(4);
  const [a, b, c, d] = await ids(body);
  // c was created first but feeds slot 2; b feeds slot 1 → b takes the main lane.
  const rewired = await rewire(body, [{ from: a, to: c }, { from: a, to: b }, { from: c, to: d, toSlot: 2 }, { from: b, to: d, toSlot: 1 }]);
  const t = await layout.readTopology(rewired);
  const p = posById(t, t.planned);
  assert.deepEqual(p[b], [785, 428]);
  assert.deepEqual(p[c], [785, 606]);
});

test('a key link (port 16 → 16) never moves a node', async () => {
  const body = await chainBody(3);
  const [a, b, c] = await ids(body);
  const rewired = await rewire(body, [{ from: a, to: b }, { from: b, to: c }, { from: a, to: c, fromPort: 16, toPort: 16, toSlot: 1 }]);
  const t = await layout.readTopology(rewired);
  assert.equal(t.meta.kind, 'chain');
  assert.equal(t.meta.keyLinks, 1);
  assert.deepEqual(posById(t, t.planned), { [a]: [290, 428], [b]: [785, 428], [c]: [1280, 428] });
});

test('unrankable wiring (a cycle) falls back to a row in index order and says so', async () => {
  const body = await chainBody(3);
  const [a, b, c] = await ids(body);
  const rewired = await rewire(body, [{ from: a, to: b }, { from: b, to: c }, { from: c, to: a }]);
  const t = await layout.readTopology(rewired);
  assert.equal(t.meta.kind, 'row');
  assert.equal(t.meta.fallback, 'unrankable graph');
  assert.equal(t.planned.length, 3);
  assert.deepEqual(t.planned.map((p) => p[1]), [428, 428, 428]);
});

test('layout:"row" reproduces the pre-topology behaviour (list order)', async () => {
  const body = await chainBody(3);
  const [a, b, c] = await ids(body);
  const rewired = await rewire(body, [{ from: c, to: a }, { from: a, to: b }]);
  const r = await layout.relayoutBody(rewired, { layout: 'row' });
  assert.deepEqual(r.positions, layout.cleanRowPositions(3));
  assert.equal(r.meta.kind, 'row');
});

test('null control: a single node has nothing to rank and sits at the row origin', async () => {
  const body = await chainBody(1);
  const t = await layout.readTopology(body);
  assert.deepEqual(t.planned, [[290, 428]]);
  assert.equal(t.meta.kind, 'row');
});
