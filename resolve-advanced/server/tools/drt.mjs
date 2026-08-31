/**
 * drt tool — DaVinci Resolve Timeline (.drt) format. All actions local/offline.
 *
 * parse — .drt/.drp path → { timelines, metadata, seqContainers }
 * author — spec → .drt bytes written to outputPath. TEMPLATE SCHEMA: the
 *   output serves offline/DB workflows (inject_into_drp, parsing, diffing);
 *   Resolve's ImportTimelineFromFile REFUSES it (measured 19.1.3.7 — the
 *   native format is blob-based with a project.xml this shape lacks). For a
 *   file Resolve imports, author OTIO, or extract a REAL container with
 *   extract_from_drp.
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
import { drt, drp } from '../libs.mjs';
import { summarizeDrtTimelines } from '../sequences.mjs';

const parseSchema = z.object({ drtPath: z.string().describe('Absolute path to a .drt (or .drp) file') });
const listSequencesSchema = z.object({ drpPath: z.string().describe('Absolute path to a .drp (or .drt) file') });
const authorSchema = z.object({
  spec: z.object({}).passthrough().describe('{ timelines, mediaPool?, metadata? } — buildDRP shape minus the project shell'),
  outputPath: z.string().describe('Absolute path where the .drt will be written'),
});
const validateSchema = z.object({ drtPath: z.string().describe('Absolute path to a .drt file') });
const assembleFromInterchangeSchema = z.object({
  format: z.enum(['edl', 'otio', 'xml', 'aaf']).describe('Interchange format of the input'),
  path: z.string().optional().describe('Path to the interchange file (aaf REQUIRES a path)'),
  content: z.string().optional().describe('Inline interchange text (edl/otio/xml)'),
  fps: z.number().optional().describe('Event frame rate for parsing (default 24; use e.g. 29.97 for NTSC EDLs)'),
  sourceMap: z
    .record(z.object({ mediaFilePath: z.string(), spec: z.object({}).passthrough() }))
    .describe('reel/source name → {mediaFilePath, spec:{width,height,frameCount,fps}}; every video event must map'),
  timelineName: z.string().optional(),
  outputPath: z.string().describe('Where the importable .drt is written'),
  targetAppVersion: z.union([z.string(), z.number()]).optional()
    .describe("Host Resolve version, e.g. '19.1' for pre-21"),
});
const assembleSchema = z.object({
  spec: z
    .object({})
    .passthrough()
    .describe("assembleTimeline spec: { timelineName?, media?: {mediaFilePath, spec:{width,height,frameCount,fps}, cuts:[{startFrame,durationFrames,srcIn?,track? (1-based video track; >1 = video-only, render-verified stacking),speed? (forward constant retime, e.g. 0.5; video-only; render-verified on 19)}]} | [same, ...] (multi-source needs media_pool.capture_media_template run once per file), elements?: [{type:'title'|'generator', track, startFrame, durationFrames?, text?, generatorName? ('Solid Color'|'SMPTE Color Bar'|'Grey Scale' render-verified on 19), ...}], transitions? }. startFrame is timeline-absolute (origin 86400)."),
  outputPath: z.string().describe('Absolute path where the importable .drt will be written'),
  targetAppVersion: z
    .union([z.string(), z.number()])
    .optional()
    .describe("Resolve version that must import it, e.g. '19.1' — stamps ProjectVersion down from the template's Resolve-21 capture. Omit for 21+ hosts."),
});

/** Rewrite version stamps across every XML entry of a JSZip; returns patch counts. */
async function applyVersionStamps(zip, targetPV, appVer) {
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
        xml = xml.replace(/DbAppVer="[^"]*" DbPrjVer="[^"]*"/g, () => {
          stampPatches += 1;
          return `DbAppVer="${appVer}" DbPrjVer="${targetPV}"`;
        });
        out.file(path, xml);
      })(),
    );
  });
  await Promise.all(jobs);
  return { out, elementPatches, stampPatches };
}
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

/**
 * .drt/.drp are ZIP containers, so every reader here takes a FILE PATH. A caller reaching for the
 * content-shaped convention its sibling text formats use (`{ content }`) otherwise gets a bare zod
 * dump that never names the key it wanted.
 */
function requirePathArg(args, key, action) {
  const a = args && typeof args === 'object' ? args : {};
  if (typeof a[key] === 'string' && a[key]) return a;
  const given = Object.keys(a).filter((k) => a[k] !== undefined);
  throw new Error(
    `drt.${action}: pass \`${key}\` — an absolute path to the .drt/.drp. A .drt/.drp is a ZIP container, so this action reads a FILE PATH, never file content` +
      `${given.length ? ` (got: ${given.join(', ')})` : ' (got no arguments)'}.`,
  );
}

export const drtTool = {
  name: 'drt',
  description:
    'DaVinci Resolve Timeline (.drt) operations — offline, no Resolve required. Actions: assemble_from_interchange (EDL/OTIO/XML/AAF + sourceMap → IMPORTABLE RENDERING native .drt in one call; retimes flatten; cross-dissolves are AUTHORED when the cut abuts with handles both sides (render-verified on 19), else dropped with reason; ledger in `conform`), assemble (spec → IMPORTABLE native-schema .drt via template-spliced real structures; pass targetAppVersion e.g. \'19.1\' for pre-21 hosts), parse, list_sequences (enumerate the timelines inside a .drp/.drt → [{id,name,eventCount,index}] to drive a "which sequence?" picker), author, validate, inject_into_drp, extract_from_drp (pull one SeqContainer out as a .drt — feed the .drt to the Python davinci-resolve MCP timeline.import_timeline_checked, or use timeline.import_from_drp to do both), downgrade (stamp <ProjectVersion> down so an OLDER Resolve will import a .drt/.drp from a newer one — pass targetAppVersion like "19.1.3" or targetProjectVersion).',
  async handler({ action, args }) {
    if (action === 'parse') {
      const p = parseSchema.parse(requirePathArg(args, 'drtPath', 'parse'));
      return drt().parseDRT(p.drtPath);
    }
    if (action === 'list_sequences') {
      const p = listSequencesSchema.parse(requirePathArg(args, 'drpPath', 'list_sequences'));
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
      const p = validateSchema.parse(requirePathArg(args, 'drtPath', 'validate'));
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
    if (action === 'assemble_from_interchange') {
      // Coast-to-coast conform: interchange in, importable RENDERING .drt out.
      const p = assembleFromInterchangeSchema.parse(args);
      const { parseInterchange } = await import('../editorial.mjs');
      const { eventsToAssembleSpec } = await import('../author-interchange.mjs');
      let content = p.content;
      if (p.format === 'aaf') {
        if (!p.path) return { error: 'aaf input requires path' };
        content = p.path;
      } else if (!content) {
        if (!p.path) return { error: 'provide content or path' };
        content = await fs.readFile(p.path, 'utf8');
      }
      const events = parseInterchange(p.format, content, { fps: p.fps ?? 24 });
      if (!events || !events.length) return { error: 'no events parsed from the interchange input' };
      const { spec, report } = eventsToAssembleSpec(events, {
        sourceMap: p.sourceMap, timelineName: p.timelineName,
      });
      if (p.targetAppVersion !== undefined) {
        spec.templateVersion = parseFloat(p.targetAppVersion) >= 21 ? 21 : 19;
      }
      const { assembleTimeline } = drp();
      const { buffer, timelineName, mediaDescriptor } = await assembleTimeline(spec);
      let outBuf = buffer;
      let stamped = null;
      if (p.targetAppVersion !== undefined) {
        const targetPV = resolveTargetProjectVersion({ targetAppVersion: p.targetAppVersion });
        const appVer = `${p.targetAppVersion}${'.0'.repeat(Math.max(0, 4 - String(p.targetAppVersion).split('.').length))}`;
        const zip = await JSZip.loadAsync(buffer);
        const { out } = await applyVersionStamps(zip, targetPV, appVer);
        outBuf = await out.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
        stamped = { targetProjectVersion: targetPV };
      }
      await fs.writeFile(p.outputPath, outBuf);
      return {
        outputPath: p.outputPath,
        bytes: outBuf.length,
        timelineName,
        mediaDescriptor,
        stamped,
        conform: report,
        note:
          'Import with timeline.import_timeline_checked (timeline is named after the FILE). ' +
          'Retimes are flattened and transitions become cuts — see `conform` for the ledger.',
      };
    }
    if (action === 'assemble') {
      const p = assembleSchema.parse(args);
      // Native-schema authoring: template-spliced real Resolve structures
      // (drp-format assembleTimeline), which ImportTimelineFromFile accepts —
      // unlike drt.author's flat template. Measured live on Studio 19.1.3.7:
      // assembled + stamped to the host's ProjectVersion imports with every
      // element intact.
      const { assembleTimeline } = drp();
      // The template GENERATION must match the target host: a Resolve-21
      // template stamped down imports on 19 but renders BLACK (measured) —
      // the stamp clears the gate, not the blob semantics.
      const spec = { ...p.spec };
      if (spec.templateVersion === undefined && p.targetAppVersion !== undefined) {
        spec.templateVersion = parseFloat(p.targetAppVersion) >= 21 ? 21 : 19;
      }
      const { buffer, timelineName, startFrame, mediaDescriptor } = await assembleTimeline(spec);
      let outBuf = buffer;
      let stamped = null;
      if (p.targetAppVersion !== undefined) {
        const targetPV = resolveTargetProjectVersion({ targetAppVersion: p.targetAppVersion });
        const appVer = `${p.targetAppVersion}${'.0'.repeat(Math.max(0, 4 - String(p.targetAppVersion).split('.').length))}`;
        const zip = await JSZip.loadAsync(buffer);
        const { out, elementPatches, stampPatches } = await applyVersionStamps(zip, targetPV, appVer);
        outBuf = await out.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
        stamped = { targetProjectVersion: targetPV, elementPatches, stampPatches };
      }
      await fs.writeFile(p.outputPath, outBuf);
      return {
        outputPath: p.outputPath,
        bytes: outBuf.length,
        timelineName,
        startFrame,
        stamped,
        templateVersion: spec.templateVersion ?? 21,
        mediaDescriptor: mediaDescriptor ?? 'none',
        ...((spec.elements || []).some((e) => e && e.type === 'title') && (spec.templateVersion ?? 21) < 21
          ? {
              elementsWarning:
                'On a pre-21 host, imported Fusion TITLE comps render only via the machine\'s ' +
                'Fusion disk cache, keyed to the EXACT comp bytes (measured: an identity ' +
                'recompression rendered black) — offline-authored titles may render black and ' +
                'offline text patching cannot work there. The working pre-21 title flow: assemble ' +
                'without title text, then set it post-import with timeline.set_title_text (its ' +
                'Fusion-comp path is live-verified on 19.1.3). Media cuts and built-in GENERATORS ' +
                '(Solid Color / SMPTE Color Bar / Grey Scale — plain Sm2TiGenerator, no Fusion ' +
                'comp) render everywhere: generator kinds render-verified on 19.1.3.',
            }
          : {}),
        ...(mediaDescriptor === 'repoint-fallback'
          ? {
              warning:
                'No native media template cached for this file — the archive imports and reads back ' +
                'correctly but its media may not RENDER (black frames / "Full resolution media not ' +
                'found"). Run media_pool.capture_media_template(media_path) once with Resolve open, ' +
                'then re-assemble for a render-verified transplant.',
            }
          : {}),
        note:
          'Import with timeline.import_timeline_checked — the imported timeline is named after the FILE. ' +
          'On a host older than Resolve 21, pass targetAppVersion or the version gate refuses the archive.',
      };
    }
    if (action === 'extract_from_drp') {
      const p = extractFromDrpSchema.parse(args);
      const drpZip = await JSZip.loadAsync(await fs.readFile(p.drpPath));
      const seqEntries = drt().listSeqContainerEntries(drpZip);
      const idx = p.timelineIndex ?? 0;
      if (idx >= seqEntries.length) {
        return { error: `timelineIndex ${idx} out of range (${seqEntries.length} SeqContainers)` };
      }
      // The importable-.drt recipe, measured by bisection on Studio 19.1.3.7:
      // a .drt IS a .drp that ImportTimelineFromFile accepts. project.xml and
      // MediaPool/ are REQUIRED (the Sm2Sequence/Sm2Timeline objects live in
      // MpFolder.xml); the SeqContainer must keep its ORIGINAL uuid path —
      // renaming it imports an EMPTY timeline with no error; Gallery.xml is
      // droppable. Other timelines' MpFolder blocks must go too, or each
      // arrives as a ghost empty timeline (matched via the container tracks'
      // <Sequence> DbId, which appears inside exactly one Sm2MpTimelineClip).
      const keepEntry = seqEntries[idx];
      const keepXml = await drpZip.file(keepEntry).async('string');
      const keepSeqIds = [...keepXml.matchAll(/<Sequence>([0-9a-f-]{36})<\/Sequence>/g)].map((m) => m[1]);
      const out = new JSZip();
      let droppedTimelines = 0;
      for (const name of Object.keys(drpZip.files)) {
        const entry = drpZip.files[name];
        if (entry.dir) continue;
        if (name === 'Gallery.xml') continue;
        const isSeq = seqEntries.includes(name);
        if (isSeq && name !== keepEntry) continue;
        let content = await entry.async(name.endsWith('.xml') ? 'string' : 'nodebuffer');
        if (name.endsWith('MpFolder.xml') && seqEntries.length > 1) {
          content = content.replace(
            /<Element>\s*<Sm2MpTimelineClip DbId="[^"]+">(?:(?!<\/Sm2MpTimelineClip>)[\s\S])*?<\/Sm2MpTimelineClip>\s*<\/Element>/g,
            (block) => {
              if (keepSeqIds.some((id) => block.includes(id))) return block;
              droppedTimelines += 1;
              return '';
            },
          );
        }
        out.file(name, content);
      }
      out.file(
        'metadata.json',
        JSON.stringify(
          {
            source: 'extract_from_drp',
            sourceDrp: p.drpPath,
            sourceSeqContainer: keepEntry,
            droppedTimelines,
            exportedFrom: 'davinci-resolve-advanced-mcp drt.extract_from_drp',
          },
          null,
          2,
        ),
      );
      const outBuf = await out.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
      await fs.writeFile(p.outputPath, outBuf);
      return {
        outputPath: p.outputPath,
        bytes: outBuf.length,
        sourceSeqContainer: keepEntry,
        droppedTimelines,
        note: 'The imported timeline is named after the FILE. Source must be a SAVED project export — ExportProject snapshots the saved DB state, so unsaved edits are absent.',
      };
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
