/**
 * conform.relink_scalefix — multi-root footage indexing + proxy/test warnings.
 * The 0913 footprint: a source whose highres lives in a footage folder you forgot
 * to index stays stuck on its proxy pathurl. relink_scalefix now indexes MULTIPLE
 * roots (PROXY excluded) and reports any clip left on a proxy/test path.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs';

import { conformTool } from '../server/tools/conform.mjs';

const XMEML = `<?xml version="1.0" encoding="UTF-8"?>
<xmeml version="4">
 <sequence>
 <name>TestSeq</name>
 <rate><timebase>24</timebase><ntsc>FALSE</ntsc></rate>
 <media><video>
 <format><samplecharacteristics><width>3600</width><height>2160</height><rate><timebase>24</timebase></rate></samplecharacteristics></format>
 <track>
 <clipitem id="clipitem-1"><name>clipA</name><start>0</start><end>48</end><in>0</in><out>48</out>
 <file id="file-1"><name>clipA_proxy.mov</name>
 <pathurl>file://localhost/Volumes/X/01X_TEST_FOOTAGE/PROXY/clipA%20proxy.mov</pathurl>
 <media><video><samplecharacteristics><width>2048</width><height>1306</height></samplecharacteristics></video></media></file></clipitem>
 <clipitem id="clipitem-2"><name>clipB</name><start>48</start><end>96</end><in>0</in><out>48</out>
 <file id="file-2"><name>clipB.mov</name>
 <pathurl>file://localhost/Volumes/HR/ScanLab/clipB.mov</pathurl>
 <media><video><samplecharacteristics><width>4096</width><height>2612</height></samplecharacteristics></video></media></file></clipitem>
 </track>
 </video></media>
 </sequence>
</xmeml>`;

function writeXmeml() {
  const p = path.join(os.tmpdir(), `relinkwarn-${process.pid}-${Math.floor(performance.now())}.xml`);
  fs.writeFileSync(p, XMEML);
  return p;
}

test('warns on a source left on a proxy/test path (nothing relinked)', async () => {
  const filePath = writeXmeml();
  const r = await conformTool.handler({
    action: 'relink_scalefix',
    args: {
      filePath,
      media: [],
      sequenceWidth: 3600,
      sequenceHeight: 2160,
    },
  });
  assert.equal(r.warnings.hasIssues, true);
  // clipA's path has PROXY + TEST markers → flagged; clipB's highres path is clean
  assert.equal(r.warnings.leftOnProxyOrTest.length, 1);
  assert.match(r.warnings.leftOnProxyOrTest[0], /PROXY\/clipA proxy\.mov$/);
  assert.ok(!r.warnings.leftOnProxyOrTest.some((u) => u.includes('clipB')));
  // both sources are unresolved (empty index)
  assert.ok(r.warnings.unresolvedSources.length >= 1);
});

test('no proxy warning when paths are clean (custom proxyMarkers)', async () => {
  const filePath = writeXmeml();
  // mark only an impossible token so nothing matches as proxy
  const r = await conformTool.handler({
    action: 'relink_scalefix',
    args: {
      filePath,
      media: [],
      sequenceWidth: 3600,
      sequenceHeight: 2160,
      proxyMarkers: ['__never__'],
    },
  });
  assert.equal(r.warnings.leftOnProxyOrTest.length, 0);
});

test('indexes MULTIPLE footage roots and excludes PROXY from the index', async () => {
  const filePath = writeXmeml();
  const root1 = fs.mkdtempSync(path.join(os.tmpdir(), 'fr1-'));
  const root2 = fs.mkdtempSync(path.join(os.tmpdir(), 'fr2-'));
  fs.writeFileSync(path.join(root1, 'clipX.mov'), '');
  fs.mkdirSync(path.join(root2, 'PROXY'));
  fs.writeFileSync(path.join(root2, 'PROXY', 'clipY.mov'), ''); // excluded
  fs.writeFileSync(path.join(root2, 'clipZ.mov'), '');
  const r = await conformTool.handler({
    action: 'relink_scalefix',
    args: {
      filePath,
      footageDirs: [root1, root2],
      sequenceWidth: 3600,
      sequenceHeight: 2160,
    },
  });
  assert.equal(r.mediaIndexed, 2); // clipX + clipZ, PROXY/clipY excluded
  assert.deepEqual(r.indexRoots, [root1, root2]);
});

test('back-compat: single footageDir still works', async () => {
  const filePath = writeXmeml();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'fr-'));
  fs.writeFileSync(path.join(root, 'clipQ.mov'), '');
  const r = await conformTool.handler({
    action: 'relink_scalefix',
    args: {
      filePath,
      footageDir: root,
      sequenceWidth: 3600,
      sequenceHeight: 2160,
    },
  });
  assert.equal(r.mediaIndexed, 1);
});
