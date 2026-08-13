/**
 * compound-nav — walking into compound clips and nested timelines.
 *
 * Fixture: compound-nav-r21.drp, exported from DaVinci Resolve Studio 21.0.4.5
 * (DbPrjVer 17). It holds, deliberately, one of each interesting case:
 *   CMP_MEDIA   compound wrapping a media clip
 *   CMP_TITLE   compound wrapping a Text+ (text set to "INSIDE COMPOUND")
 *   ZZ_CMP_TL   the outer timeline
 *   ZZ_INNER_TL a plain nested timeline holding a Text+
 *
 * The compound cases are the point: the scripting API cannot reach into them at
 * all. MediaPoolItem.GetTimeline() returns None for Type='Compound' (measured on
 * 21.0.4.5) while working for Type='Timeline', and a compounded Text+ reports
 * GetFusionCompCount()==0. On disk there is no such asymmetry.
 */

const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');

const nav = require('../compound-nav');

const FIXTURE = path.join(__dirname, 'fixtures', 'compound-nav-r21.drp');
const hasFixture = fs.existsSync(FIXTURE);
const maybe = hasFixture ? test : test.skip;

maybe('listNestedSequences finds both compounds and both timelines', async () => {
  const list = await nav.listNestedSequences(FIXTURE);
  const byName = Object.fromEntries(list.map((e) => [e.name, e]));

  assert.equal(list.length, 4);
  assert.equal(byName.CMP_MEDIA.kind, 'compound');
  assert.equal(byName.CMP_TITLE.kind, 'compound');
  assert.equal(byName.ZZ_CMP_TL.kind, 'timeline');
  assert.equal(byName.ZZ_INNER_TL.kind, 'timeline');
});

maybe('every nested sequence resolves to its own SeqContainer', async () => {
  const list = await nav.listNestedSequences(FIXTURE);
  for (const e of list) {
    assert.ok(e.sequenceDbId, `${e.name} has no Sm2Sequence DbId`);
    assert.ok(e.entry, `${e.name} did not resolve to a SeqContainer`);
  }
  // The join is one-to-one: no two media pool items share a container.
  const entries = list.map((e) => e.entry);
  assert.equal(new Set(entries).size, entries.length);
});

maybe('readNestedSequence returns the items inside a compound', async () => {
  const media = await nav.readNestedSequence(FIXTURE, { name: 'CMP_MEDIA' });
  assert.equal(media.kind, 'compound');
  assert.equal(media.tracks.length, 1);
  assert.equal(media.tracks[0].items.length, 1);
  assert.equal(media.tracks[0].items[0].name, 'retime_src.mp4');
  assert.equal(media.tracks[0].items[0].duration, 48);
});

maybe('compound contents are rebased to 0; a nested timeline keeps timeline TC', async () => {
  const cmp = await nav.readNestedSequence(FIXTURE, { name: 'CMP_TITLE' });
  const tl = await nav.readNestedSequence(FIXTURE, { name: 'ZZ_INNER_TL' });
  assert.equal(cmp.tracks[0].items[0].start, 0);
  assert.equal(tl.tracks[0].items[0].start, 86400);
});

maybe('readNestedTitles decodes text the scripting API cannot reach', async () => {
  const titles = await nav.readNestedTitles(FIXTURE, { name: 'CMP_TITLE' });
  assert.equal(titles.length, 1);
  assert.equal(titles[0].text, 'INSIDE COMPOUND');
  assert.equal(titles[0].font, 'Open Sans');
});

maybe('setNestedTitleText rewrites the text inside a compound', async () => {
  const res = await nav.setNestedTitleText(FIXTURE, {
    name: 'CMP_TITLE', text: 'REWRITTEN',
  });
  assert.equal(res.before.text, 'INSIDE COMPOUND');
  assert.equal(res.after.text, 'REWRITTEN');

  // Re-read from the produced buffer, not from the in-memory result.
  const again = await nav.readNestedTitles(res.buffer, { name: 'CMP_TITLE' });
  assert.equal(again[0].text, 'REWRITTEN');
  // Untouched inputs survive.
  assert.equal(again[0].font, 'Open Sans');
  assert.equal(again[0].size, 0.09);
});

maybe('setNestedTitleText leaves the other compound alone', async () => {
  const res = await nav.setNestedTitleText(FIXTURE, {
    name: 'CMP_TITLE', text: 'ONLY THIS ONE',
  });
  const other = await nav.readNestedSequence(res.buffer, { name: 'CMP_MEDIA' });
  assert.equal(other.tracks[0].items[0].name, 'retime_src.mp4');
  assert.equal(other.tracks[0].items[0].duration, 48);
});

maybe('unknown name throws rather than silently doing nothing', async () => {
  await assert.rejects(
    () => nav.readNestedSequence(FIXTURE, { name: 'NOPE' }),
    /no compound or timeline named/,
  );
});

maybe('a double quote in the text is refused (it would break the Lua blob)', async () => {
  await assert.rejects(
    () => nav.setNestedTitleText(FIXTURE, { name: 'CMP_TITLE', text: 'say "hi"' }),
    /must not contain double quotes/,
  );
});

maybe('titleIndex out of range names the count it saw', async () => {
  await assert.rejects(
    () => nav.setNestedTitleText(FIXTURE, { name: 'CMP_TITLE', text: 'x', titleIndex: 7 }),
    /has 1 title\(s\); no index 7/,
  );
});
