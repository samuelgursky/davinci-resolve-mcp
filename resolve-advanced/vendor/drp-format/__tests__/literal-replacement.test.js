// A string passed as the replacement to String.prototype.replace expands `$&`,
// `$'`, `` $` `` and `$$`, so a name or caption carrying them is rewritten on its
// way into the XML (#332: `R2 $& $'` as a timeline name made MpFolder.xml
// unparseable; `Spot $$ 30s` came out as `Spot $ 30s`). Interpolated
// replacements are therefore passed as functions, which insert their result
// literally. This file guards that rule and checks the writers that carry user
// text.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const JSZip = require('jszip');
const { escapeXml } = require('../xml-builder');
const { createEmptyProject } = require('../author-project');
const { placeSubtitles } = require('../place-subtitles');
const { placeGenerator } = require('../place-generator');
const { placeFusionTitle } = require('../place-fusion-title');
const { splitClip, trimClip, trimClipHead } = require('../splice-clips');
const { placeTransition } = require('../place-transition');

const ROOT = path.resolve(__dirname, '..', '..', '..');
const TRICKY = "Spot $$ 30s $& $' $` end";

function sourceFiles(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === '__tests__') continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(full));
    else if (/\.(m?js)$/.test(entry.name)) out.push(full);
  }
  return out;
}

// `.replace(<string or regex literal>, `...${...}...`)` on one line. A template
// that uses a $-backreference ($1, $&, $<name>) needs the string form and is allowed.
const STRING_REPLACEMENT = /\.replace\(\s*(?:'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|\/(?:[^/\\\n]|\\.)+\/[a-z]*)\s*,\s*`((?:[^`\\]|\\.)*)`/g;
const BACKREF = /\$(?:[0-9&'`]|<[A-Za-z_]\w*>)/;

function offenders(text) {
  const found = [];
  for (const m of text.matchAll(STRING_REPLACEMENT)) {
    const template = m[1];
    if (!template.includes('${')) continue;
    if (BACKREF.test(template.replace(/\$\{[^}]*\}/g, ''))) continue;
    found.push(m[0].slice(0, 120));
  }
  return found;
}

test('no interpolated replace() replacement is passed as a string', () => {
  const files = [...sourceFiles(path.join(ROOT, 'server')), ...sourceFiles(path.join(ROOT, 'vendor'))];
  assert.ok(files.length > 50, `scanned ${files.length} files`);
  const bad = [];
  for (const file of files) {
    for (const hit of offenders(fs.readFileSync(file, 'utf8'))) bad.push(`${path.relative(ROOT, file)}: ${hit}`);
  }
  assert.deepStrictEqual(bad, [], 'pass the replacement as () => `...` so $-sequences stay literal');
});

test('the guard catches the #332 form and allows the safe ones', () => {
  assert.strictEqual(offenders("x.replace('</MediaVec>', `${el}\\n</MediaVec>`)").length, 1);
  assert.strictEqual(offenders('x.replace(/<Name>[^<]*<\\/Name>/, `<Name>${n}</Name>`)').length, 1);
  assert.strictEqual(offenders("x.replace('</MediaVec>', () => `${el}\\n</MediaVec>`)").length, 0);
  assert.strictEqual(offenders('x.replace(/(<a>)<b\\/>/, `$1<b>${hex}</b>`)').length, 0);
  assert.strictEqual(offenders("x.replace('a', 'b')").length, 0);
});

async function sequenceXml(buffer) {
  const zip = await JSZip.loadAsync(buffer);
  const parts = [];
  for (const name of Object.keys(zip.files)) {
    if (/SeqContainer\/[^/]+\.xml$|SeqContainer\d*\.xml$/.test(name)) parts.push(await zip.files[name].async('string'));
  }
  return parts.join('\n');
}

test('placeSubtitles keeps $-sequences in caption text', async () => {
  const { buffer, startFrame } = await createEmptyProject({ timelineName: 'Subs' });
  const res = await placeSubtitles(buffer, { subtitles: [{ startFrame, durationFrames: 48, text: TRICKY }] });
  assert.ok((await sequenceXml(res.buffer)).includes(`<Name>${escapeXml(TRICKY)}</Name>`));
});

test('placeGenerator keeps $-sequences in the generator name', async () => {
  const { buffer, startFrame } = await createEmptyProject({ timelineName: 'Gen' });
  const res = await placeGenerator(buffer, { generatorName: TRICKY, trackIndex: 2, startFrame, durationFrames: 24 });
  const xml = await sequenceXml(res.buffer);
  assert.ok(xml.includes(`<PrettyType>${escapeXml(TRICKY)}</PrettyType>`));
  assert.ok(xml.includes(`<Name>${escapeXml(TRICKY)}</Name>`));
});

test('placeFusionTitle keeps $-sequences in the clip name', async () => {
  const { buffer, startFrame } = await createEmptyProject({ timelineName: 'Title' });
  const res = await placeFusionTitle(buffer, { trackIndex: 2, startFrame, durationFrames: 24, name: TRICKY });
  assert.ok((await sequenceXml(res.buffer)).includes(`<Name>${escapeXml(TRICKY)}</Name>`));
});

// A second clip on a track goes through the populated-track branch of
// setItemsInner, and splitClip/placeTransition rewrite the clip in place. A
// string replacement there copies the matched <Items> block ($&) and the text
// around it ($`, $') into the track, duplicating clips.
const nameCount = (xml) => xml.split(`<Name>${escapeXml(TRICKY)}</Name>`).length - 1;

async function titledTrack() {
  const { buffer, startFrame } = await createEmptyProject({ timelineName: 'Track' });
  const first = await placeFusionTitle(buffer, { trackIndex: 2, startFrame, durationFrames: 24, name: TRICKY });
  const second = await placeFusionTitle(first.buffer, { trackIndex: 2, startFrame: startFrame + 24, durationFrames: 24, name: 'Next' });
  return { buffer: second.buffer, startFrame };
}

test('a clip added to a populated track leaves the clip already there intact', async () => {
  const xml = await sequenceXml((await titledTrack()).buffer);
  assert.strictEqual(nameCount(xml), 1);
  assert.strictEqual(xml.split('<Name>Next</Name>').length - 1, 1);
});

test('splitClip, trimClip, trimClipHead and placeTransition keep $-sequences in the clip name', async () => {
  const { buffer, startFrame } = await titledTrack();
  for (const trim of [trimClip, trimClipHead]) {
    const res = await trim(buffer, { track: 2, clipIndex: 0, newDuration: 12, frames: 6, ripple: true });
    assert.strictEqual(nameCount(await sequenceXml(res.buffer)), 1);
  }
  const split = await splitClip(buffer, { track: 2, at: startFrame + 12 });
  assert.strictEqual(nameCount(await sequenceXml(split.buffer)), 2);
  const res = await placeTransition(buffer, { track: 2, atFrame: startFrame + 24 });
  assert.strictEqual(nameCount(await sequenceXml(res.buffer)), 1);
});
