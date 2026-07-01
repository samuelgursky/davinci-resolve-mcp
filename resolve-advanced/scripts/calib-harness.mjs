/**
 * DRX calibration harness — read the DRX_CALIB SMPTE-bars clip's live grade
 * Body out of a COPY of its Project.db, wrap it in a GyStill envelope, decode via the
 * drx parser, and dump every decoded param (named + unknown_ + NaN) so a UI sweep can
 * be mapped by matching unique values.
 *
 * Usage:
 *   node scripts/calib-harness.mjs [timelineName] [--raw] [--all]
 *     timelineName  default "BARS"
 *     --raw         also print the raw Body hex length + first node corrector summary
 *     --all         print ALL params (default also prints all; kept for symmetry)
 *
 * Read-only: copies Project.db to /tmp first (Resolve may hold a WAL on the live file).
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { findProjectDb } from '../server/db-patch.mjs';
import { readTimelineClips } from '../server/tools/project_read.mjs';
import { drxTool } from '../server/tools/drx.mjs';

const TIMELINE = process.argv[2] && !process.argv[2].startsWith('--') ? process.argv[2] : 'BARS';
const PROJECT = 'DRX_CALIB';

function xmlEscape(s) { return String(s).replace(/[<>&'"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', "'": '&apos;', '"': '&quot;' }[c])); }

function drxEnvelope(label, bodyHex) {
  const stillId = crypto.randomUUID();
  const verId = crypto.randomUUID();
  return `<?xml version="1.0" encoding="UTF-8"?>
<!--DbAppVer="19.1.3.0007" DbPrjVer="14"-->
<Gallery::GyStill DbId="${stillId}">
 <FieldsBlob/>
 <SrcHint>${xmlEscape(label)}</SrcHint>
 <SrcType>1</SrcType>
 <Label>${xmlEscape(label)}</Label>
 <Width>1920</Width>
 <Height>1080</Height>
 <BitDepth>10</BitDepth>
 <PAR>1</PAR>
 <Endianship>1</Endianship>
 <CreateTime>2026-01-01T00:00:00.000</CreateTime>
 <pClipFullVer>
  <ListMgt::LmVersion DbId="${verId}">
   <FieldsBlob/>
   <Name/>
   <HasCorrection>true</HasCorrection>
   <VerType>0</VerType>
   <ImplVersion>1</ImplVersion>
   <Body>${bodyHex}</Body>
  </ListMgt::LmVersion>
 </pClipFullVer>
 <PrimaryCCMode>0</PrimaryCCMode>
</Gallery::GyStill>
`;
}

async function main() {
  const hits = findProjectDb(PROJECT);
  if (!hits.length) throw new Error(`no Project.db for ${PROJECT}`);
  const src = hits[0];
  const tmp = path.join(os.tmpdir(), `drxcalib-${Date.now()}.db`);
  fs.copyFileSync(src, tmp);
  // also copy WAL/SHM siblings if present so the copy reflects unflushed writes
  for (const ext of ['-wal', '-shm']) {
    if (fs.existsSync(src + ext)) fs.copyFileSync(src + ext, tmp + ext);
  }

  const clips = readTimelineClips(tmp, TIMELINE, 'video', true);
  const graded = clips.filter((c) => c.gradeBody);
  console.log(`# project=${PROJECT} timeline=${TIMELINE} videoClips=${clips.length} graded=${graded.length}`);
  if (!graded.length) { console.log('NO GRADED CLIP (HasCorrection=1) — apply a grade + Cmd+S first.'); return; }

  for (const c of graded) {
    const bodyHex = c.gradeBody;
    console.log(`\n## clip="${c.name}" bodyBytes=${bodyHex.length / 2}`);
    const content = drxEnvelope(c.name, bodyHex);
    const r = await drxTool.handler({ action: 'parse', args: { content } });
    console.log(`nodes=${r.nodes?.length}`);
    for (let ni = 0; ni < (r.nodes || []).length; ni++) {
      const n = r.nodes[ni];
      const params = n.params || {};
      const correctors = n.correctors || [];
      console.log(`--- node ${ni} correctors=${correctors.length} ---`);
      for (const cor of correctors) {
        const ct = cor.correctorType ?? cor.type ?? '?';
        const plist = cor.parameters || [];
        for (const p of plist) {
          const hex = typeof p.id === 'number' ? '0x' + (p.id >>> 0).toString(16) : p.id;
          const flag = (p.name && String(p.name).startsWith('unknown_')) ? '  <UNKNOWN>' : (Number.isNaN(p.value) ? '  <NaN>' : '');
          console.log(`  ct${ct} ${hex.padEnd(12)} ${String(p.name).padEnd(28)} = ${p.value}${flag}`);
        }
      }
      // structured extras the parser lifts onto node.params
      for (const key of ['colorSlice']) {
        if (params[key]) console.log(`  params.${key} = ${JSON.stringify(params[key])}`);
      }
      if (n.qualifier) console.log(`  qualifier = ${JSON.stringify(n.qualifier)}`);
      if (n.powerWindow) console.log(`  powerWindow = ${JSON.stringify(n.powerWindow)}`);
      if (n.customCurves) console.log(`  customCurves = ${JSON.stringify(n.customCurves)}`);
      if (n.hslCurves) console.log(`  hslCurves = ${JSON.stringify(n.hslCurves)}`);
    }
  }
  // leave the tmp copy for follow-up offline blob RE
  console.log(`\n# dbCopy=${tmp}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
