/**
 * Node-graph LAYOUT rewriter — repositions nodes in a DRX/LmVersion grade Body
 * without touching any grade content.
 *
 * A grade Body is [0x81] + zstd(protobuf), or [0x80] + protobuf STORED uncompressed
 * (how Resolve serialises small/default graphs in .drp exports). Inside the protobuf, each F1 container
 * holds F7 node messages whose F4 (xPos) / F5 (yPos) varints are the node-editor
 * layout. Resolve's own "Cleanup Node Graph" rewrites ONLY those two fields
 * (verified by before/after Project.db diff, 2026-07): its clean layout is an
 * evenly spaced single row (observed x = 290/786/1280 at y = 428 for 3 nodes).
 *
 * This module replicates that: every byte other than the F4/F5 varints (and the
 * containing length prefixes) survives verbatim, so the rewrite is lossless for
 * OFX/uncalibrated params, keyframes, labels — everything.
 *
 * TOPOLOGY (2026-09-14): positions come from the graph's own connections, not from
 * the node list order. Each F1 container also carries F8 connection messages
 * (F1 = from node id, F3 = to node id, F5/F6 = source/target port — 64 is the RGB
 * path, 16 is a key link — F2/F4 = slot on multi-input nodes, F7 = creation order)
 * and F9/F10 input/output markers whose F3.F4 name the chain's first and last node.
 * Nodes are ranked by longest RGB path from the source (x), branches of a split are
 * stacked into lanes (y) and a merge returns to its lowest input lane. A plain
 * chain therefore lands on exactly the measured clean row — in CHAIN order, which
 * the list order is not (Resolve lists nodes by id; a node inserted mid-chain has
 * a high id). Key links never move a node. Lane spacing (spacingY, default 178 —
 * Resolve's own vertical placement grid seen in every stacked export) is NOT yet
 * measured against native Cleanup on a mixer graph; the x row is.
 *
 * Consumed by the drx tool's `relayout` action (live single-shot path: grab →
 * relayout → ApplyGradeFromDRX), drp's `relayout_node_graphs` (exported project
 * sweep) and project_db's `relayout_node_graphs` (closed-project bulk patch).
 */

'use strict';

const nodeZlib = require('zlib');

// Same zstd backend priority as drx-generator.js: native node:zlib (Node 22+),
// zstd-codec (WASM), fzstd (decompress-only — compress throws clearly).
const HAS_NATIVE_ZSTD =
  typeof nodeZlib.zstdCompressSync === 'function' && typeof nodeZlib.zstdDecompressSync === 'function';

let ZstdCodec = null;
try {
  ZstdCodec = require('zstd-codec').ZstdCodec;
} catch {
  /* optional */
}

let backend = null;
async function getZstd() {
  if (backend) return backend;
  if (HAS_NATIVE_ZSTD) {
    backend = {
      decompress: (data) => nodeZlib.zstdDecompressSync(Buffer.from(data)),
      compress: (data) => nodeZlib.zstdCompressSync(Buffer.from(data)),
    };
    return backend;
  }
  if (ZstdCodec) {
    backend = await new Promise((resolve) => {
      ZstdCodec.run((zstd) => {
        const simple = new zstd.Simple();
        resolve({
          decompress: (data) => Buffer.from(simple.decompress(new Uint8Array(data))),
          compress: (data) => Buffer.from(simple.compress(new Uint8Array(data))),
        });
      });
    });
    return backend;
  }
  const fzstd = require('fzstd');
  backend = {
    decompress: (data) => Buffer.from(fzstd.decompress(new Uint8Array(data))),
    compress: () => {
      throw new Error('no zstd compressor available (need Node 22+ zlib zstd or zstd-codec)');
    },
  };
  return backend;
}

// ---- Body container: 0x81 = zstd-compressed, 0x80 = stored (uncompressed) ----

const MAGIC_ZSTD = 0x81;
const MAGIC_STORED = 0x80;

/** Split a Body into its container kind and the raw protobuf. */
async function unwrapBody(body) {
  if (body[0] === MAGIC_ZSTD) {
    const zstd = await getZstd();
    return { magic: MAGIC_ZSTD, proto: zstd.decompress(body.subarray(1)) };
  }
  if (body[0] === MAGIC_STORED) return { magic: MAGIC_STORED, proto: Buffer.from(body.subarray(1)) };
  throw new Error('not a grade Body (missing 0x81/0x80 magic)');
}

/** Re-wrap a protobuf in the SAME container kind it came from (lossless in kind). */
async function wrapBody(magic, proto) {
  if (magic === MAGIC_STORED) return Buffer.concat([Buffer.from([MAGIC_STORED]), proto]);
  const zstd = await getZstd();
  return Buffer.concat([Buffer.from([MAGIC_ZSTD]), zstd.compress(proto)]);
}

// ---- minimal protobuf walker (varint + length-delimited only, as the Body uses) ----

function readVarint(buf, p) {
  let v = 0n;
  let s = 0n;
  let i = p;
  for (;;) {
    const b = buf[i++];
    v |= BigInt(b & 0x7f) << s;
    if (!(b & 0x80)) break;
    s += 7n;
  }
  return [v, i];
}

function encodeVarint(v) {
  v = BigInt(v);
  const out = [];
  while (v > 0x7fn) {
    out.push(Number(v & 0x7fn) | 0x80);
    v >>= 7n;
  }
  out.push(Number(v));
  return Buffer.from(out);
}

/** Decode one message level into {f, wt, start, end, val} field records. */
function fields(buf) {
  const out = [];
  let p = 0;
  while (p < buf.length) {
    const start = p;
    let tag;
    [tag, p] = readVarint(buf, p);
    const f = Number(tag >> 3n);
    const wt = Number(tag & 7n);
    let end = p;
    let val = null;
    if (wt === 0) [val, end] = readVarint(buf, p);
    else if (wt === 1) end = p + 8;
    else if (wt === 5) end = p + 4;
    else if (wt === 2) {
      let len;
      [len, p] = readVarint(buf, p);
      end = p + Number(len);
      val = buf.subarray(p, end);
    } else throw new Error(`unsupported wire type ${wt} at offset ${start}`);
    if (end > buf.length) throw new Error('truncated protobuf');
    out.push({ f, wt, start, end, val });
    p = end;
  }
  return out;
}

// Node message field numbers (see DRX-VALUE-SCALING.md / calibration notes):
// F4 = xPos varint, F5 = yPos varint.
const F_NODE = 7; // node message inside the F1 container
const F_X = 4;
const F_Y = 5;

// Connection message field numbers.
const F_CONN = 8;
const RGB_PORT = 64;
const KEY_PORT = 16;

/** Decode nodes (list order) + connections + chain endpoints from a decompressed Body. */
function decodeTopology(proto) {
  const nodes = [];
  const edges = [];
  let first = null;
  let last = null;
  for (const t of fields(proto)) {
    if (t.f !== 1 || t.wt !== 2) continue;
    for (const g of fields(t.val)) {
      if (g.f === F_NODE && g.wt === 2) {
        const n = { id: null, index: null, x: null, y: null };
        for (const h of fields(g.val)) {
          if (h.wt !== 0) continue;
          if (h.f === 1) n.id = Number(h.val);
          else if (h.f === 2) n.index = Number(h.val);
          else if (h.f === F_X) n.x = Number(h.val);
          else if (h.f === F_Y) n.y = Number(h.val);
        }
        nodes.push(n);
      } else if (g.f === F_CONN && g.wt === 2) {
        const e = { from: null, to: null, fromPort: RGB_PORT, toPort: RGB_PORT, fromSlot: 0, toSlot: 0, order: 0 };
        for (const h of fields(g.val)) {
          if (h.wt !== 0) continue;
          const v = Number(h.val);
          if (h.f === 1) e.from = v;
          else if (h.f === 2) e.fromSlot = v;
          else if (h.f === 3) e.to = v;
          else if (h.f === 4) e.toSlot = v;
          else if (h.f === 5) e.fromPort = v;
          else if (h.f === 6) e.toPort = v;
          else if (h.f === 7) e.order = v;
        }
        if (e.from !== null && e.to !== null) edges.push(e);
      } else if ((g.f === 9 || g.f === 10) && g.wt === 2) {
        for (const h of fields(g.val)) {
          if (h.f !== 3 || h.wt !== 2) continue;
          for (const k of fields(h.val)) if (k.f === 4 && k.wt === 0) (g.f === 9 ? (first = Number(k.val)) : (last = Number(k.val)));
        }
      }
    }
  }
  return { nodes, edges, first, last };
}

/**
 * Plan positions from topology. Returns positions in NODE LIST order (what
 * relayoutBody writes) plus a meta block. Falls back to the plain row — in
 * chain order when the graph has a chain, else list order — on anything it
 * cannot rank (cycles, dangling ids).
 *
 * Lanes: walking ranks left→right, a node with k RGB outputs fans its children
 * into lanes lane, lane+1, … (ordered by the target's input slot, then creation
 * order); a node with several RGB inputs (a mixer) sits on the lowest of its
 * input lanes; two nodes claiming one (rank, lane) cell push the later one down.
 */
function planPositions(topo, { originX = 290, originY = 428, spacingX = 495, spacingY = 178, layout = 'topology' } = {}) {
  const n = topo.nodes.length;
  const ids = topo.nodes.map((v) => v.id);
  const byId = new Map(ids.map((id, i) => [id, i]));
  const rowPositions = (orderIdx) => {
    const pos = new Array(n);
    orderIdx.forEach((listIdx, k) => (pos[listIdx] = [originX + k * spacingX, originY]));
    return pos;
  };
  const listOrder = topo.nodes.map((_, i) => i);
  if (n === 0) return { positions: [], meta: { kind: 'empty', ranks: 0, lanes: 0 } };
  if (layout === 'row' || n === 1) return { positions: rowPositions(listOrder), meta: { kind: 'row', ranks: n, lanes: 1 } };

  const flow = topo.edges.filter((e) => !(e.fromPort === KEY_PORT && e.toPort === KEY_PORT) && byId.has(e.from) && byId.has(e.to) && e.from !== e.to);
  const keyLinks = topo.edges.length - flow.length;
  if (!flow.length) {
    // No wiring at all: order by Resolve's own index field, then list order.
    const order = [...listOrder].sort((a, b) => (topo.nodes[a].index ?? 1e9) - (topo.nodes[b].index ?? 1e9) || a - b);
    return { positions: rowPositions(order), meta: { kind: 'row', ranks: n, lanes: 1, keyLinks } };
  }

  const out = new Map(ids.map((id) => [id, []]));
  const indeg = new Map(ids.map((id) => [id, 0]));
  for (const e of flow) {
    out.get(e.from).push(e);
    indeg.set(e.to, indeg.get(e.to) + 1);
  }
  // Branch order at a fan-out: the slot this edge lands in, else the slot the
  // branch eventually feeds on its merge (Resolve numbers mixer inputs top-down),
  // else creation order.
  const mergeSlot = (id) => Math.min(Infinity, ...(out.get(id) || []).map((e) => e.toSlot || Infinity));
  for (const list of out.values()) list.sort((a, b) => (a.toSlot || 0) - (b.toSlot || 0) || mergeSlot(a.to) - mergeSlot(b.to) || a.order - b.order);

  // Longest-path ranks (Kahn); a cycle leaves nodes unranked → fall back.
  const rank = new Map();
  const queue = ids.filter((id) => indeg.get(id) === 0);
  const remaining = new Map(indeg);
  for (const id of queue) rank.set(id, 0);
  while (queue.length) {
    const id = queue.shift();
    for (const e of out.get(id)) {
      rank.set(e.to, Math.max(rank.get(e.to) ?? 0, rank.get(id) + 1));
      remaining.set(e.to, remaining.get(e.to) - 1);
      if (remaining.get(e.to) === 0) queue.push(e.to);
    }
  }
  if (rank.size !== n) {
    const order = [...listOrder].sort((a, b) => (topo.nodes[a].index ?? 1e9) - (topo.nodes[b].index ?? 1e9) || a - b);
    return { positions: rowPositions(order), meta: { kind: 'row', ranks: n, lanes: 1, keyLinks, fallback: 'unrankable graph' } };
  }

  // Lanes, walking ranks left → right (parents are always placed before children):
  //   no input        → lane 0
  //   one input p     → lane(p) + k, k = this edge's position among p's outputs
  //   several inputs  → the lowest input lane (a merge comes back to the main line)
  // A (rank, lane) cell taken by an earlier node pushes the later one down.
  const lane = new Map();
  const taken = new Set();
  const claim = (id, want) => {
    let l = want;
    while (taken.has(`${rank.get(id)}:${l}`)) l += 1;
    lane.set(id, l);
    taken.add(`${rank.get(id)}:${l}`);
  };
  const idx = (id) => topo.nodes[byId.get(id)].index ?? 0;
  const byRank = [...ids].sort((a, b) => rank.get(a) - rank.get(b) || (a === topo.first ? -1 : b === topo.first ? 1 : 0) || idx(a) - idx(b));
  const inputsOf = new Map(ids.map((id) => [id, []]));
  for (const e of flow) inputsOf.get(e.to).push(e);
  for (const id of byRank) {
    const ins = inputsOf.get(id);
    let want = 0;
    if (ins.length === 1) {
      const p = ins[0].from;
      const k = out.get(p).findIndex((e) => e.to === id);
      want = (lane.get(p) ?? 0) + Math.max(0, k);
    } else if (ins.length > 1) {
      want = Math.min(...ins.map((e) => lane.get(e.from) ?? 0));
    }
    claim(id, want);
  }

  const positions = new Array(n);
  let maxRank = 0;
  let maxLane = 0;
  for (const id of ids) {
    const r = rank.get(id);
    const l = lane.get(id);
    maxRank = Math.max(maxRank, r);
    maxLane = Math.max(maxLane, l);
    positions[byId.get(id)] = [originX + r * spacingX, originY + l * spacingY];
  }
  return { positions, meta: { kind: maxLane > 0 ? 'dag' : 'chain', ranks: maxRank + 1, lanes: maxLane + 1, keyLinks } };
}

/**
 * Resolve-cleanup-style positions for n nodes: one evenly spaced row.
 * Defaults are the exact values Resolve's own Cleanup Node Graph produced
 * (3-node measurement); spacing stays fixed rather than adapting to n so the
 * result matches native cleanup for typical graphs.
 */
function cleanRowPositions(n, { originX = 290, originY = 428, spacingX = 495 } = {}) {
  return Array.from({ length: n }, (_, i) => [originX + i * spacingX, originY]);
}

/** Rewrite F4/F5 in one node message buffer; appends them if absent. */
function rewriteNodeMessage(nodeBuf, x, y) {
  const parts = [];
  let sawX = false;
  let sawY = false;
  for (const h of fields(nodeBuf)) {
    if (h.f === F_X && h.wt === 0) {
      sawX = true;
      parts.push(encodeVarint((F_X << 3) | 0), encodeVarint(x));
    } else if (h.f === F_Y && h.wt === 0) {
      sawY = true;
      parts.push(encodeVarint((F_Y << 3) | 0), encodeVarint(y));
    } else {
      parts.push(nodeBuf.subarray(h.start, h.end));
    }
  }
  if (!sawX) parts.push(encodeVarint((F_X << 3) | 0), encodeVarint(x));
  if (!sawY) parts.push(encodeVarint((F_Y << 3) | 0), encodeVarint(y));
  return Buffer.concat(parts);
}

/**
 * Reposition every node in a grade Body.
 *
 * @param {Buffer} body — raw Body blob: 0x81 magic + zstd(protobuf)
 * @param {Object} [options]
 * @param {Array<[number,number]>} [options.positions] — explicit [x,y] per node
 *   (encounter order = node index order); omit for the clean-row layout.
 * @param {number} [options.originX] @param {number} [options.originY]
 * @param {number} [options.spacingX] — clean-row tuning when positions omitted.
 * @returns {Promise<{body: Buffer, nodeCount: number, positions: Array<[number,number]>}>}
 */
async function relayoutBody(body, options = {}) {
  if (!Buffer.isBuffer(body)) body = Buffer.from(body);
  const { magic, proto } = await unwrapBody(body);

  // First pass: count nodes so the default layout can be sized.
  const top = fields(proto);
  let nodeCount = 0;
  for (const t of top) {
    if (t.f === 1 && t.wt === 2) for (const g of fields(t.val)) if (g.f === F_NODE && g.wt === 2) nodeCount++;
  }
  if (nodeCount === 0) throw new Error('relayout refused: Body decodes to 0 nodes');

  let meta = { kind: 'explicit', ranks: nodeCount, lanes: 1 };
  let positions = options.positions;
  if (!positions) {
    const planned = planPositions(decodeTopology(proto), options);
    positions = planned.positions;
    meta = planned.meta;
  }
  if (positions.length < nodeCount) {
    throw new Error(`positions has ${positions.length} entries but the grade has ${nodeCount} nodes`);
  }
  for (const [x, y] of positions.slice(0, nodeCount)) {
    if (!Number.isInteger(x) || !Number.isInteger(y) || x < 0 || y < 0) {
      throw new Error('positions must be non-negative integers (protobuf varints)');
    }
  }

  // Second pass: rebuild, rewriting each node message and re-lengthing its containers.
  let nodeIdx = 0;
  const rebuilt = [];
  for (const t of top) {
    if (t.f === 1 && t.wt === 2) {
      const innerParts = [];
      for (const g of fields(t.val)) {
        if (g.f === F_NODE && g.wt === 2) {
          const [x, y] = positions[nodeIdx++];
          const newNode = rewriteNodeMessage(g.val, x, y);
          innerParts.push(encodeVarint((F_NODE << 3) | 2), encodeVarint(newNode.length), newNode);
        } else {
          innerParts.push(t.val.subarray(g.start, g.end));
        }
      }
      const newInner = Buffer.concat(innerParts);
      rebuilt.push(encodeVarint((1 << 3) | 2), encodeVarint(newInner.length), newInner);
    } else {
      rebuilt.push(proto.subarray(t.start, t.end));
    }
  }

  const out = await wrapBody(magic, Buffer.concat(rebuilt));
  return { body: out, nodeCount, positions: positions.slice(0, nodeCount), meta };
}

/** Hex-string convenience wrapper (DRX <Body> / DB dumps are handled as hex upstream). */
async function relayoutBodyHex(bodyHex, options = {}) {
  const r = await relayoutBody(Buffer.from(bodyHex.trim(), 'hex'), options);
  return { ...r, bodyHex: r.body.toString('hex') };
}

/** Decode nodes + connections + planned positions without rewriting anything. */
async function readTopology(body, options = {}) {
  if (!Buffer.isBuffer(body)) body = Buffer.from(body);
  const { proto } = await unwrapBody(body);
  const topo = decodeTopology(proto);
  const planned = planPositions(topo, options);
  return { ...topo, planned: planned.positions, meta: planned.meta };
}

/** Decode just the node positions from a Body (for dry runs / verification). */
async function readNodePositions(body) {
  if (!Buffer.isBuffer(body)) body = Buffer.from(body);
  const { proto } = await unwrapBody(body);
  const positions = [];
  for (const t of fields(proto)) {
    if (t.f !== 1 || t.wt !== 2) continue;
    for (const g of fields(t.val)) {
      if (g.f !== F_NODE || g.wt !== 2) continue;
      let x = null;
      let y = null;
      for (const h of fields(g.val)) {
        if (h.f === F_X && h.wt === 0) x = Number(h.val);
        if (h.f === F_Y && h.wt === 0) y = Number(h.val);
      }
      positions.push([x, y]);
    }
  }
  return positions;
}

module.exports = { relayoutBody, relayoutBodyHex, readNodePositions, readTopology, decodeTopology, planPositions, cleanRowPositions, unwrapBody, wrapBody, encodeVarint };
