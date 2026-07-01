/**
 * Node-graph LAYOUT rewriter — repositions nodes in a DRX/LmVersion grade Body
 * without touching any grade content.
 *
 * A grade Body is [0x81] + zstd(protobuf). Inside the protobuf, each F1 container
 * holds F7 node messages whose F4 (xPos) / F5 (yPos) varints are the node-editor
 * layout. Resolve's own "Cleanup Node Graph" rewrites ONLY those two fields
 * (verified by before/after Project.db diff, 2026-07): its clean layout is an
 * evenly spaced single row (observed x = 290/786/1280 at y = 428 for 3 nodes).
 *
 * This module replicates that: every byte other than the F4/F5 varints (and the
 * containing length prefixes) survives verbatim, so the rewrite is lossless for
 * OFX/uncalibrated params, keyframes, labels — everything.
 *
 * Consumed by the drx tool's `relayout` action (live single-shot path: grab →
 * relayout → ApplyGradeFromDRX) and project_db's `relayout_node_graphs`
 * (closed-project bulk patch of ListMgt::LmVersion rows).
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
  if (body[0] !== 0x81) throw new Error('not a grade Body (missing 0x81 magic)');
  const zstd = await getZstd();
  const proto = zstd.decompress(body.subarray(1));

  // First pass: count nodes so the default layout can be sized.
  const top = fields(proto);
  let nodeCount = 0;
  for (const t of top) {
    if (t.f === 1 && t.wt === 2) for (const g of fields(t.val)) if (g.f === F_NODE && g.wt === 2) nodeCount++;
  }
  if (nodeCount === 0) throw new Error('relayout refused: Body decodes to 0 nodes');

  const positions = options.positions || cleanRowPositions(nodeCount, options);
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

  const out = Buffer.concat([Buffer.from([0x81]), zstd.compress(Buffer.concat(rebuilt))]);
  return { body: out, nodeCount, positions: positions.slice(0, nodeCount) };
}

/** Hex-string convenience wrapper (DRX <Body> / DB dumps are handled as hex upstream). */
async function relayoutBodyHex(bodyHex, options = {}) {
  const r = await relayoutBody(Buffer.from(bodyHex.trim(), 'hex'), options);
  return { ...r, bodyHex: r.body.toString('hex') };
}

/** Decode just the node positions from a Body (for dry runs / verification). */
async function readNodePositions(body) {
  if (!Buffer.isBuffer(body)) body = Buffer.from(body);
  if (body[0] !== 0x81) throw new Error('not a grade Body (missing 0x81 magic)');
  const zstd = await getZstd();
  const proto = zstd.decompress(body.subarray(1));
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

module.exports = { relayoutBody, relayoutBodyHex, readNodePositions, cleanRowPositions };
