/**
 * conform tool — conform/relink QC engine (the offline core of the conform-qc library).
 *
 * Core principle: a filename match is NOT a conform — the only truth is the frame
 * the target tool actually shows (the Oracle), compared to a reference.
 *
 * Offline (pure, no deps beyond fast-xml-parser):
 * parse_geometry — turnover XML (XMEML/FCP7) → per-clip geometry/conform fields
 * oracle_derive — clip + context → the frame Resolve will show + transform (per target)
 * list_targets — supported target tools + their frame-math
 * repair_ladder — the strategy ladder (diagnosis order) for relink repair
 * build_manifest — conformed clips → relink manifest
 * report — build a per-cut QC report
 *
 * Gated (needs optional `sharp` for brightness-robust frame compare):
 * verify — math + frame-compare verification (lazy; clear error if sharp absent)
 *
 * Frame sampling + live `clip_where` read-back (the cloud/local adapters) are NOT
 * part of this offline tool — those belong to the live Python MCP / a Resolve session.
 */

import fs from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { z } from 'zod';
import { createRequire } from 'node:module';
import { hasSharp } from '../capabilities.mjs';

const require = createRequire(import.meta.url);
const V = '../../vendor/conform-qc';
const parse = require(`${V}/parse/index.js`);
const oracle = require(`${V}/oracle/index.js`);
const repair = require(`${V}/repair/index.js`);
const packaging = require(`${V}/packaging/index.js`);
const report = require(`${V}/report/index.js`);
const { MediaIndex } = require(`${V}/repair/media-index.js`);
const { surgicalRelink } = require(`${V}/packaging/surgical-relink.js`);
const { analyzeMediaList } = require(`${V}/repair/media-analysis.js`);
import { locateReverseClip, writeReverseClip, calibrateK, inForTarget } from '../reverse-clip-db.mjs';
import * as lineage from '../lineage-db.mjs';

const pgScope = z
  .object({
    host: z.string().optional(),
    IpAddress: z.string().optional(),
    port: z.number().int().optional(),
    user: z.string().optional(),
    password: z.string().optional(),
    database: z.string().optional(),
    DbName: z.string().optional(),
  })
  .optional()
  .describe('PostgreSQL connection (studio DB) instead of a SQLite projectDb');

const fixReverseSchema = z
  .object({
    projectDb: z.string().optional().describe('SQLite Project.db path (or pass postgres)'),
    postgres: pgScope,
    timelineId: z.string().optional().describe('Sm2Timeline_id (preferred)'),
    timelineName: z.string().optional(),
    mediaPathContains: z.string().describe('Source-name fragment to find the reversed clip (e.g. "A01-A03")'),
    mode: z.enum(['locate', 'fix']).default('locate'),
    itemId: z.string().optional().describe('fix: the reversed Sm2TiItem id from a locate call'),
    targetFrame: z.number().int().optional().describe('fix: desired get_source_start_frame (oracle = (masterFrames-1-endoffset)-in)'),
    K: z.number().optional().describe('fix: mirror constant (displayed = K - In); if absent, supply probeIn+displayedAtProbe, else this is a probe'),
    probeIn: z.number().int().optional().describe('fix: In set during calibration probe (default = targetFrame)'),
    displayedAtProbe: z.number().int().optional().describe('fix: the get_source_start_frame read AFTER a probe reopen (solves K)'),
    restoreReverse: z.boolean().optional().describe('fix: copy a generic reverse MediaTimemapBA blob (default true)'),
    blobSourceItemId: z.string().optional().describe('fix: override the reverse-blob source item'),
    iConfirmProjectClosed: z.boolean().optional().describe('fix: required true — close the project in Resolve first'),
  })
  .refine((a) => a.projectDb || a.postgres, { message: 'provide projectDb or postgres' });

const parseSchema = z
  .object({
    filePath: z.string().optional().describe('Turnover file (XMEML/FCP7 XML)'),
    content: z.string().optional().describe('Turnover XML content (alternative to filePath)'),
    format: z.enum(['xmeml', 'otio', 'aaf']).optional().describe('default xmeml'),
  })
  .refine((a) => a.filePath || a.content, { message: 'provide filePath or content' });

const deriveSchema = z.object({
  clip: z.object({}).passthrough().describe('A parsed clip (geometry/conform fields)'),
  ctx: z.object({}).passthrough().describe('Context: { seqResolution, fps,... }'),
  target: z.string().optional().describe('Target tool id (default resolve)'),
});

const manifestSchema = z.object({ conformed: z.array(z.object({}).passthrough()), opts: z.object({}).passthrough().optional() });
const reportSchema = z.object({ meta: z.object({}).passthrough().optional(), cuts: z.array(z.object({}).passthrough()).optional() });

export const conformTool = {
  name: 'conform',
  description:
    'Conform/relink QC engine (offline core). Actions: parse_geometry, oracle_derive, list_targets, repair_ladder, build_manifest, analyze_media (ffprobe target media → res/aspect/codec/bitdepth/fps + quality rank), relink_scalefix (surgical: repoint proxy→highres pathurls + fix the scale double-count per clip, preserving retimes/tracks/audio byte-for-byte; index MULTIPLE footage roots via footageDirs, PROXY excluded; returns warnings.leftOnProxyOrTest + unresolvedSources so a source stuck on its proxy cannot slip through), report; verify (gated on optional sharp); fix_reverse_clip (LIVE DB patch — restore a reversed clip dropped on import: copy a generic reverse MediaTimemapBA blob + set the mirrored "In"; SQLite or PostgreSQL; project must be CLOSED; locate→probe→calibrate K→apply); snapshot (sequence LINEAGE store — ingest_xml/ingest_live an editorial-or-conform XML or a live timeline into one content-hashed schema, then list/diff/show/rollback_plan; the diff is the incremental frame-QC worklist); qc (comprehensive per-cut frame diff vs the reference render → MATCH/OFFSET/WRONG/REF_OFFLINE/UNREADABLE cached per snapshot; conform frame is sampled at the oracle source frame AND scale-corrected to the edit framing before diffing, so reversed/scaled clips compare apples-to-apples; REF_OFFLINE = the reference is black/flat at that record position because the shot was offline upstream in editorial — inconclusive, NOT a conform error; op run [ffmpeg+sharp] / markers [red conform / yellow turnover / blue ref-offline / cyan review marker plan] / propagate [carry unchanged verdicts to a new snapshot]). Frame-math is the truth, not filename matches.',
  async handler({ action, args }) {
    if (action === 'parse_geometry') {
      const p = parseSchema.parse(args);
      const xml = p.content != null ? p.content : await fs.readFile(p.filePath, 'utf8');
      if (p.format === 'otio') return parse.parseGeometryOTIO(xml);
      if (p.format === 'aaf') return parse.parseGeometryAAF(xml);
      return parse.parseGeometry(xml);
    }
    if (action === 'oracle_derive') {
      const p = deriveSchema.parse(args);
      return oracle.derive(p.clip, p.ctx, p.target || oracle.DEFAULT_TARGET);
    }
    if (action === 'list_targets') {
      return { targets: oracle.TARGETS, default: oracle.DEFAULT_TARGET };
    }
    if (action === 'repair_ladder') {
      const p = z.object({ opts: z.object({}).passthrough().optional() }).parse(args);
      const ladder = repair.makeRepairLadder(p.opts || {});
      return {
        order: repair.DEFAULT_ORDER,
        strategies: Object.keys(repair.strategies || {}),
        ladder: typeof ladder === 'object' ? Object.keys(ladder) : ladder,
      };
    }
    if (action === 'build_manifest') {
      const p = manifestSchema.parse(args);
      return packaging.buildManifest(p.conformed, p.opts || {});
    }
    if (action === 'report') {
      const p = reportSchema.parse(args);
      let r = report.makeReport(p.meta || {});
      for (const cut of p.cuts || []) r = report.addCut(r, cut);
      return r;
    }
    if (action === 'analyze_media') {
      const p = z.object({ paths: z.array(z.string()).min(1).describe('Media file paths to probe (ffprobe)') }).parse(args);
      return { media: analyzeMediaList(p.paths) };
    }
    if (action === 'relink_scalefix') {
      const p = z
        .object({
          filePath: z.string().describe('Turnover XMEML to relink + scale-correct'),
          footageDir: z.string().optional().describe('A single high-res tree to index'),
          footageDirs: z
            .array(z.string())
            .optional()
            .describe('MULTIPLE high-res roots to index (index ALL of them — a source in a folder you forgot stays stuck on its proxy)'),
          media: z.array(z.object({ path: z.string(), basename: z.string().optional() }).passthrough()).optional(),
          sequenceWidth: z.number().describe('Sequence width, for the scale double-count fix'),
          sequenceHeight: z.number().describe('Sequence height — needed for the aspect-aware scaleToFit fix'),
          minScore: z.number().optional(),
          outPath: z.string().optional().describe('If set, write the transformed XML here'),
          indexExcludeMarkers: z
            .array(z.string())
            .optional()
            .describe('Path fragments to EXCLUDE from the footage index (default ["/PROXY/"]) so relink targets highres, not proxies'),
          proxyMarkers: z
            .array(z.string())
            .optional()
            .describe('Case-insensitive path fragments that mark a proxy/test path (default ["PROXY","TEST"]) — flagged as left-on-proxy after relink'),
        })
        .refine((a) => a.footageDir || a.footageDirs || a.media, { message: 'provide footageDir, footageDirs, or media' })
        .parse(args);
      const xml = await fs.readFile(p.filePath, 'utf8');
      const excludeMarkers = p.indexExcludeMarkers || ['/PROXY/'];
      const proxyMarkers = (p.proxyMarkers || ['PROXY', 'TEST']).map((m) => m.toLowerCase());
      let media = p.media;
      if (!media) {
        const roots = p.footageDirs && p.footageDirs.length ? p.footageDirs : [p.footageDir];
        const r = spawnSync('find', [...roots, '-iname', '*.mov', '-o', '-iname', '*.mp4'], { encoding: 'utf8', maxBuffer: 256 * 1024 * 1024 });
        if (r.status !== 0) throw new Error(`conform.relink_scalefix: find failed in [${roots.join(', ')}]: ${(r.stderr || '').slice(-200)}`);
        const seen = new Set();
        media = r.stdout
          .split('\n')
          .filter((l) => l && !l.includes('/._') && !excludeMarkers.some((m) => l.includes(m)))
          .filter((path) => (seen.has(path) ? false : (seen.add(path), true)))
          .map((path) => ({ path, basename: path.split('/').pop() }));
      } else {
        media = media.map((m) => ({ ...m, basename: m.basename || m.path.split('/').pop() }));
      }
      const index = new MediaIndex(media);
      const res = surgicalRelink(xml, index, { sequenceWidth: p.sequenceWidth, sequenceHeight: p.sequenceHeight, minScore: p.minScore });
      if (p.outPath) await fs.writeFile(p.outPath, res.xml);
      // Warn on any source still on a proxy/test path — the 0913 footprint: a clip
      // left unresolved (not in the index) stays stuck on its proxy pathurl.
      const pathurls = [...new Set([...res.xml.matchAll(/<pathurl>([^<]*)<\/pathurl>/g)].map((m) => decodeURIComponent(m[1])))];
      const leftOnProxyOrTest = pathurls.filter((u) => proxyMarkers.some((mk) => u.toLowerCase().includes(mk)));
      const warnings = {
        unresolvedSources: (res.relink.unresolved || []).map((u) => u.basename || u.id),
        leftOnProxyOrTest,
        hasIssues: (res.relink.unresolved || []).length > 0 || leftOnProxyOrTest.length > 0,
      };
      const { xml: outXml, ...summary } = res;
      return {
        ...summary,
        warnings,
        mediaIndexed: media.length,
        indexRoots: p.media ? null : p.footageDirs || [p.footageDir],
        outPath: p.outPath || null,
        xml: p.outPath ? undefined : outXml,
      };
    }
    if (action === 'verify') {
      if (!hasSharp()) throw new Error("conform.verify (brightness-robust frame compare) needs the optional dep 'sharp'. Install: npm i sharp");
      const verifyFn = require(`${V}/ops/verify.js`).verify;
      const p = z.object({ model: z.object({}).passthrough(), opts: z.object({}).passthrough().optional() }).parse(args);
      return verifyFn(p.model, p.opts || {});
    }
    if (action === 'fix_reverse_clip') {
      const p = fixReverseSchema.parse(args);
      const scope = { projectDb: p.projectDb, postgres: p.postgres };
      const locate = (extra = {}) =>
        locateReverseClip({ ...scope, timelineId: p.timelineId, timelineName: p.timelineName, mediaPathContains: p.mediaPathContains, ...extra });
      if (p.mode === 'locate') return locate();
      // mode 'fix' (project must be CLOSED)
      if (!p.itemId) throw new Error("fix needs itemId — run mode 'locate' first and pick the reversed clip");
      if (p.targetFrame == null && p.probeIn == null) throw new Error('fix needs targetFrame (or probeIn to calibrate)');
      const restoreReverse = p.restoreReverse !== false;
      let blobSourceItemId = p.blobSourceItemId;
      if (restoreReverse && !blobSourceItemId) {
        const loc = await locate();
        blobSourceItemId = loc.blobSource && loc.blobSource.id;
        if (!blobSourceItemId)
          throw new Error('no generic reverse blob source for this media — pass blobSourceItemId (a reversed clip of the same media in any project)');
      }
      let K = p.K;
      if (K == null && p.probeIn != null && p.displayedAtProbe != null) K = calibrateK(p.probeIn, p.displayedAtProbe);
      let setIn;
      let calibration = null;
      if (K != null && p.targetFrame != null) {
        setIn = inForTarget(K, p.targetFrame);
      } else {
        setIn = p.probeIn != null ? p.probeIn : p.targetFrame; // probe
        calibration = {
          needsCalibration: true,
          probeIn: setIn,
          hint: 'Reopen the project, read get_source_start_frame (= displayed), then call fix again with probeIn + displayedAtProbe (or K = probeIn + displayed) and targetFrame to land the frame.',
        };
      }
      const res = await writeReverseClip({
        ...scope,
        itemId: p.itemId,
        setIn,
        restoreBlobFromItemId: restoreReverse ? blobSourceItemId : undefined,
        iConfirmProjectClosed: p.iConfirmProjectClosed,
      });
      return { ...res, setIn, K: K ?? null, targetFrame: p.targetFrame ?? null, restoredReverseFrom: restoreReverse ? blobSourceItemId : null, calibration };
    }
    if (action === 'snapshot') {
      const p = z
        .object({
          lineageDb: z.string().describe('Path to the lineage SQLite sidecar'),
          op: z.enum(['ingest_xml', 'ingest_live', 'list', 'diff', 'show', 'rollback_plan']),
        })
        .passthrough()
        .parse(args);
      const a = args;
      if (p.op === 'ingest_xml') return lineage.ingestXml(a.lineageDb, a.xmlPath, a);
      if (p.op === 'ingest_live') return await lineage.ingestLiveTimeline(a.lineageDb, a);
      if (p.op === 'list') return { snapshots: lineage.listSnapshots(a.lineageDb, { reel: a.reel }) };
      if (p.op === 'show') return lineage.getSnapshot(a.lineageDb, a.snapshotId);
      if (p.op === 'diff') return lineage.diffSnapshots(a.lineageDb, a.aId, a.bId);
      if (p.op === 'rollback_plan') return lineage.rollbackPlan(a.lineageDb, a.currentId, a.targetId);
      throw new Error(`unknown snapshot op: ${p.op}`);
    }
    if (action === 'qc') {
      const a = args;
      const op = a.op || 'run';
      const qc = await import('../qc-frame.mjs');
      if (op === 'markers') return { markers: qc.markerPlan(a.lineageDb, a.snapshotId, a.referenceRef ?? null) };
      if (op === 'propagate') return qc.propagateVerdicts(a.lineageDb, a.fromSnapshotId, a.toSnapshotId, a.referenceRef ?? null);
      // op === 'run' — comprehensive per-cut frame diff vs the reference (ffmpeg + sharp).
      if (!hasSharp()) throw new Error("conform.qc run needs the optional dep 'sharp' (frame decode). Install: npm i sharp");
      const { makeSamplers } = await import('../qc-sampler.mjs');
      const need = ['lineageDb', 'snapshotId', 'referenceMovie', 'seqW', 'seqH', 'hrW', 'hrH'];
      for (const k of need) if (a[k] == null) throw new Error(`conform.qc run needs ${k}`);
      const s = makeSamplers(a);
      // basic satisfiability: a sampled-null conform = source can't deliver → handled as turnover upstream
      const satisfiability = (cut) => {
        const src = (a.mediaMap && a.mediaMap[cut.source_basename]) || cut.source_path;
        const fsmod = require('node:fs');
        return { sourceOnline: src ? fsmod.existsSync(src) : false, frameInRange: true, aspectOk: true };
      };
      return await qc.qcSnapshot(a.lineageDb, a.snapshotId, {
        referenceRef: a.referenceRef ?? a.referenceMovie,
        width: s.width,
        height: s.height,
        mask: s.mask,
        sampleConform: s.sampleConform,
        sampleReference: s.sampleReference,
        satisfiability,
        incremental: a.incremental,
        now: a.now,
      });
    }
    throw new Error(`Unknown conform action: ${action}`);
  },
};
