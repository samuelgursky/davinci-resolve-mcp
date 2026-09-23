/**
 * OFX instance binding + integer params in generated DRX.
 *
 * Native Resolve (Studio 21.0 CST capture) writes the tool-list instance entry
 * (0xC000005E) as "<context>_<clip-version DbId>_<node id>" while the OFX
 * container's F3 keeps the bare context. With the bare context in both slots
 * the node applies but the plugin's stored params never bind — verified live by
 * exporting a 33-pt LUT: the generated CST only matched a hand-built CST
 * (bit-identical, 35,937/35,937 points) once the keyed form was emitted.
 *
 * Integer params (doFwdOOTF / doInvOOTF) are varint F3 on the wire.
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const zlib = require('node:zlib');

const { drxGenerator, drxParser } = require('..');

const CST = 'com.blackmagicdesign.resolvefx.colorspacetransformv2';

function decompressClipBody(xml) {
  const hex = xml.match(/<pClipFullVer>[\s\S]*?<Body>([0-9a-f]+)<\/Body>/)[1];
  const body = Buffer.from(hex, 'hex');
  assert.equal(body[0], 0x81);
  const decompress = zlib.zstdDecompressSync
    ? (b) => zlib.zstdDecompressSync(b)
    : (b) => Buffer.from(require('fzstd').decompress(b));
  return decompress(body.subarray(1));
}

async function generateCstGraph() {
  const nodes = [
    { label: 'CC' },
    {
      label: 'CST 709',
      params: {
        ofx: {
          pluginId: CST,
          params: {
            inputColorSpace: 'DWG_COLORSPACE',
            inputGamma: 'DAV_INTER_OETF_GAMMA',
            outputColorSpace: 'REC709_COLORSPACE',
            outputGamma: 'TWOPOINTFOUR_GAMMA',
            doFwdOOTF: { int: 1 },
            doInvOOTF: { int: 0 },
          },
          options: { version: '1.4' },
        },
      },
    },
  ];
  return drxGenerator.generateMultiNodeDRX(nodes, [{ from: 1, to: 2 }], { label: 'test' });
}

test('tool-list instance entry is keyed by clip version DbId and node id', async () => {
  const xml = await generateCstGraph();
  const versionId = xml.match(/<pClipFullVer>\s*<ListMgt::LmVersion DbId="([0-9a-f-]+)"/)[1];
  const raw = decompressClipBody(xml);
  // Fresh mode numbers nodes from 2, so the CST (second node) has id 3.
  const keyed = Buffer.from(`OfxImageEffectContextFilter_${versionId}_3`, 'utf-8');
  assert.ok(raw.includes(keyed), 'keyed instance id present in tool list');
});

test('OFX container keeps the bare context name', async () => {
  const xml = await generateCstGraph();
  const parsed = await drxParser.parseDRXContent(xml);
  const tool = parsed.nodes[1].ofxTools[0];
  assert.equal(tool.pluginId, CST);
  assert.equal(tool.instanceId, 'OfxImageEffectContextFilter');
});

test('integer params round-trip as {int} via varint F3', async () => {
  const xml = await generateCstGraph();
  const parsed = await drxParser.parseDRXContent(xml);
  const params = parsed.nodes[1].ofxTools[0].params;
  assert.deepEqual(params.doFwdOOTF, { int: 1 });
  assert.deepEqual(params.doInvOOTF, { int: 0 });
  assert.equal(params.inputColorSpace, 'DWG_COLORSPACE');
  assert.equal(params.outputGamma, 'TWOPOINTFOUR_GAMMA');

  // wire check: name entry followed by F2{F3 varint 1}
  const raw = decompressClipBody(xml);
  const name = Buffer.from('doFwdOOTF', 'utf-8');
  const expected = Buffer.concat([Buffer.from([0x0a, name.length]), name, Buffer.from([0x12, 0x02, 0x18, 0x01])]);
  assert.ok(raw.includes(expected), 'doFwdOOTF encoded as varint F3');
});

test('explicit instanceKey option is honoured', async () => {
  const xml = await drxGenerator.generateMultiNodeDRX(
    [{ label: 'X', params: { ofx: { pluginId: CST, params: {}, options: { instanceKey: 'Custom_key_9' } } } }],
    [],
    { label: 'test' },
  );
  assert.ok(decompressClipBody(xml).includes(Buffer.from('Custom_key_9')));
});
