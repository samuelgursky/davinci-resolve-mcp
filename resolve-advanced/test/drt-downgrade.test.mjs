/**
 * drt.downgrade — stamp <ProjectVersion> down so an older Resolve imports a newer
 *.drt/.drp. Verified version map (live, 2026-06-23): 18.0.4→11, 19.1.x→14, 21.0→17.
 * The GATE is the <ProjectVersion> ELEMENT, not the DbAppVer/DbPrjVer comment.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs/promises';
import JSZip from 'jszip';

import { drtTool } from '../server/tools/drt.mjs';

const tmp = (n) => path.join(os.tmpdir(), `drt-dg-${n}`);

async function makeV17Drt(p) {
  const z = new JSZip();
  z.file('project.xml', '<?xml version="1.0"?>\n<!--DbAppVer="21.0.0.0048" DbPrjVer="17"-->\n<SM_Project><ProjectVersion>17</ProjectVersion></SM_Project>');
  z.file('SeqContainer/abc.xml', '<?xml version="1.0"?>\n<!--DbAppVer="21.0.0.0048" DbPrjVer="17"-->\n<Seq/>');
  await fs.writeFile(p, await z.generateAsync({ type: 'nodebuffer' }));
}

test('downgrade patches the ProjectVersion element + comment stamp (targetAppVersion)', async () => {
  await makeV17Drt(tmp('in .drt'));
  const r = await drtTool.handler({ action: 'downgrade', args: { drtPath: tmp('in .drt'), outputPath: tmp('out.drt'), targetAppVersion: '19.1.3' } });
  assert.equal(r.targetProjectVersion, 14);
  assert.equal(r.projectVersionElementsPatched, 1);
  assert.equal(r.commentStampsPatched, 2); // both members
  const z = await JSZip.loadAsync(await fs.readFile(tmp('out.drt')));
  const proj = await z.file('project.xml').async('string');
  assert.match(proj, /<ProjectVersion>14<\/ProjectVersion>/);
  assert.match(proj, /DbPrjVer="14"/);
  // the other member's stamp is aligned too
  const seq = await z.file('SeqContainer/abc.xml').async('string');
  assert.match(seq, /DbPrjVer="14"/);
});

test('explicit targetProjectVersion overrides the map', async () => {
  await makeV17Drt(tmp('in2.drt'));
  const r = await drtTool.handler({ action: 'downgrade', args: { drtPath: tmp('in2.drt'), outputPath: tmp('out2.drt'), targetProjectVersion: 11 } });
  assert.equal(r.targetProjectVersion, 11);
  const z = await JSZip.loadAsync(await fs.readFile(tmp('out2.drt')));
  assert.match(await z.file('project.xml').async('string'), /<ProjectVersion>11<\/ProjectVersion>/);
});

test('unknown app version is rejected (no silent guess)', async () => {
  await makeV17Drt(tmp('in3.drt'));
  await assert.rejects(
    () => drtTool.handler({ action: 'downgrade', args: { drtPath: tmp('in3.drt'), outputPath: tmp('x'), targetAppVersion: '99.9' } }),
    /unknown targetAppVersion/,
  );
});

test('missing target is rejected', async () => {
  await makeV17Drt(tmp('in4.drt'));
  await assert.rejects(() => drtTool.handler({ action: 'downgrade', args: { drtPath: tmp('in4.drt'), outputPath: tmp('x') } }), /provide targetProjectVersion/);
});
