// Unit: read/replace a Fusion Title's on-screen text in a CompositionBA blob.
// Encoding verified by live Resolve 21 import + re-export (the re-export reads back the
// edited StyledText) — see resolve21-schema-reconciliation.md.

const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');
const { decodeTitleText, setTitleText } = require('../composition-text');
const { placeFusionTitle } = require('../place-fusion-title');
const { parseDRT } = require('../../drt-format');

const TEMPLATE = fs.readFileSync(path.join(__dirname, '..', 'templates', 'fusion-title.xml'), 'utf8');
const TEMPLATE_BA = TEMPLATE.match(/<CompositionBA>([0-9a-fA-F]*)<\/CompositionBA>/)[1];
const FIXTURE = path.resolve(
  __dirname,
  '../../../docs/design/drp-drx-drt-closeout-harness/fixtures/canary-resolve21.drp',
);

test('decodeTitleText reads the bundled template text', () => {
  assert.strictEqual(decodeTitleText(TEMPLATE_BA), 'Custom Title');
});

test('setTitleText round-trips through decodeTitleText', () => {
  const enc = setTitleText(TEMPLATE_BA, 'SAMPLE TITLE');
  assert.strictEqual(decodeTitleText(enc), 'SAMPLE TITLE');
  // idempotent re-edit
  assert.strictEqual(decodeTitleText(setTitleText(enc, 'Second Edit 2')), 'Second Edit 2');
});

test('setTitleText round-trips text with quotes, backslashes, and newlines (Lua escaping)', () => {
  for (const s of ['He said "hi"', 'back\\slash', 'line1\nline2', 'mix: "a"\\b\tc', 'price $5 & up']) {
    const enc = setTitleText(TEMPLATE_BA, s);
    assert.strictEqual(decodeTitleText(enc), s, `round-trip failed for ${JSON.stringify(s)}`);
  }
});

test('placeFusionTitle honors the text option (CompositionBA rewritten in place)', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip(`fixture missing: ${FIXTURE}`); return; }
  const res = await placeFusionTitle(FIXTURE, { trackIndex: 2, startFrame: 1000, text: 'HELLO WORLD' });
  // Re-read the placed clip's CompositionBA from the output zip and confirm the text.
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(res.buffer);
  let found = null;
  for (const name of Object.keys(zip.files)) {
    if (!/SeqContainer\/[^/]+\.xml$|SeqContainer\d*\.xml$/.test(name)) continue;
    const xml = await zip.files[name].async('string');
    for (const tag of xml.match(/<CompositionBA>[0-9a-fA-F]+<\/CompositionBA>/g) || []) {
      const ba = tag.replace(/<\/?CompositionBA>/g, '');
      const txt = decodeTitleText(ba);
      if (txt === 'HELLO WORLD') found = txt;
    }
  }
  assert.strictEqual(found, 'HELLO WORLD', 'placed title carries the requested on-screen text');

  // And it still parses as a clip on V2.
  const parsed = await parseDRT(res.buffer);
  const tl = parsed.timelines.find((t2) => (t2.videoTracks || []).length >= 2 && t2.videoTracks[1].clips?.length === 1);
  assert.ok(tl, 'title present on V2');
});

const { setTitleInputs, decodeTitleInputs } = require('../composition-text');

test('setTitleInputs sets font/style/size/justify and round-trips', () => {
  const enc = setTitleInputs(TEMPLATE_BA, { text: 'STYLED', font: 'Helvetica Neue', style: 'Bold', size: 0.14, hJustify: 0, vJustify: 1 });
  const got = decodeTitleInputs(enc);
  assert.strictEqual(got.text, 'STYLED');
  assert.strictEqual(got.font, 'Helvetica Neue');
  assert.strictEqual(got.style, 'Bold');
  assert.strictEqual(got.size, 0.14);
  assert.strictEqual(got.hJustify, 0);
  assert.strictEqual(got.vJustify, 1);
});

test('decodeTitleInputs reads template defaults', () => {
  const got = decodeTitleInputs(TEMPLATE_BA);
  assert.strictEqual(got.text, 'Custom Title');
  assert.strictEqual(got.font, 'Open Sans');
  assert.strictEqual(typeof got.size, 'number');
});

test('setTitleInputs rejects unknown inputs', () => {
  assert.throws(() => setTitleInputs(TEMPLATE_BA, { bogus: 1 }), /unknown input/);
});

test('setTitleInputs injects + round-trips text color (Red1/Green1/Blue1)', () => {
  const enc = setTitleInputs(TEMPLATE_BA, { text: 'COLORED', color: { r: 0.9, g: 0.1, b: 0.2 } });
  const got = decodeTitleInputs(enc);
  assert.strictEqual(got.text, 'COLORED');
  assert.deepStrictEqual(got.color, { r: 0.9, g: 0.1, b: 0.2 });
  // re-setting replaces in place (no duplicate injection)
  const enc2 = setTitleInputs(enc, { color: { r: 0.3 } });
  assert.strictEqual(decodeTitleInputs(enc2).color.r, 0.3);
});

test('setTitleInputs rejects out-of-range color', () => {
  assert.throws(() => setTitleInputs(TEMPLATE_BA, { color: { r: 2 } }), /0\.\.1/);
});
