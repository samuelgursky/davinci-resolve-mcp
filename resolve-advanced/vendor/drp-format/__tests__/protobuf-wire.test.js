const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const JSZip = require('jszip');
const {
  decodeProtobuf, encodeProtobuf, decodeEffectFilters, encodeEffectFilters,
} = require('../protobuf-wire');
const { decodeKeyedDict, encodeKeyedDict, classifyBlob } = require('../keyed-dict');

const FIXTURE = 'docs/design/drp-drx-drt-closeout-harness/fixtures/canary-resolve21.drp';
const TRANS = require('path').join(__dirname, '..', 'templates', 'transition-cross-dissolve.xml');

async function grabAll(path, tag) {
  let xmls = [];
  if (path.endsWith('.drp')) {
    const zip = await JSZip.loadAsync(fs.readFileSync(path));
    for (const n of Object.keys(zip.files)) {
      if (n.endsWith('.xml')) xmls.push(await zip.files[n].async('string'));
    }
  } else {
    xmls = [fs.readFileSync(path, 'utf8')];
  }
  const out = [];
  for (const x of xmls) {
    const re = new RegExp(`<${tag}>([0-9a-f]+)</${tag}>`, 'g');
    let m;
    while ((m = re.exec(x))) out.push(m[1]);
  }
  return out;
}

test('decodeProtobuf reads Radiometry color-science fields + round-trips', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip('fixture missing'); return; }
  const hex = (await grabAll(FIXTURE, 'Radiometry'))[0];
  const fields = decodeProtobuf(hex);
  assert.ok(fields.length >= 5, 'several varint fields');
  assert.ok(fields.every((f) => f.wire === 0), 'Radiometry is all varints');
  assert.strictEqual(encodeProtobuf(fields).toString('hex'), hex, 'round-trip exact');
});

test('decodeEffectFilters reads the transition effect envelope + round-trips', async () => {
  const hex = (await grabAll(TRANS, 'EffectFiltersBA'))[0];
  const dec = decodeEffectFilters(hex);
  assert.strictEqual(dec.hdr, 2);
  assert.ok(dec.fields.length > 0);
  assert.strictEqual(encodeEffectFilters(dec).toString('hex'), hex, 'envelope round-trip exact');
});

test('classifyBlob splits FieldsBlob into keyed-dict / protobuf / zstd; keyed-dicts round-trip', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip('fixture missing'); return; }
  const all = await grabAll(FIXTURE, 'FieldsBlob');
  const seen = new Set();
  for (const hex of all) {
    const cls = classifyBlob(hex);
    seen.add(cls);
    if (cls === 'keyed-dict') {
      // Every keyed-dict FieldsBlob (element state + UI view-options) round-trips exactly.
      assert.strictEqual(encodeKeyedDict(decodeKeyedDict(hex)).toString('hex'), hex);
    }
    // 'zstd' = compressed internal state, carried verbatim (no built-in zstd in Node).
  }
  assert.ok(seen.has('keyed-dict'), 'has keyed-dict FieldsBlobs');
  assert.ok(seen.has('zstd'), 'has zstd internal-state FieldsBlobs');
});
