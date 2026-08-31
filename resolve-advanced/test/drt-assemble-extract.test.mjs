// Native-schema DRT authoring (measured live on Studio 19.1.3.7):
// drt.assemble splices real Resolve template structures into an archive
// ImportTimelineFromFile accepts; extract_from_drp keeps the importable-.drt
// recipe — project.xml + MediaPool + ORIGINAL SeqContainer path, other
// timelines' MpFolder blocks removed, Gallery dropped.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import JSZip from 'jszip';
import { drtTool } from '../server/lib.mjs';

const tmp = (ext) => path.join(os.tmpdir(), `drtns-${Math.random().toString(36).slice(2)}${ext}`);

test('assemble writes a native archive with the requested version stamps', async () => {
  const out = tmp('.drt');
  const res = await drtTool.handler({ action: 'assemble', args: {
    outputPath: out, targetAppVersion: '19.1',
    spec: { timelineName: 'T', elements: [
      { type: 'title', track: 1, startFrame: 86400, durationFrames: 48, text: 'X' },
    ]},
  }});
  assert.equal(res.stamped.targetProjectVersion, 14);
  assert.ok(res.stamped.elementPatches >= 1);
  const zip = await JSZip.loadAsync(await fs.readFile(out));
  const names = Object.keys(zip.files).filter((n) => !zip.files[n].dir);
  assert.ok(names.includes('project.xml'));
  assert.ok(names.some((n) => n.startsWith('MediaPool/')));
  assert.ok(names.some((n) => /^SeqContainer\//.test(n)), 'original-path container');
  const pj = await zip.file('project.xml').async('string');
  assert.match(pj, /<ProjectVersion>14<\/ProjectVersion>/);
  assert.match(pj, /DbPrjVer="14"/);
  // native schema, not the flat template ImportTimelineFromFile refuses
  const seqName = names.find((n) => /^SeqContainer\//.test(n));
  const seq = await zip.file(seqName).async('string');
  assert.doesNotMatch(seq, /<StartFrame>/);
  await fs.unlink(out);
});

test('assemble without targetAppVersion keeps the template stamps', async () => {
  const out = tmp('.drt');
  const res = await drtTool.handler({ action: 'assemble', args: {
    outputPath: out,
    spec: { elements: [{ type: 'generator', track: 1, startFrame: 86400, durationFrames: 24 }] },
  }});
  assert.equal(res.stamped, null);
  await fs.unlink(out);
});

test('extract keeps the recipe and drops the other timeline block', async () => {
  const alpha = 'aaaaaaaa-1111-2222-3333-444444444444';
  const beta = 'bbbbbbbb-1111-2222-3333-444444444444';
  const container = (id) =>
    `<?xml version="1.0"?><Sm2SequenceContainer DbId="c"><VideoTrackVec><Element>` +
    `<Sm2TiTrack DbId="t"><Sequence>${id}</Sequence></Sm2TiTrack></Element></VideoTrackVec></Sm2SequenceContainer>`;
  const mp =
    '<Sm2MpFolder>' +
    `<Element><Sm2MpTimelineClip DbId="a"><Name>ALPHA</Name><Id>${alpha}</Id></Sm2MpTimelineClip></Element>` +
    `<Element><Sm2MpTimelineClip DbId="b"><Name>BETA</Name><Id>${beta}</Id></Sm2MpTimelineClip></Element>` +
    '</Sm2MpFolder>';
  const zip = new JSZip();
  zip.file('project.xml', '<SM_Project/>');
  zip.file('MediaPool/Master/MpFolder.xml', mp);
  zip.file('SeqContainer/aaaa.xml', container(alpha));
  zip.file('SeqContainer/bbbb.xml', container(beta));
  zip.file('Gallery.xml', '<g/>');
  const src = tmp('.drp');
  await fs.writeFile(src, await zip.generateAsync({ type: 'nodebuffer' }));
  const out = tmp('.drt');
  const res = await drtTool.handler({ action: 'extract_from_drp', args: {
    drpPath: src, outputPath: out, timelineIndex: 0 }});
  assert.equal(res.droppedTimelines, 1);
  const outZip = await JSZip.loadAsync(await fs.readFile(out));
  const names = Object.keys(outZip.files).filter((n) => !outZip.files[n].dir);
  assert.ok(names.includes('SeqContainer/aaaa.xml'), 'original path kept');
  assert.ok(!names.includes('SeqContainer/bbbb.xml'));
  assert.ok(!names.includes('Gallery.xml'));
  const folder = await outZip.file('MediaPool/Master/MpFolder.xml').async('string');
  assert.match(folder, /ALPHA/);
  assert.doesNotMatch(folder, /BETA/, 'ghost timeline block removed');
  await fs.unlink(src);
  await fs.unlink(out);
});

test('generator kind selection lands in the seq XML; title-only warning gate', async () => {
  // Kind swap render-verified on 19.1.3.7: SMPTE Color Bar YAVG 104.9,
  // Grey Scale 125.1, Solid Color 16 — plain Sm2TiGenerator, no Fusion comp,
  // so the byte-keyed comp-cache law does not apply and no warning is due.
  const out = tmp('.drt');
  const res = await drtTool.handler({ action: 'assemble', args: {
    outputPath: out, targetAppVersion: '19.1.3',
    spec: { elements: [
      { type: 'generator', generatorName: 'SMPTE Color Bar', track: 2, startFrame: 86400, durationFrames: 32 },
      { type: 'generator', generatorName: 'Grey Scale', track: 2, startFrame: 86440, durationFrames: 32 },
    ]},
  }});
  assert.equal(res.elementsWarning, undefined, 'generator-only pre-21 spec must not warn');
  const zip = await JSZip.loadAsync(await fs.readFile(out));
  const seqName = Object.keys(zip.files).find((n) => !zip.files[n].dir && /^SeqContainer\//.test(n));
  const seq = await zip.file(seqName).async('string');
  assert.match(seq, /<PrettyType>SMPTE Color Bar<\/PrettyType>/);
  assert.match(seq, /<PrettyType>Grey Scale<\/PrettyType>/);
  await fs.unlink(out);

  const out2 = tmp('.drt');
  const res2 = await drtTool.handler({ action: 'assemble', args: {
    outputPath: out2, targetAppVersion: '19.1.3',
    spec: { elements: [{ type: 'title', track: 1, startFrame: 86400, durationFrames: 24 }] },
  }});
  assert.match(res2.elementsWarning || '', /byte|cache|set_title_text/i, 'pre-21 title spec must warn');
  await fs.unlink(out2);
});
