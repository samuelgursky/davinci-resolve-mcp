// Native media-descriptor transplant (measured, Studio 19.1.3.7): a repointed
// pool entry imports and reads back perfectly but the render engine refuses
// ("Full resolution media not found") or paints black. Transplanting the
// live-captured native <Element> + rewiring MediaRefs renders identically to
// a natively built timeline (YAVG 123.189 both).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { transplantMediaElement, loadMediaTemplate, cachePathFor } =
  require('../vendor/drp-format/media-template-cache.js');
const { cutSourceIntoClips } = require('../vendor/drp-format/cut-media.js');

test('transplant swaps the element, keeps the folder id, rewires MediaRefs', () => {
  const mp = '<Sm2MpFolder><TimelineClips><Element><Sm2MpVideoClip DbId="old">' +
    '<Name>x.mp4</Name><MpFolder>11111111-1111-1111-1111-111111111111</MpFolder>' +
    '<Sm2MpMedia DbId="oldref"/></Sm2MpVideoClip></Element></TimelineClips></Sm2MpFolder>';
  const seq = '<Sm2TiVideoClip><MediaRef>00000000-0000-0000-0000-000000000000</MediaRef></Sm2TiVideoClip>';
  const cached = {
    poolElement: '<Element><Sm2MpVideoClip DbId="nat"><Name>x.mp4</Name>' +
      '<MpFolder>99999999-9999-9999-9999-999999999999</MpFolder>' +
      '<Sm2MpMedia DbId="natref"/></Sm2MpVideoClip></Element>',
    mediaRef: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
  };
  const res = transplantMediaElement(mp, [seq], cached);
  assert.ok(res.mpXml.includes('DbId="nat"'));
  assert.ok(!res.mpXml.includes('DbId="old"'), 'old element replaced');
  assert.ok(res.mpXml.includes('<MpFolder>11111111-1111-1111-1111-111111111111</MpFolder>'),
    'target folder id preserved');
  assert.equal(res.seqXmls[0],
    '<Sm2TiVideoClip><MediaRef>aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee</MediaRef></Sm2TiVideoClip>');
});

test('cache misses return null; hits require poolElement and mediaRef', () => {
  assert.equal(loadMediaTemplate('/no/such/file.mp4'), null);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mtc-'));
  process.env.DRP_MEDIA_TEMPLATE_DIR = dir;
  // module caches CACHE_DIR at load; test via cachePathFor of the loaded module —
  // it read the env at import time, so write where IT expects.
  const target = '/tmp/some_media_file_for_cache_test.mp4';
  const p = cachePathFor(target);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify({ poolElement: '<Element/>', mediaRef: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee' }));
  const hit = loadMediaTemplate(target);
  assert.ok(hit && hit.mediaRef);
  fs.unlinkSync(p);
});

test('cutSourceIntoClips clones the donor with per-cut geometry', async () => {
  // A minimal archive with one video clip donor — reuse the bundled r19 template.
  const tpl = fs.readFileSync(
    path.join(process.cwd(), 'vendor', 'drp-format', 'templates', 'media-clip-r19.drp'));
  const res = await cutSourceIntoClips(tpl, { cuts: [
    { startFrame: 86400, durationFrames: 10, srcIn: 5 },
    { startFrame: 86410, durationFrames: 20, srcIn: 50 },
  ]});
  assert.equal(res.cutCount, 2);
  assert.equal(res.clipDbIds.length, 2);
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(res.buffer);
  for (const n of Object.keys(zip.files)) {
    if (!/SeqContainer\/.+\.xml$/.test(n)) continue;
    const xml = await zip.file(n).async('string');
    const starts = [...xml.matchAll(/<Sm2TiVideoClip[^>]*>[\s\S]*?<Start>(\d+)<\/Start>/g)].map((m) => m[1]);
    assert.deepEqual(starts, ['86400', '86410']);
  }
});

test('multi-source: missing caches refuse with the capture action named', async () => {
  const { assembleTimeline } = require('../vendor/drp-format/index.js');
  await assert.rejects(
    assembleTimeline({
      media: [
        { mediaFilePath: '/no/cache/a.mp4', spec: { width: 64, height: 36, frameCount: 48, fps: 24 },
          cuts: [{ startFrame: 86400, durationFrames: 10 }] },
        { mediaFilePath: '/no/cache/b.mp4', spec: { width: 64, height: 36, frameCount: 48, fps: 24 },
          cuts: [{ startFrame: 86410, durationFrames: 10 }] },
      ],
    }),
    /capture_media_template/,
  );
});

test('insertMediaElement appends a sibling into MediaVec with the folder id fixed', () => {
  const { insertMediaElement } = require('../vendor/drp-format/media-template-cache.js');
  const mp = '<Sm2MpFolder><MediaVec><Element><Sm2MpVideoClip DbId="one">' +
    '<MpFolder>11111111-1111-1111-1111-111111111111</MpFolder></Sm2MpVideoClip></Element>' +
    '</MediaVec></Sm2MpFolder>';
  const el = '<Element><Sm2MpVideoClip DbId="two">' +
    '<MpFolder>99999999-9999-9999-9999-999999999999</MpFolder></Sm2MpVideoClip></Element>';
  const out = insertMediaElement(mp, el);
  assert.ok(out.includes('DbId="one"') && out.includes('DbId="two"'));
  assert.equal((out.match(/<MpFolder>11111111-1111-1111-1111-111111111111<\/MpFolder>/g) || []).length, 2,
    'inserted element adopts the target folder id');
  assert.ok(out.indexOf('DbId="two"') < out.indexOf('</MediaVec>'));
});

test('per-cut mediaRef rewires the clone', async () => {
  const fs2 = require('node:fs');
  const path2 = require('node:path');
  const tpl = fs2.readFileSync(
    path2.join(process.cwd(), 'vendor', 'drp-format', 'templates', 'media-clip-r19.drp'));
  const ref = 'abcdefab-1234-5678-9abc-def012345678';
  const res = await cutSourceIntoClips(tpl, { cuts: [
    { startFrame: 86400, durationFrames: 10, mediaRef: ref },
    { startFrame: 86410, durationFrames: 10 },
  ]});
  const JSZip2 = require('jszip');
  const zip = await JSZip2.loadAsync(res.buffer);
  for (const n of Object.keys(zip.files)) {
    if (!/SeqContainer\/.+\.xml$/.test(n)) continue;
    const xml = await zip.file(n).async('string');
    const refs = [...xml.matchAll(/<Sm2TiVideoClip[^>]*>[\s\S]*?<MediaRef>([0-9a-f-]{36})<\/MediaRef>/g)].map((m) => m[1]);
    assert.equal(refs[0], ref, 'first cut rewired');
    assert.notEqual(refs[1], ref, 'second cut keeps donor ref');
  }
});

test('harvested r19 snippets are Element-wrapped (unwrapped clips break the track vec)', () => {
  // An unwrapped clip inserted into Items made AddRenderJob-era renders fail
  // outright with no status (measured); the wrapper is load-bearing.
  const fs3 = require('node:fs');
  const path3 = require('node:path');
  for (const f of ['fusion-title-r19.xml', 'generator-solid-color-r19.xml', 'fusion-title.xml', 'generator-solid-color.xml', 'transition-cross-fade-r19.xml']) {
    const s = fs3.readFileSync(
      path3.join(process.cwd(), 'vendor', 'drp-format', 'templates', f), 'utf8').trim();
    assert.ok(s.startsWith('<Element>'), `${f} must start with <Element>`);
    assert.ok(s.endsWith('</Element>'), `${f} must end with </Element>`);
  }
});
