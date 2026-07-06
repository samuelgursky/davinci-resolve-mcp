/**
 * drt tool — DaVinci Resolve Timeline (.drt) format. All actions local/offline.
 *
 * parse — .drt/.drp path → { timelines, metadata, seqContainers }
 * author — spec → .drt bytes written to outputPath
 * validate — .drt path → { valid, errors }
 * inject_into_drp — graft a .drt's SeqContainers into an existing .drp
 * extract_from_drp — pull a SeqContainer out of a .drp as a .drt
 *
 * inject/extract piggy-back on the shared SeqContainer schema — DRT and DRP
 * differ only by the project shell, so timeline surgery is a zip-entry copy.
 */

import fs from 'node:fs/promises';
import { z } from 'zod';
import JSZip from 'jszip';
import { drt } from '../libs.mjs';
import { summarizeDrtTimelines } from '../sequences.mjs';

const parseSchema = z.object({ drtPath: z.string().describe('Absolute path to a .drt (or .drp) file') });
const listSequencesSchema = z.object({ drpPath: z.string().describe('Absolute path to a .drp (or .drt) file') });
const authorSchema = z.object({
  spec: z.object({}).passthrough().describe('{ timelines, mediaPool?, metadata? } — buildDRP shape minus the project shell'),
  outputPath: z.string().describe('Absolute path where the .drt will be written'),
});
const validateSchema = z.object({ drtPath: z.string().describe('Absolute path to a .drt file') });
const injectIntoDrpSchema = z.object({
  drtPath: z.string().describe('Source .drt'),
  drpPath: z.string().describe('Target.drp to inject into'),
  outputPath: z.string().describe('Path for the modified .drp'),
});
const extractFromDrpSchema = z.object({
  drpPath: z.string().describe('Source .drp'),
  outputPath: z.string().describe('Path for the emitted .drt'),
  timelineIndex: z.number().int().nonnegative().optional().describe('Which SeqContainer to extract (0-based, default 0)'),
});

// Verified Resolve app-version → on-disk <ProjectVersion> map (the import GATE).
// A.drt/.drp whose ProjectVersion is NEWER than the target app is refused
// ("A newer version of DaVinci Resolve is needed to import"). Downgrading the
// element lets an older app open it. Add points as they're confirmed.
const PROJECT_VERSION_BY_APP = Object.freeze({
  '18.0': 11,
  18: 11,
  '19.0': 14,
  19.1: 14,
  19: 14,
  '21.0': 17,
  21: 17,
});
function resolveTargetProjectVersion({ targetProjectVersion, targetAppVersion }) {
  if (Number.isInteger(targetProjectVersion)) return targetProjectVersion;
  if (targetAppVersion) {
    const parts = String(targetAppVersion).split('.');
    for (const key of [`${parts[0]}.${parts[1]}`, parts[0]]) {
      if (key in PROJECT_VERSION_BY_APP) return PROJECT_VERSION_BY_APP[key];
    }
    throw new Error(
      `unknown targetAppVersion "${targetAppVersion}" — pass targetProjectVersion explicitly (known apps: ${Object.keys(PROJECT_VERSION_BY_APP).join(', ')})`,
    );
  }
  throw new Error('provide targetProjectVersion (int) or targetAppVersion (e.g. "19.1.3")');
}

const downgradeSchema = z.object({
  drtPath: z.string().describe('Source .drt/.drp (e.g. exported from a newer Resolve)'),
  outputPath: z.string().describe('Where to write the downgraded file'),
  targetProjectVersion: z.number().int().optional().describe('On-disk <ProjectVersion> to stamp (overrides targetAppVersion)'),
  targetAppVersion: z.string().optional().describe('Target Resolve app version, e.g. "19.1.3" — mapped to ProjectVersion'),
  appVersionString: z.string().optional().describe('DbAppVer comment to stamp (default derived from targetAppVersion, else "<v>.0.0.0000")'),
});

export const drtTool = {
  name: 'drt',
  description:
    'DaVinci Resolve Timeline (.drt) operations — offline, no Resolve required. Actions: parse, list_sequences (enumerate the timelines inside a .drp/.drt → [{id,name,eventCount,index}] to drive a "which sequence?" picker), author, validate, inject_into_drp, extract_from_drp (pull one SeqContainer out as a .drt — feed the .drt to the Python davinci-resolve MCP timeline.import_timeline_checked, or use timeline.import_from_drp to do both), downgrade (stamp <ProjectVersion> down so an OLDER Resolve will import a .drt/.drp from a newer one — pass targetAppVersion like "19.1.3" or targetProjectVersion).',
  async handler({ action, args }) {
    if (action === 'parse') {
      const p = parseSchema.parse(args);
      return drt().parseDRT(p.drtPath);
    }
    if (action === 'list_sequences') {
      const p = listSequencesSchema.parse(args);
      const parsed = await drt().parseDRT(p.drpPath);
      const sequences = summarizeDrtTimelines(parsed);
      return { path: p.drpPath, count: sequences.length, sequences };
    }
    if (action === 'author') {
      const p = authorSchema.parse(args);
      const buf = await drt().buildDRT(p.spec);
      await fs.writeFile(p.outputPath, buf);
      return { outputPath: p.outputPath, bytes: buf.length };
    }
    if (action === 'validate') {
      const p = validateSchema.parse(args);
      return drt().validateDRT(p.drtPath);
    }
    if (action === 'inject_into_drp') {
      const p = injectIntoDrpSchema.parse(args);
      const drpZip = await JSZip.loadAsync(await fs.readFile(p.drpPath));
      const drtZip = await JSZip.loadAsync(await fs.readFile(p.drtPath));
      let projectFolder = 'Primary1';
      let existingCount = 0;
      drpZip.forEach((path, e) => {
        if (e.dir) return;
        const m = path.match(/^(.*?)\/?SeqContainer\d*\.xml$/);
        if (m) {
          existingCount += 1;
          if (m[1]) projectFolder = m[1];
        }
      });
      let injected = 0;
      const jobs = [];
      drtZip.forEach((path, e) => {
        if (e.dir || !/(^|\/)SeqContainer\d*\.xml$/.test(path)) return;
        jobs.push(
          drtZip
            .file(path)
            .async('string')
            .then((xml) => {
              drpZip.file(`${projectFolder}/SeqContainer${existingCount + injected + 1}.xml`, xml);
              injected += 1;
            }),
        );
      });
      await Promise.all(jobs);
      const outBuf = await drpZip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
      await fs.writeFile(p.outputPath, outBuf);
      return { outputPath: p.outputPath, bytes: outBuf.length, seqContainersInjected: injected, projectFolder };
    }
    if (action === 'extract_from_drp') {
      const p = extractFromDrpSchema.parse(args);
      const drpZip = await JSZip.loadAsync(await fs.readFile(p.drpPath));
      const seqEntries = drt().listSeqContainerEntries(drpZip);
      const idx = p.timelineIndex ?? 0;
      if (idx >= seqEntries.length) {
        return { error: `timelineIndex ${idx} out of range (${seqEntries.length} SeqContainers)` };
      }
      const xml = await drpZip.file(seqEntries[idx]).async('string');
      const out = new JSZip();
      out.file('Primary1/SeqContainer1.xml', xml);
      out.file(
        'metadata.json',
        JSON.stringify(
          {
            source: 'extract_from_drp',
            sourceDrp: p.drpPath,
            sourceSeqContainer: seqEntries[idx],
            exportedFrom: 'davinci-resolve-advanced-mcp drt.extract_from_drp',
          },
          null,
          2,
        ),
      );
      const outBuf = await out.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
      await fs.writeFile(p.outputPath, outBuf);
      return { outputPath: p.outputPath, bytes: outBuf.length, sourceSeqContainer: seqEntries[idx] };
    }
    if (action === 'downgrade') {
      const p = downgradeSchema.parse(args);
      const targetPV = resolveTargetProjectVersion(p);
      const appVer =
        p.appVersionString ||
        (p.targetAppVersion ? `${p.targetAppVersion}${'.0'.repeat(Math.max(0, 4 - String(p.targetAppVersion).split('.').length))}` : `${targetPV}.0.0.0000`);
      const zip = await JSZip.loadAsync(await fs.readFile(p.drtPath));
      const out = new JSZip();
      let elementPatches = 0;
      let stampPatches = 0;
      const jobs = [];
      zip.forEach((path, e) => {
        if (e.dir) return;
        jobs.push(
          (async () => {
            if (!path.endsWith('.xml')) {
              out.file(path, await e.async('nodebuffer'));
              return;
            }
            let xml = await e.async('string');
            xml = xml.replace(/<ProjectVersion>\d+<\/ProjectVersion>/g, () => {
              elementPatches += 1;
              return `<ProjectVersion>${targetPV}</ProjectVersion>`;
            });
            // align the decorative comment stamp too (not the gate, but keep consistent)
            xml = xml.replace(/DbAppVer="[^"]*" DbPrjVer="[^"]*"/g, () => {
              stampPatches += 1;
              return `DbAppVer="${appVer}" DbPrjVer="${targetPV}"`;
            });
            out.file(path, xml);
          })(),
        );
      });
      await Promise.all(jobs);
      // STORE-friendly DEFLATE; JSZip emits no explicit dir entries for.file() adds.
      const buf = await out.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
      await fs.writeFile(p.outputPath, buf);
      return {
        outputPath: p.outputPath,
        bytes: buf.length,
        targetProjectVersion: targetPV,
        appVersion: appVer,
        projectVersionElementsPatched: elementPatches,
        commentStampsPatched: stampPatches,
        note: 'Stamp downgrade clears the import GATE only; verify content imports cleanly (fine clip corrections can drop across a multi-version gap).',
      };
    }
    throw new Error(`Unknown drt action: ${action}`);
  },
};
