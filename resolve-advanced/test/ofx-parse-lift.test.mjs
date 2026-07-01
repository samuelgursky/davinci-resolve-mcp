/**
 * OFX decode/write through the FULL envelope + STORED-body support — landed 2026-07-03.
 *
 * 1. OFX params are SELF-DESCRIBING on the wire (name string + float64/string value;
 *    enums are label strings) — verified against real project grades (filmgrain, CST,
 *    acestransform). The parser now lifts them onto `node.ofxTools`, and the generator
 *    accepts `gradeParams.ofx = {pluginId, params}` — so generate→parse round-trips
 *    names and values with no per-plugin registry.
 * 2. Body magic 0x80 = STORED (uncompressed protobuf), 0x81 = zstd. Real projects carry
 *    ~10% stored bodies; the parser previously refused them outright.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { drxTool } from '../server/tools/drx.mjs';

const require = createRequire(import.meta.url);

const OFX_ARGS = {
  gradeParams: {
    gain: [1.05, 1, 1, 1.0122],
    ofx: {
      pluginId: 'com.blackmagicdesign.resolvefx.filmgrain',
      params: { GrainStrength: 0.42, GrainSize: 0.5, softness: 0.3, filmGrainPresets: 'GRAIN_PRE_CUSTOM' },
    },
  },
  metadata: { label: 'ofx lift test' },
};

test('OFX: generate→parse round-trips pluginId + named params through the full envelope', async () => {
  const r = await drxTool.handler({ action: 'generate', args: OFX_ARGS });
  const p = await drxTool.handler({ action: 'parse', args: { content: r.content } });
  const withOfx = (p.nodes || []).filter((n) => n.ofxTools && n.ofxTools.length);
  assert.equal(withOfx.length, 1, 'exactly one node carries the OFX tool');
  const t = withOfx[0].ofxTools[0];
  assert.equal(t.pluginId, 'com.blackmagicdesign.resolvefx.filmgrain');
  assert.equal(t.enabled, true);
  assert.ok(Math.abs(t.params.GrainStrength - 0.42) < 1e-9);
  assert.ok(Math.abs(t.params.softness - 0.3) < 1e-9);
  assert.equal(t.params.filmGrainPresets, 'GRAIN_PRE_CUSTOM');
});

test('0x80 STORED body: parses identically to the zstd body it was derived from', async () => {
  const { parseDRXContent } = require('../vendor/drx-codec/drx-parser.js');
  const r = await drxTool.handler({ action: 'generate', args: OFX_ARGS });
  const hex = r.content.match(/<Body>([0-9a-f]+)<\/Body>/i)[1];
  const zbuf = Buffer.from(hex, 'hex');
  assert.equal(zbuf[0], 0x81, 'generator writes zstd bodies');
  // decompress and re-envelope as STORED (0x80 + raw protobuf)
  let raw;
  const zlib = await import('node:zlib');
  if (typeof zlib.zstdDecompressSync === 'function') raw = zlib.zstdDecompressSync(zbuf.subarray(1));
  else raw = Buffer.from(require('fzstd').decompress(zbuf.subarray(1)));
  const stored = Buffer.concat([Buffer.from([0x80]), raw]);
  const storedXml = r.content.replace(/<Body>[0-9a-f]+<\/Body>/i, `<Body>${stored.toString('hex')}</Body>`);
  const a = await parseDRXContent(r.content);
  const b = await parseDRXContent(storedXml);
  assert.equal(b.nodes.length, a.nodes.length, 'same node count');
  const ta = a.nodes.find((n) => n.ofxTools), tb = b.nodes.find((n) => n.ofxTools);
  assert.ok(tb, 'stored body lifts ofxTools too');
  assert.deepEqual(tb.ofxTools[0].params, ta.ofxTools[0].params, 'identical OFX params');
});

test('OFX container: native structure — Filter context, resolvefxVersion, universal entry ids', async () => {
  // Live-confirmed 2026-07-03 (_mcp_ofx_live2 render): a written filmgrain node ENGAGES
  // (flat patch YMIN=YMAX → full grain spread) and a CST node written with the SAME ids
  // engages too — Resolve keys plugins on the pluginId STRING; entry ids are universal
  // (0x49 pluginId / 0x5E context / 0x63 enable / 0x87 container / 0xD2 end). The two
  // historical write bugs: misplaced entry ids (hard CRASH on deserialize) and a
  // synthesized F3 "instance id" (F3 is the OFX CONTEXT name — wrong name = plugin
  // silently never instantiates).
  const r = await drxTool.handler({ action: 'generate', args: OFX_ARGS });
  const p = await drxTool.handler({ action: 'parse', args: { content: r.content } });
  const t = p.nodes.flatMap((n) => n.ofxTools || [])[0];
  assert.equal(t.instanceId, 'OfxImageEffectContextFilter', 'F3 must be the standard Filter context');
  assert.equal(t.params.resolvefxVersion, '3.2', 'version param always serialized');
});
