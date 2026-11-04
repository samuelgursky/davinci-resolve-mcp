// A string passed as the replacement to String.prototype.replace expands `$&`,
// `$'`, `` $` `` and `$$`, so a name or caption carrying them is rewritten on its
// way into the XML (#332: `R2 $& $'` as a timeline name made MpFolder.xml
// unparseable; `Spot $$ 30s` came out as `Spot $ 30s`). Interpolated
// replacements are therefore passed as functions, which insert their result
// literally. This file guards that rule for every replace() call (#333 found
// forms the first guard missed: a variable, a call or a conditional as the
// replacement) and checks the writers that carry user text.

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
  if (!fs.existsSync(dir)) return out;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === '__tests__') continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourceFiles(full));
    else if (/\.(m?js)$/.test(entry.name)) out.push(full);
  }
  return out;
}

// A small scanner, enough to split each replace() call into its arguments: it
// skips strings, templates, regex literals and comments, and matches brackets.
const REGEX_CAN_FOLLOW = '(,=:[!&|?{};+-*%<>~^';
function prevSignificant(s, i) {
  let j = i - 1;
  while (j >= 0 && /\s/.test(s[j])) j -= 1;
  return j >= 0 ? s[j] : '';
}
function skipString(s, i) {
  const q = s[i];
  i += 1;
  while (s[i] !== q) i += s[i] === '\\' ? 2 : 1;
  return i + 1;
}
function skipTemplate(s, i) {
  i += 1;
  while (s[i] !== '`') {
    if (s[i] === '\\') i += 2;
    else if (s.startsWith('${', i)) i = skipBracketed(s, i + 1);
    else i += 1;
  }
  return i + 1;
}
function skipRegex(s, i) {
  let inClass = false;
  for (i += 1; ; i += 1) {
    const c = s[i];
    if (c === '\\') { i += 1; continue; }
    if (c === '\n' || c === undefined) return -1;
    if (c === '[') inClass = true;
    else if (c === ']') inClass = false;
    else if (c === '/' && !inClass) break;
  }
  i += 1;
  while (/[a-z]/.test(s[i] || '')) i += 1;
  return i;
}
// Skip a string, template, comment or regex literal at i; return the index after
// it, or -1 when none starts there.
function skipAtom(s, i) {
  const c = s[i];
  if (c === "'" || c === '"') return skipString(s, i);
  if (c === '`') return skipTemplate(s, i);
  if (c === '/' && s[i + 1] === '/') return s.indexOf('\n', i);
  if (c === '/' && s[i + 1] === '*') return s.indexOf('*/', i) + 2;
  if (c === '/' && REGEX_CAN_FOLLOW.includes(prevSignificant(s, i))) return skipRegex(s, i);
  return -1;
}
function skipBracketed(s, i) {
  let depth = 0;
  while (i < s.length) {
    const next = skipAtom(s, i);
    if (next > i) { i = next; continue; }
    if ('([{'.includes(s[i])) depth += 1;
    else if (')]}'.includes(s[i]) && --depth === 0) return i + 1;
    i += 1;
  }
  return s.length;
}
function callArguments(s, open) {
  const close = skipBracketed(s, open) - 1;
  const args = [];
  let start = open + 1;
  for (let i = start; i < close; ) {
    const next = skipAtom(s, i);
    if (next > i) { i = next; continue; }
    if ('([{'.includes(s[i])) { i = skipBracketed(s, i); continue; }
    if (s[i] === ',') { args.push(s.slice(start, i).trim()); start = i + 1; }
    i += 1;
  }
  args.push(s.slice(start, close).trim());
  return args;
}

const BACKREF = /\$(?:[0-9&'`]|<[A-Za-z_]\w*>)/;
// Replacements that are rules a caller writes, where $1 and $& are the feature.
const INTENDED = new Set([
  'server/editorial.mjs: a.replace',
  "server/media-ops.mjs: rule.replace ?? ''",
]);

// The replacement of every .replace()/.replaceAll() call must be a function, or a
// literal with no $ in it. A literal whose $-sequences are backreferences ($1,
// $&) is deliberate and allowed; anything else (a variable, a call, an
// interpolated template) may carry a $ and is reported.
function offenders(text, file = '') {
  const found = [];
  for (const m of text.matchAll(/\.(?:replace|replaceAll)\(/g)) {
    const args = callArguments(text, m.index + m[0].length - 1);
    if (args.length < 2) continue;
    const rep = args[1];
    if (/^(async\s+)?(\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>|^function\b/.test(rep)) continue;
    const literal = /^(['"`])[\s\S]*\1$/.test(rep);
    if (literal && !rep.includes('$')) continue;
    if (literal && BACKREF.test(rep.replace(/\$\{[^}]*\}/g, ''))) continue;
    if (INTENDED.has(`${file}: ${rep}`)) continue;
    found.push(`${file}: .replace(${args[0].slice(0, 40)}, ${rep.slice(0, 60)})`);
  }
  return found;
}

test('every replace() replacement is a function or a $-free literal', () => {
  const dirs = ['server', 'vendor', 'bin', '../scripts', '../bin'].map((d) => path.join(ROOT, d));
  const files = dirs.flatMap(sourceFiles);
  assert.ok(files.length > 50, `scanned ${files.length} files`);
  const bad = files.flatMap((file) => offenders(fs.readFileSync(file, 'utf8'), path.relative(ROOT, file).split(path.sep).join('/')));
  assert.deepStrictEqual(bad, [], 'pass the replacement as () => ... so $-sequences in it stay literal');
});

test('the guard catches each string form and allows the safe ones', () => {
  const caught = [
    "x.replace('</MediaVec>', `${el}\\n</MediaVec>`)", // #332
    'x.replace(/<Name>[^<]*<\\/Name>/, `<Name>${n}</Name>`)',
    'out.replace(c, nc)', // #333
    'items.replace(target, setClipDuration(target, d))',
    'x.replace(/<Items>[\\s\\S]*?<\\/Items>/, body ? `<Items>${body}</Items>` : "<Items/>")',
    'x.replaceAll(a, b)',
  ];
  for (const code of caught) assert.strictEqual(offenders(code).length, 1, code);
  const allowed = [
    "x.replace('</MediaVec>', () => `${el}\\n</MediaVec>`)",
    'x.replace(/(<a>)<b\\/>/, `$1<b>${hex}</b>`)',
    "x.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')",
    "x.replace('a', 'b')",
    'x.replace(re, (m, g) => g.toUpperCase())',
    "x.replace(re, function (m) { return m + ', '; })",
  ];
  for (const code of allowed) assert.strictEqual(offenders(code).length, 0, code);
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
