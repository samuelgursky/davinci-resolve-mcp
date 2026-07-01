const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const JSZip = require('jszip');
const {
  decodeKeyedDict, encodeKeyedDict, readKeyedDict, keyedDictType,
  getKeyedValue, setKeyedValue, readAudioTracks,
} = require('../keyed-dict');

const FIXTURE = 'docs/design/drp-drx-drt-closeout-harness/fixtures/canary-resolve21.drp';

async function grabAll(tag) {
  const zip = await JSZip.loadAsync(fs.readFileSync(FIXTURE));
  const out = [];
  for (const name of Object.keys(zip.files)) {
    if (!name.endsWith('.xml')) continue;
    const x = await zip.files[name].async('string');
    const re = new RegExp(`<${tag}>([0-9a-f]+)</${tag}>`, 'g');
    let m;
    while ((m = re.exec(x))) out.push(m[1]);
  }
  return out;
}

test('decodeKeyedDict parses Geometry with typed values', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip('fixture missing'); return; }
  const hex = (await grabAll('Geometry'))[0];
  const { count, entries } = decodeKeyedDict(hex);
  assert.strictEqual(count, entries.length, 'count matches entry total');
  const byKey = Object.fromEntries(entries.map((e) => [e.key, e]));
  assert.strictEqual(byKey.DbType.value, 'BtGeometry');
  // Resolution is a BYTES value [u32 0][u32 W][u32 0][u32 H] — W=352 H=262 in the canary template.
  const res = Buffer.from(byKey.Resolution.value, 'hex');
  assert.strictEqual(res.readUInt32BE(4), 352);
  assert.strictEqual(res.readUInt32BE(12), 262);
});

test('decodeKeyedDict parses Time (StartFrame/NumFrames/FrameRate)', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip('fixture missing'); return; }
  const hex = (await grabAll('Time'))[0];
  const byKey = Object.fromEntries(decodeKeyedDict(hex).entries.map((e) => [e.key, e]));
  assert.strictEqual(byKey.StartFrame.value, 0);
  assert.strictEqual(byKey.NumFrames.value, 4576);
  assert.strictEqual(keyedDictType(hex), 'BtVideoTime');
  // FrameRate BYTES value is [double fps LE][double 0] — 29.97 in the canary.
  const fr = Buffer.from(byKey.FrameRate.value, 'hex');
  assert.ok(Math.abs(fr.readDoubleLE(0) - 30000 / 1001) < 1e-6, `fps ${fr.readDoubleLE(0)}`);
});

test('encodeKeyedDict round-trips every keyed-dict blob byte-for-byte', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip('fixture missing'); return; }
  // Includes the nested audio dicts (TracksBA holds a BYTES inner BtAudioTrack dict).
  for (const tag of ['Geometry', 'Time', 'VideoMetadata', 'Proxy', 'TracksBA', 'VirtualAudioTrackBA']) {
    for (const hex of await grabAll(tag)) {
      const re = encodeKeyedDict(decodeKeyedDict(hex)).toString('hex');
      assert.strictEqual(re, hex, `${tag} must round-trip exactly`);
    }
  }
});

test('readAudioTracks decodes BtAudioInfo config from TracksBA', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip('fixture missing'); return; }
  const tracks = readAudioTracks((await grabAll('TracksBA'))[0]);
  assert.strictEqual(tracks.length, 1);
  const tr = tracks[0];
  assert.strictEqual(tr.sampleRate, 44100);
  assert.strictEqual(tr.numChannels, 2);
  assert.strictEqual(tr.codecName, 'AAC');
  // Duration is in audio samples: 6733824 / 44100 == 152.69 s (the clip length).
  assert.strictEqual(Math.round(Number(tr.duration) / tr.sampleRate), 153);
});

test('setKeyedValue edits a value and re-encodes', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip('fixture missing'); return; }
  const hex = (await grabAll('Time'))[0];
  const edited = setKeyedValue(hex, 'NumFrames', 1234);
  assert.strictEqual(getKeyedValue(edited, 'NumFrames'), 1234);
  assert.strictEqual(getKeyedValue(edited, 'StartFrame'), 0, 'other keys untouched');
});

test('readKeyedDict back-compat returns [{key,value}]', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip('fixture missing'); return; }
  const keys = readKeyedDict((await grabAll('Time'))[0]).map((e) => e.key);
  assert.ok(keys.includes('NumFrames'));
});
