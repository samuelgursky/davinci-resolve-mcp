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
