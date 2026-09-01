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
  format: z.enum(['edl', 'otio', 'xml', 'aaf', 'prproj']).describe('Interchange format of the input'),
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
  subtitlesSrtPath: z.string().optional().describe('Sidecar .srt for the turnover: cues are authored onto the subtitle track (anchored at the timeline origin)'),
  sequenceName: z.string().optional().describe('Multi-sequence AAF/prproj: assemble THIS sequence (see editorial.list_sequences)'),
  sequenceIndex: z.number().int().optional().describe('Multi-sequence AAF/prproj: assemble the sequence at this 0-based index'),
  preserveStartTimecode: z.boolean().optional()
    .describe('Keep the interchange\'s ABSOLUTE record start: the assembled timeline starts at the turnover\'s real first record frame instead of 01:00:00:00 (start-TC patch render-verified on 19). AAF conforms should pass true.'),
});
const assembleSchema = z.object({
  spec: z
    .object({})
    .passthrough()
    .describe("assembleTimeline spec: { timelineName?, startFrame? (timeline start frame @24, default 86400=01:00:00:00 — sets the start TIMECODE, render-verified on 19), media?: {mediaFilePath, spec:{width,height,frameCount,fps}, cuts:[{startFrame,durationFrames,srcIn?,track? (1-based video track; >1 = video-only, render-verified stacking),speed?/reverse? (constant retime, e.g. 0.5, forward or backwards; video-only; readback+render-verified on 19),freeze? (true = hold source frame srcIn for the whole cut; video-only; render-proven frozen on 19 via freezedetect),ramp? ([{durationFrames,speed},...] >=2 LINEAR segments from the cut head, srcIn honored; video-only; render-proven cadence on 19 — eased/curved ramps are NOT authorable, an interp!=0 keyframe crashes Resolve on import (measured)),audioOnly?+track? (explicit AUDIO placement on audio track 1-8; presence suppresses the A1 mirror; render-verified on 19),markers? (ITEM markers/clip locators: [{frame ITEM-relative, color?, name?, note?, duration?, customData?}] — readback-verified on 19; NOTE Resolve's own EXPORT_DRT drops item markers, this authoring path is the only .drt carrier)}]} | [same, ...] (multi-source needs media_pool.capture_media_template run once per file), transitions?: [{track, atFrame, durationFrames?, trackType? ('video' | 'audio' cross-fade), type? ('dissolve' default | 'wipe' | 'dip' | 'additive' | 'smooth-cut' | 'non-additive' — all render-verified on 19 w/ midpoint fingerprints; XMEML/EDL transition codes route automatically, and NOTE Resolve's own XMEML importer writes transitions that render INERT, so this route beats it)}], markers?: [{frame (timeline-absolute), color? (16 names), name?, note?, duration?, customData?}] (readback-verified on 19), compounds?: [{name, startFrame (parent, absolute), durationFrames, track?, cuts:[{mediaFilePath, startFrame (INNER, 0-based), durationFrames, srcIn?}], compounds?: [same, nested — frames inner-relative]}] (multiple PARALLEL compounds compose AND compounds NEST recursively — depth-2 through depth-4 playback render-verified on 19 (the old depth-2 black was a missing SequenceSetup key, fixed); inner cuts need captured templates w/ native clips), subtitles?: [{startFrame (timeline-absolute), durationFrames, text}] + subtitlesSrt? (raw SRT, cues anchor at the origin; readback-verified on 19; angle-bracket runs read as SRT markup), elements?: [{type:'title'|'generator', track, startFrame, durationFrames?, text?, generatorName? ('Solid Color'|'SMPTE Color Bar'|'Grey Scale' render-verified on 19), ...}] }. startFrame is timeline-absolute (origin 86400)."),
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
    'DaVinci Resolve Timeline (.drt) operations — offline, no Resolve required. Actions: assemble_from_interchange (EDL/OTIO/XML/AAF + sourceMap → IMPORTABLE RENDERING native .drt in one call; retimes AUTHOR — constant speed fwd/rev AND zero-speed freezes (EDL M2 000.0; render-proven frozen); cross-dissolves are AUTHORED when the cut abuts with handles both sides (render-verified on 19), else dropped with reason; ledger in `conform`), assemble (spec → IMPORTABLE native-schema .drt via template-spliced real structures; pass targetAppVersion e.g. \'19.1\' for pre-21 hosts), parse, list_sequences (enumerate the timelines inside a .drp/.drt → [{id,name,eventCount,index}] to drive a "which sequence?" picker), author, validate, inject_into_drp, extract_from_drp (pull one SeqContainer out as a .drt — feed the .drt to the Python davinci-resolve MCP timeline.import_timeline_checked, or use timeline.import_from_drp to do both), downgrade (stamp <ProjectVersion> down so an OLDER Resolve will import a .drt/.drp from a newer one — pass targetAppVersion like "19.1.3" or targetProjectVersion).',
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
      let events;
      const pickSequence = (sequences) => {
        // Multi-sequence containers (AAF/prproj): pick ONE sequence by name
        // or index instead of flattening everything (overlapping record
        // ranges across sequences would refuse in the overlap check).
        if (p.sequenceName !== undefined) {
          const hit = sequences.find((sq) => sq.name === p.sequenceName);
          if (!hit) throw new Error(`sequenceName ${JSON.stringify(p.sequenceName)} not found — available: ${sequences.map((sq) => sq.name).join(', ')}`);
          return hit.events;
        }
        if (p.sequenceIndex !== undefined) {
          if (p.sequenceIndex < 0 || p.sequenceIndex >= sequences.length) throw new Error(`sequenceIndex ${p.sequenceIndex} out of range (${sequences.length} sequences)`);
          return sequences[p.sequenceIndex].events;
        }
        if (sequences.length > 1) {
          const nonEmpty = sequences.filter((sq) => (sq.events || []).length);
          if (nonEmpty.length > 1) throw new Error(
            `the file holds ${nonEmpty.length} sequences with events — pass sequenceName or sequenceIndex ` +
            `(available: ${sequences.map((sq, i) => `${i}:${sq.name}`).join(', ')})`);
          if (nonEmpty.length === 1) return nonEmpty[0].events;
        }
        return sequences.flatMap((sq) => sq.events || []);
      };
      if (p.format === 'aaf') {
        // BUG FIX (v2.126.0): this branch used to fall through to the sync
        // parseInterchange, which THROWS for aaf — the tool-layer AAF route
        // never worked before.
        if (!p.path) return { error: 'aaf input requires path' };
        const { parseAafDocument } = await import('../aaf.mjs');
        const parsed = await parseAafDocument(p.path);
        events = pickSequence(parsed.sequences);
      } else if (p.format === 'prproj') {
        // Premiere: offline gunzip+graph read (no Premiere, no Resolve
        // import path).
        if (!p.path) return { error: 'prproj input requires path' };
        const { parsePrprojDoc } = await import('../prproj.mjs');
        events = pickSequence(parsePrprojDoc(p.path).sequences);
      } else if (!content) {
        if (!p.path) return { error: 'provide content or path' };
        content = await fs.readFile(p.path, 'utf8');
      }
      if (!events) events = parseInterchange(p.format, content, { fps: p.fps ?? 24 });
      if (!events || !events.length) return { error: 'no events parsed from the interchange input' };
      const { spec, report } = eventsToAssembleSpec(events, {
        sourceMap: p.sourceMap, timelineName: p.timelineName,
        preserveStartTimecode: p.preserveStartTimecode,
      });
      if (p.targetAppVersion !== undefined) {
        spec.templateVersion = parseFloat(p.targetAppVersion) >= 21 ? 21 : 19;
      }
      if (p.subtitlesSrtPath) {
        spec.subtitlesSrt = await fs.readFile(p.subtitlesSrtPath, 'utf8');
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
          'Import with timeline.import_timeline_checked (timeline is named after the FILE). Dissolves/cross-fades, forward+reverse retimes, multi-track video, audio events and markers are AUTHORED when geometry allows; everything else drops WITH a reason — see `conform` for the ledger.',
      };
    }
    if (action === 'assemble_project') {
      // MULTI-TIMELINE archive (E85): assemble each timeline spec with the
      // full single-timeline engine, then merge the later archives into the
      // first — SeqContainers copied wholesale, MpFolder elements merged with
      // DbId dedup (captured media templates carry FIXED pool DbIds, so the
      // same source assembled twice IS the same element and every clip's
      // MediaRef already points at it), and LocableBlobSet marker blobs
      // carried over. Import the result as a PROJECT
      // (project_manager.import_project / safe_project_import) — the
      // single-timeline .drt import path only takes one timeline per file.
      const p = z.object({
        timelines: z.array(z.object({}).passthrough()).min(2)
          .describe('Two or more assembleTimeline specs (same shape as `assemble` spec); timelineName required and unique per entry'),
        outputPath: z.string().describe('Where the multi-timeline .drp is written'),
        targetAppVersion: z.union([z.string(), z.number()]).optional(),
      }).parse(args);
      const names = p.timelines.map((t, i) => t.timelineName || `Timeline ${i + 1}`);
      if (new Set(names).size !== names.length) throw new Error(`assemble_project: timelineName must be unique per timeline (got: ${names.join(', ')})`);
      const { assembleTimeline } = drp();
      const buffers = [];
      for (const [i, spec] of p.timelines.entries()) {
        const s = { ...spec, timelineName: names[i] };
        if (s.templateVersion === undefined && p.targetAppVersion !== undefined) {
          s.templateVersion = parseFloat(p.targetAppVersion) >= 21 ? 21 : 19;
        }
        buffers.push((await assembleTimeline(s)).buffer);
      }
      // Every assembly reuses the TEMPLATE's fixed identities across the
      // whole TIMELINE CLUSTER — pool clip element (which nests a version
      // table with back-references: MpTimelineClip, pActive, UniqueSequenceId,
      // UniqueMediaPoolItemId, numeric IDs), the parent container, its shared
      // sequence and track ids — so archives 2..n silently collide with
      // archive 1 (measured twice: the merge imported as ONE timeline, first
      // via container overwrite, then via UniqueMediaPoolItemId dedup).
      // Rather than freshening named fields one by one, remap EVERY uuid the
      // later archive's cluster shares with the first archive's cluster —
      // except media-element ids, which are shared BY DESIGN (captured
      // templates carry fixed pool DbIds so identical sources dedup and
      // MediaRefs keep pointing at the survivor). The keyed SeqRef inside the
      // pool clip's embedded sequence blob is patched through the codec.
      const { createRequire } = await import('node:module');
      const requireCjs = createRequire(import.meta.url);
      const { decodeKeyedDict, encodeKeyedDict } = requireCjs('../../vendor/drp-format/keyed-dict.js');
      const { randomUUID } = await import('node:crypto');
      const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g;
      const TL_EL_RE = /<Element>\s*<Sm2MpTimelineClip DbId="[^"]+">[\s\S]*?<\/Sm2MpTimelineClip>\s*<\/Element>/g;
      // Media pool elements: Sm2MpVideoClip/Sm2MpAudioClip (captured
      // template media — the tag is NOT Sm2MpMedia; measured the hard way
      // when an over-narrow pattern left media ids in the remap set and
      // every item MediaRef in the merged reel went dangling → offline)
      // plus Sm2MpCompoundClip clusters.
      const MEDIA_EL_RE = /<Element>\s*<Sm2Mp(?:VideoClip|AudioClip|Media|CompoundClip) DbId="[^"]+">[\s\S]*?<\/Sm2Mp(?:VideoClip|AudioClip|Media|CompoundClip)>\s*<\/Element>/g;
      const base = await JSZip.loadAsync(buffers[0]);
      const mpP = 'MediaPool/Master/MpFolder.xml';
      let mpXml = await base.file(mpP).async('string');
      let pjXml = await base.file('project.xml').async('string');
      const baseIds = new Set((mpXml + pjXml).match(UUID_RE) || []);
      for (const n of Object.keys(base.files)) {
        if (!base.files[n].dir && /SeqContainer\/.+\.xml$/.test(n)) {
          for (const id of (await base.file(n).async('string')).match(UUID_RE) || []) baseIds.add(id);
        }
      }
      let nextPoolId = 101; // template pool clips carry <ID>100</ID>
      for (const buf of buffers.slice(1)) {
        const zip = await JSZip.loadAsync(buf);
        let mp2 = await zip.file(mpP).async('string');
        const mediaEls = mp2.match(MEDIA_EL_RE) || [];
        const mediaIds = new Set(mediaEls.flatMap((el) => el.match(UUID_RE) || []));
        const tlEl = (mp2.match(TL_EL_RE) || [])[0];
        if (!tlEl) throw new Error('assemble_project: merged archive has no timeline pool clip');
        // cluster text: the pool clip element + every SeqContainer entry
        const containers = {};
        for (const n of Object.keys(zip.files)) {
          if (!zip.files[n].dir && /SeqContainer\/.+\.xml$/.test(n)) containers[n] = await zip.file(n).async('string');
        }
        const clusterText = tlEl + Object.values(containers).join('');
        const remap = new Map();
        for (const id of new Set(clusterText.match(UUID_RE) || [])) {
          if (baseIds.has(id) && !mediaIds.has(id)) remap.set(id, randomUUID());
        }
        const apply = (text) => { let t = text; for (const [a, b] of remap) t = t.split(a).join(b); return t; };
        // Keyed FieldsBlobs store uuid VALUES as UTF-16 — invisible to the
        // plaintext remap. (Measured the hard way: the pool clip's top
        // FieldsBlob is keyed {ActiveVer→uuid}; left unpatched it pointed
        // REEL_02's active version at REEL_01's cluster and the timeline
        // silently never materialized.) Decode every keyed blob, remap any
        // string entry matching a remapped uuid, re-encode. Non-keyed blobs
        // (zstd bodies etc.) decode-fail and pass through untouched.
        const applyBlobs = (text) => text.replace(/<FieldsBlob>([0-9a-fA-F]+)<\/FieldsBlob>/g, (whole, hex) => {
          try {
            const dict = decodeKeyedDict(Buffer.from(hex, 'hex'));
            let changed = false;
            for (const e of dict.entries) {
              if (typeof e.value === 'string' && remap.has(e.value)) { e.value = remap.get(e.value); changed = true; }
            }
            if (!changed) return whole;
            return `<FieldsBlob>${encodeKeyedDict({ hdr: dict.hdr, entries: dict.entries }).toString('hex')}</FieldsBlob>`;
          } catch { return whole; }
        });
        // pool clip: uuid remap + keyed SeqRef patch + fresh numeric IDs
        let tlNew = applyBlobs(apply(tlEl)).replace(/<ID>\d+<\/ID>/g, `<ID>${nextPoolId}<\/ID>`.replace('<\/ID>', '</ID>'));
        nextPoolId += 1;
        const fbM = tlNew.match(/(<Sm2Sequence DbId="[^"]+">\s*<FieldsBlob>)([0-9a-fA-F]+)(<\/FieldsBlob>)/);
        if (fbM) {
          const dict = decodeKeyedDict(Buffer.from(fbM[2], 'hex'));
          const seqRef = dict.entries.find((e) => e.key === 'SeqRef');
          if (seqRef && remap.has(String(seqRef.value))) {
            seqRef.value = remap.get(String(seqRef.value));
            tlNew = tlNew.replace(fbM[0], `${fbM[1]}${encodeKeyedDict({ hdr: dict.hdr, entries: dict.entries }).toString('hex')}${fbM[3]}`);
          }
        }
        for (const [n, xml] of Object.entries(containers)) {
          const remapped = applyBlobs(apply(xml));
          const cid = (remapped.match(/<Sm2SequenceContainer DbId="([^"]+)"/) || [])[1];
          base.file(cid ? `SeqContainer/${cid}.xml` : n, remapped);
        }
        // Children live INSIDE <MediaVec> — an element appended after its
        // close parses fine and is silently invisible (measured: the whole
        // REEL_02 subtree vanished while every id chain checked out).
        mpXml = mpXml.replace('</MediaVec>', `${tlNew}\n</MediaVec>`);
        for (const el of mediaEls) {
          const id = el.match(/DbId="([^"]+)"/)[1];
          if (!mpXml.includes(`DbId="${id}"`)) mpXml = mpXml.replace('</MediaVec>', `${el}\n</MediaVec>`);
        }
        const pj2 = await zip.file('project.xml').async('string');
        for (const blob of pj2.match(/<Element>\s*<Sm2(?:Sequence|TiItem)LockableBlob DbId="[^"]+">[\s\S]*?<\/Sm2(?:Sequence|TiItem)LockableBlob>\s*<\/Element>/g) || []) {
          pjXml = pjXml.replace('</LocableBlobSet>', `${apply(blob)}</LocableBlobSet>`);
        }
        // THE timeline registry (found the hard way — two invisible merges):
        // project.xml's <TimelineHandleVec> lists each pool clip's embedded
        // Sm2Timeline DbId; a pool clip absent from the vec imports as pool
        // furniture but never materializes as a timeline. Carry the later
        // archive's handles over, remapped with its cluster.
        const vec2 = pj2.match(/<TimelineHandleVec>([\s\S]*?)<\/TimelineHandleVec>/);
        if (vec2) {
          for (const h of vec2[1].match(/<Element>[^<]*<\/Element>/g) || []) {
            pjXml = pjXml.replace('</TimelineHandleVec>', ` ${apply(h)}\n </TimelineHandleVec>`);
          }
        }
        // future merges must not collide with THIS timeline's fresh ids either
        for (const id of remap.values()) baseIds.add(id);
        for (const id of clusterText.match(UUID_RE) || []) if (!remap.has(id)) baseIds.add(id);
      }
      base.file(mpP, mpXml);
      base.file('project.xml', pjXml);
      let outBuf = await base.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
      let stamped = null;
      if (p.targetAppVersion !== undefined) {
        const targetPV = resolveTargetProjectVersion({ targetAppVersion: p.targetAppVersion });
        const appVer = `${p.targetAppVersion}${'.0'.repeat(Math.max(0, 4 - String(p.targetAppVersion).split('.').length))}`;
        const zip = await JSZip.loadAsync(outBuf);
        const { out, elementPatches, stampPatches } = await applyVersionStamps(zip, targetPV, appVer);
        outBuf = await out.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
        stamped = { targetProjectVersion: targetPV, elementPatches, stampPatches };
      }
      await fs.writeFile(p.outputPath, outBuf);
      return {
        outputPath: p.outputPath, bytes: outBuf.length, timelines: names, stamped,
        note: 'Import as a PROJECT (project_manager.safe_project_import); timeline.import_timeline_checked takes one timeline per file — use drt.extract_from_drp to pull singles.',
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
      // COMPOUND CLIPS: a compound is a pool Sm2MpCompoundClip with an
      // EMBEDDED Sm2Sequence whose tracks live in their OWN SeqContainer —
      // dropping that container ships a compound that imports and reads back
      // but is hollow. Walk MediaRefs of the kept container(s) → compound
      // pool elements → embedded sequence ids → keep those containers too,
      // recursively (compounds nest). Live-proven: a .drt that keeps the
      // inner container renders the compound's content (E45, 19.1.3.7).
      const mpXmlByName = {};
      for (const name of Object.keys(drpZip.files)) {
        if (!drpZip.files[name].dir && name.endsWith('MpFolder.xml')) {
          mpXmlByName[name] = await drpZip.file(name).async('string');
        }
      }
      const seqXmlByEntry = { [keepEntry]: keepXml };
      const keepContainers = new Set([keepEntry]);
      const compoundIds = new Set();
      const queue = [keepXml];
      while (queue.length) {
        const xml = queue.pop();
        for (const m of xml.matchAll(/<MediaRef>([0-9a-f-]{36})<\/MediaRef>/g)) {
          const ref = m[1];
          if (compoundIds.has(ref)) continue;
          for (const mpXml of Object.values(mpXmlByName)) {
            const cm = mpXml.match(new RegExp(`<Sm2MpCompoundClip DbId="${ref}">[\\s\\S]*?</Sm2MpCompoundClip>`));
            if (!cm) continue;
            compoundIds.add(ref);
            const innerSeq = (cm[0].match(/<Sm2Sequence DbId="([0-9a-f-]{36})">/) || [])[1];
            if (!innerSeq) continue;
            for (const entryName of seqEntries) {
              if (keepContainers.has(entryName)) continue;
              const sx = seqXmlByEntry[entryName] ?? (seqXmlByEntry[entryName] = await drpZip.file(entryName).async('string'));
              if (sx.includes(`<Sequence>${innerSeq}</Sequence>`)) {
                keepContainers.add(entryName);
                queue.push(sx);
              }
            }
          }
        }
      }
      const out = new JSZip();
      let droppedTimelines = 0;
      for (const name of Object.keys(drpZip.files)) {
        const entry = drpZip.files[name];
        if (entry.dir) continue;
        if (name === 'Gallery.xml') continue;
        const isSeq = seqEntries.includes(name);
        if (isSeq && !keepContainers.has(name)) continue;
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
