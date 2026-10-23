import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import JSZip from 'jszip';
import { editSubtitleTimeline, inspectSubtitleTimeline } from '../server/subtitle-timeline.mjs';

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

test('independent base stroke and opt-in literals survive readback without changing captions', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'subtitle-inputs-'));
  try {
    const source = await fixture(dir, 'source.drt'), output = path.join(dir, 'outlined.drt');
    const before = await inspectSubtitleTimeline({ source });
    assert.equal(before.literalInputs.find(e => e.name === 'StyledText').writable, false);
    assert.equal(before.literalInputs.find(e => e.name === 'Red1').writable, false);
    const result = await editSubtitleTimeline({ source, output,
      inputs: { baseOutlineEnabled: 1, baseOutlineThickness: 0.08,
        baseOutlineRed: 0, baseOutlineGreen: 0, baseOutlineBlue: 0 },
      literal_inputs: { Size: 0.09, Font: 'Helvetica', Center: [0.5, 0.4] } });
    assert.equal(result.after.baseOutlineShape, 1);
    assert.equal(result.after.baseOutlineEnabled, 1);
    assert.equal(result.after.baseOutlineThickness, 0.08);
    assert.equal(result.after.outlineEnabled, before.inputs.outlineEnabled);
    assert.equal(result.after.shadowEnabled, before.inputs.shadowEnabled);
    assert.deepEqual(result.literalAfter, { Size: 0.09, Font: 'Helvetica', Center: [0.5, 0.4] });
    const back = await inspectSubtitleTimeline({ source: output });
    assert.deepEqual(back.inputs, result.after);
    assert.equal(back.literalInputs.find(e => e.name === 'Size').value, 0.09);
    const a = await JSZip.loadAsync(await fs.readFile(source)), b = await JSZip.loadAsync(await fs.readFile(output));
    const entry = Object.keys(a.files).find(n => /^SeqContainer\/.*\.xml$/.test(n));
    const strip = s => s.replace(/<FusionCompHolderItems>[\s\S]*?<\/FusionCompHolderItems>/g, '<holder/>');
    assert.equal(strip(await a.file(entry).async('string')), strip(await b.file(entry).async('string')));
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});

test('literal editing refuses absent, connected, protected, ill-typed and conflicting inputs', async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'subtitle-input-refusals-'));
  try {
    const source = await fixture(dir, 'source.drt');
    const cases = [
      { literal_inputs: { StyledText: 'Replace captions' } },
      { literal_inputs: { highlightScale: 1.1 } },
      { literal_inputs: { Red1: 0.5 } },
      { literal_inputs: { 'Size = Input': 1 } },
      { literal_inputs: { Font: 1 } },
      { literal_inputs: { Size: Infinity } },
      { literal_inputs: { Center: [0.5, 0.5, 0] } },
      { literal_inputs: { Size: {} } },
      { literal_inputs: [] },
      { inputs: { size: 0.1 }, literal_inputs: { Size: 0.12 } },
      { preset: 'Lollipop', inputs: { baseOutlineEnabled: 1 } },
    ];
    for (let i = 0; i < cases.length; i++) {
      const output = path.join(dir, `refused-${i}.drt`);
      await assert.rejects(editSubtitleTimeline({ source, output, ...cases[i] }));
      assert.equal(await fs.stat(output).catch(() => null), null);
    }
  } finally { await fs.rm(dir, { recursive: true, force: true }); }
});
