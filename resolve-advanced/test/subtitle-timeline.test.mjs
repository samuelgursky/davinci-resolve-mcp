import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import JSZip from 'jszip';
import { XMLValidator } from 'fast-xml-parser';
import { editSubtitleTimeline, editCaptionTimeline, inspectCaptionTimeline } from '../server/subtitle-timeline.mjs';

const native = await fs.readFile(new URL('../assets/word-highlight-track.xml', import.meta.url), 'utf8');
const section = /<FusionCompHolderItems>[\s\S]*?<\/FusionCompHolderItems>/.exec(native)[0];
async function fixture(dir, name, withPreset = true) {
  const zip = new JSZip();
  const track = `<Element><Sm2TiTrack DbId="11111111-1111-1111-1111-111111111111"><Sequence>keep-sequence-reference</Sequence><Items><caption FieldsBlob="keep-word-timing"/></Items>${withPreset ? section : '<FusionCompHolderItems/>'}</Sm2TiTrack></Element>`;
  const xml = `<Sm2SequenceContainer DbId="22222222-2222-2222-2222-222222222222"><VideoTrackVec>keep-video</VideoTrackVec><SubtitleTrackVec>${track}${track}</SubtitleTrackVec><AudioTrackVec>keep-audio</AudioTrackVec></Sm2SequenceContainer>`;
  zip.file('project.xml', '<project>keep-cross-entry-references</project>');
  zip.file('MediaPool/Master/MpFolder.xml', '<pool>keep-media</pool>');
  zip.file('SeqContainer/22222222-2222-2222-2222-222222222222.xml', xml);
  const file = path.join(dir, name);
  await fs.writeFile(file, await zip.generateAsync({ type: 'nodebuffer' }));
  return file;
}
test('edit only selected preset; preserve other tracks, caption bytes and cross-entry references', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'subtitle-drt-test-'));
  try {
    const source = await fixture(dir, 'source.drt'), output = path.join(dir, 'out.drt');
    const original = await fs.readFile(source);
    const result = await editSubtitleTimeline({ source, output, track: 2, inputs: { textRed: 0, size: 0.07 } });
    assert.equal(result.after.textRed, 0);
    assert.equal(result.after.size, 0.07);
    assert.deepEqual(await fs.readFile(source), original);
    const before = await JSZip.loadAsync(original), after = await JSZip.loadAsync(await fs.readFile(output));
    assert.deepEqual(Object.keys(after.files), Object.keys(before.files));
    for (const file of ['project.xml', 'MediaPool/Master/MpFolder.xml']) {
      assert.equal(await before.file(file).async('string'), await after.file(file).async('string'));
    }
    const entry = Object.keys(before.files).find(n => n.startsWith('SeqContainer/') && n.endsWith('.xml'));
    const a = await before.file(entry).async('string'), b = await after.file(entry).async('string');
    const strip = s => s.replace(/<FusionCompHolderItems>[\s\S]*?<\/FusionCompHolderItems>/g, '<holder/>');
    assert.equal(strip(a), strip(b));
    assert.equal(b.match(/<FusionCompHolderItems>[\s\S]*?<\/FusionCompHolderItems>/g)[0], section);
    await assert.rejects(editSubtitleTimeline({ source, output, inputs: { textRed: 0 } }), /EEXIST/);
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});
test('apply bundled Word Highlight to a track without a preset', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'subtitle-drt-test-'));
  try {
    const source = await fixture(dir, 'source.drt', false), output = path.join(dir, 'out.drt');
    const result = await editSubtitleTimeline({ source, output, preset: 'Word Highlight', inputs: { highlightBlue: 1 } });
    assert.equal(result.after.highlightBlue, 1);
    assert.equal(result.after.textRed, 1);
    await assert.rejects(editSubtitleTimeline({ source, output: path.join(dir, 'bad.drt'), inputs: { size: 2 } }));
    await assert.rejects(editSubtitleTimeline({ source, output: path.join(dir, 'bad.drt'), inputs: { unknown: 1 } }));
    await assert.rejects(editSubtitleTimeline({ source, output: path.join(dir, 'bad.drt'), inputs: { size: 0.1 } }), /No animation preset/);
    assert.equal(await fs.stat(path.join(dir, 'bad.drt')).catch(() => null), null);
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});
test('apply native Lollipop, edit common controls, refuse effect-specific unmapped controls', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'subtitle-drt-test-'));
  try {
    const source = await fixture(dir, 'source.drt'), output = path.join(dir, 'lollipop.drt');
    const result = await editSubtitleTimeline({ source, output, preset: 'Lollipop' });
    assert.equal(result.templateId, 'Templates/Edit/Titles/Subtitles/Animated/Lollipop');
    assert.equal(result.after.font, 'Open Sans');
    const edited = await editSubtitleTimeline({ source, output: path.join(dir, 'edited.drt'), preset: 'Lollipop', inputs: { size: 0.07, textRed: 0.2 } });
    assert.equal(edited.after.size, 0.07);
    assert.equal(edited.after.textRed, 0.2);
    await assert.rejects(editSubtitleTimeline({ source, output: path.join(dir, 'bad.drt'), preset: 'Lollipop', inputs: { highlightBlue: 0.2 } }), /unsupported preset input/);
    assert.equal(await fs.stat(path.join(dir, 'bad.drt')).catch(() => null), null);
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});

test('capture an installed subtitle via native title DRT without changing caption bytes', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'subtitle-native-title-'));
  try {
    const source = await fixture(dir, 'source.drt', false);
    const native = await fs.readFile(new URL('../assets/lollipop-track.xml', import.meta.url), 'utf8');
    const composition = /<CompositionBA>[\s\S]*?<\/CompositionBA>/.exec(native)[0];
    const zip = new JSZip();
    zip.file('project.xml', '<project/>');
    zip.file('SeqContainer/native.xml', `<VideoTrackVec>${composition}</VideoTrackVec>`);
    const reference = path.join(dir, 'title.drt');
    await fs.writeFile(reference, await zip.generateAsync({type:'nodebuffer'}));
    const result = await editSubtitleTimeline({source, output:path.join(dir,'out.drt'), title_reference:reference,
      template_id:'Templates/Edit/Titles/Subtitles/Animated/Lollipop', inputs:{position:[0.5,0.3]}});
    assert.equal(result.templateId, 'Templates/Edit/Titles/Subtitles/Animated/Lollipop');
    assert.deepEqual(result.after.position,[0.5,0.3]);
    await assert.rejects(editSubtitleTimeline({source, output:path.join(dir,'bad.drt'), title_reference:reference,
      template_id:'Templates/Edit/Titles/Subtitles/Animated/Rotate'}),/exactly one matching/);
    await assert.rejects(editSubtitleTimeline({source, output:path.join(dir,'bad.drt'), title_reference:reference,
      template_id:'Templates/Edit/Titles/Statement'}),/subtitle template/);
  } finally { await fs.rm(dir,{recursive:true,force:true}); }
});

test('Word Highlight lists and sets its drop shadow; per-word scale is refused', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'subtitle-shadow-'));
  try {
    const source = await fixture(dir, 'source.drt'), output = path.join(dir, 'out.drt');
    const result = await editSubtitleTimeline({
      source, output, inputs: { shadowEnabled: 1, shadowBlue: 0.25, verticalAlign: 3 },
    });
    assert.equal(result.after.shadowEnabled, 1);
    assert.equal(result.after.shadowBlue, 0.25);
    assert.equal(result.after.verticalAlign, 3);
    assert.ok(result.editableInputs.includes('shadowOffset'));
    assert.ok(!result.editableInputs.includes('highlightScale'));
    await assert.rejects(
      editSubtitleTimeline({ source, output: path.join(dir, 'scale.drt'), inputs: { highlightScale: 1.1 } }),
      /highlightScale/,
    );
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});

const captionBlobs = ['00000002000000748128b52ffd206a5103000a5568007204204f682c72072074686174277372052073756368720220617205206375746578ec980d7894990d78ba990d78c6990d78d2990d800194990d8001ba990d8001c6990d8001d2990d8001de990da801b6cc06121100000024789c6366606420040000b20005',
  '00000002000000738128b52ffd20694903000a5468007204206361747205206974277372022061720420646f6772072064756d6d792e78de990d78fa990d78ea9a0d78ec9a0d78809b0d8001fa990d8001ea9a0d8001ec9a0d8001809b0d8001949b0da801efcc06121100000024789c6366606420040000b20005'];
const generator = (id, blob, name, start, duration) => `<Element><Sm2TiGenerator DbId="${id}"><FieldsBlob>${blob}</FieldsBlob><PrettyType>Subtitle</PrettyType><Name>${name}</Name><Start>${start}</Start><Duration>${duration}</Duration><MarkersBA>keep-marker</MarkersBA><In/></Sm2TiGenerator></Element>`;
async function captionFixture(dir, secondStart = 108143) {
  const items = generator('aaaaaaaa-0000-0000-0000-000000000001', captionBlobs[0], " Oh, that's such a cute", 108086, 57)
    + generator('aaaaaaaa-0000-0000-0000-000000000002', captionBlobs[1], ' cat it&apos;s a dog dummy.', secondStart, 91);
  const zip = new JSZip();
  zip.file('project.xml', '<project/>');
  zip.file('MediaPool/Master/MpFolder.xml', '<Sm2Sequence DbId="33333333-3333-3333-3333-333333333333"><FrameRate>0000000000003e400000000000000000</FrameRate></Sm2Sequence>');
  zip.file('SeqContainer/22222222-2222-2222-2222-222222222222.xml', `<Sm2SequenceContainer><SubtitleTrackVec><Element><Sm2TiTrack DbId="11111111-1111-1111-1111-111111111111"><Sequence>33333333-3333-3333-3333-333333333333</Sequence><Items>${items}</Items><FusionCompHolderItems/></Sm2TiTrack></Element></SubtitleTrackVec></Sm2SequenceContainer>`);
  const file = path.join(dir, 'captions.drt');
  await fs.writeFile(file, await zip.generateAsync({ type: 'nodebuffer' }));
  return file;
}
test('replace, add and delete caption text and word timing in an exported DRT', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'subtitle-captions-'));
  try {
    const source = await captionFixture(dir), output = path.join(dir, 'out.drt');
    const before = await inspectCaptionTimeline({ source });
    assert.equal(before.fps, 30);
    assert.deepEqual(before.captions.map((c) => c.text), ["Oh, that's such a cute", "cat it's a dog dummy."]);
    const [first, second] = before.captions;
    const result = await editCaptionTimeline({ source, output,
      replace: [{ id: first.id, text: 'Oh f**k <so> cute', start: 108086, end: 108143, words: [
        { text: 'Oh', start: 108086, end: 108100 }, { text: 'f**k', start: 108100, end: 108120 },
        { text: '<so>', start: 108120, end: 108130 }, { text: 'cute', start: 108130, end: 108143 }] }],
      add: [{ text: 'new one', start: 108300, end: 108330, words: [
        { text: 'new', start: 108300, end: 108310 }, { text: 'one', start: 108310, end: 108330 }] }],
      delete: [second.id] });
    assert.equal(result.added.length, 1);
    const after = await inspectCaptionTimeline({ source: output });
    const strip = (c) => ({ text: c.text, start: c.start, end: c.end, words: c.words });
    assert.deepEqual(after.captions.map(strip), result.captions.map(strip));
    assert.deepEqual(after.captions.map((c) => c.text), ['Oh f**k <so> cute', 'new one']);
    assert.equal(first.id, '108086', 'live caption ids are start frames, stable across exports');
    assert.equal(after.captions[0].id, '108086');
    const xml = await (await JSZip.loadAsync(await fs.readFile(output))).file('SeqContainer/22222222-2222-2222-2222-222222222222.xml').async('string');
    assert.match(xml, /aaaaaaaa-0000-0000-0000-000000000001/);
    assert.doesNotMatch(xml, /aaaaaaaa-0000-0000-0000-000000000002/);
    assert.equal(xml.match(/Sm2TiGenerator DbId/g).length, 2);
    assert.match(xml, /<Name> Oh f\*\*k &lt;so&gt; cute<\/Name>/);
    assert.equal(xml.match(/keep-marker/g).length, 1, 'fresh captions must not copy the template markers');
    await assert.rejects(editCaptionTimeline({ source, output: path.join(dir, 'gap.drt'), replace: [{ id: first.id, text: 'a b',
      start: 108086, end: 108143, words: [{ text: 'a', start: 108086, end: 108090 }, { text: 'b', start: 108100, end: 108143 }] }] }), /word_gap/);
    await assert.rejects(editCaptionTimeline({ source, output: path.join(dir, 'over.drt'), add: [{ text: 'x', start: 108100, end: 108110,
      words: [{ text: 'x', start: 108100, end: 108110 }] }] }), /overlapping/);
    await assert.rejects(editCaptionTimeline({ source, output: path.join(dir, 'id.drt'), delete: ['missing'] }), /not on the selected track/);
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});


test('caption writes refuse ambiguous start-frame IDs before removing any item', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'subtitle-duplicate-start-'));
  try {
    const source = await captionFixture(dir, 108086), original = await fs.readFile(source);
    const before = await inspectCaptionTimeline({ source });
    assert.deepEqual(before.captions.map((c) => c.id), ['108086', '108086']);
    const caption = { text: 'new', start: 108300, end: 108330,
      words: [{ text: 'new', start: 108300, end: 108330 }] };
    for (const [name, edits] of [
      ['delete', { delete: ['108086'] }],
      ['replace', { replace: [{ id: '108086', ...caption }] }],
      ['add', { add: [caption] }],
    ]) {
      const output = path.join(dir, `${name}.drt`);
      await assert.rejects(editCaptionTimeline({ source, output, ...edits }), /duplicate caption ids/);
      assert.equal(await fs.stat(output).catch(() => null), null);
      assert.deepEqual(await fs.readFile(source), original);
    }
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});


test('caption text inserts dollar sequences literally and escapes XML on replace and add', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'subtitle-literal-text-'));
  try {
    const source = await captionFixture(dir), output = path.join(dir, 'literal.drt');
    const original = await fs.readFile(source);
    const tokens = ['$&', '$`', "$'", '$$', '$1', '<tag>', '&amp;'];
    const text = tokens.join(' ');
    const cue = (start, end) => ({ text, start, end, words: tokens.map((word, i) => ({
      text: word, start: start + Math.floor((end - start) * i / tokens.length),
      end: start + Math.floor((end - start) * (i + 1) / tokens.length),
    })) });
    await editCaptionTimeline({ source, output,
      replace: [{ id: '108086', ...cue(108086, 108143) }], add: [cue(108300, 108360)] });
    const zip = await JSZip.loadAsync(await fs.readFile(output));
    const xml = await zip.file('SeqContainer/22222222-2222-2222-2222-222222222222.xml').async('string');
    assert.equal(XMLValidator.validate(xml), true);
    assert.equal(xml.split("<Name> $&amp; $` $' $$ $1 &lt;tag&gt; &amp;amp;</Name>").length - 1, 2);
    const after = await inspectCaptionTimeline({ source: output });
    assert.equal(after.captions[0].text, text);
    assert.equal(after.captions[2].text, text);
    assert.deepEqual(await fs.readFile(source), original);
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});


test('added and moved captions return start-frame IDs usable by subsequent edits', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'subtitle-reusable-ids-'));
  try {
    const source = await captionFixture(dir), output = path.join(dir, 'revised.drt');
    const cue = (text, start, end) => ({ text, start, end, words: [{ text, start, end }] });
    const result = await editCaptionTimeline({ source, output,
      replace: [{ id: '108086', ...cue('moved', 108250, 108280) }],
      add: [cue('added', 108300, 108330)] });
    assert.deepEqual(result.added, ['108300']);
    const after = await inspectCaptionTimeline({ source: output });
    assert.deepEqual(result.captions, after.captions);
    assert.deepEqual(result.captions.map((c) => c.id), ['108143', '108250', '108300']);
    const moved = result.captions.find((c) => c.text === 'moved');
    const nextOutput = path.join(dir, 'next.drt');
    const next = await editCaptionTimeline({ source: output, output: nextOutput,
      replace: [{ id: moved.id, ...cue('updated', 108250, 108280) }],
      templateCaptionId: result.added[0], add: [cue('templated', 108400, 108430)], delete: result.added });
    const back = await inspectCaptionTimeline({ source: nextOutput });
    assert.deepEqual(next.captions, back.captions);
    assert.deepEqual(back.captions.map((c) => c.text), ["cat it's a dog dummy.", 'updated', 'templated']);
    assert.deepEqual(next.added, ['108400']);
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});
