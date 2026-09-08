/**
 * color_trace tool — a better ColorTrace. Match clips between a SOURCE and
 * TARGET timeline (cross-project, identity-aware) → a trace plan mapping each
 * target clip to the source clip whose grade should carry over, plus a lossless
 * .drx per graded match and a plan.json the live server's
 * `timeline_item_color.apply_trace_plan` consumes.
 *
 * Resolve's native ColorTrace matches by TC/name/order within a project and breaks
 * on renames/reorders/retimes. This reads clip lists from ANY project's Project.db
 * (READ-only, no Resolve, even cross-project) and matches on MEDIA IDENTITY first,
 * names last:
 *
 *   media-exact     same media (pool id or file path), same in-point + duration   1.00
 *   media-overlap   same media, overlapping source range (best overlap wins)      0.95
 *   reel-overlap    same reel name, overlapping source range                      0.90
 *   basename-overlap same file name (relocated media), overlapping source range  0.85
 *   media-only      same media, source range unreadable or disjoint              0.70
 *   exact-name      clip name identical                                          0.75
 *   normalized-name clip name identical after version/separator normalisation    0.60
 *
 * A stringout — one long file cut into many graded sections — is the case native
 * ColorTrace loses: every section shares a name and a file. media-overlap picks
 * the section whose source range covers the target's, and flags `ambiguous`
 * when two candidates tie.
 *
 * plan — source timeline + target timeline → { matches[], summary, planPath? }
 */

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { z } from 'zod';
import { resolveDbPath } from '../db-patch.mjs';
import { readTimelineClips } from './project_read.mjs';

const side = (name) => ({
  [`${name}ProjectDb`]: z.string().optional(),
  [`${name}ProjectName`]: z.string().optional(),
  [`${name}Timeline`]: z.string(),
});
const planSchema = z.object({
  ...side('source'),
  ...side('target'),
  emitDir: z
    .string()
    .optional()
    .describe(
      'If set, write a .drx per matched+graded clip here plus plan.json (for timeline_item_color.apply_trace_plan on the live server). Use a temp-dir path: the live apply refuses .drx files outside the system temp dir by default.',
    ),
  minConfidence: z
    .number()
    .min(0)
    .max(1)
    .optional()
    .describe(
      'Matches below this confidence get no .drx and status below-threshold (default 0 — everything is emitted, confidence is reported per match; the live apply has its own gate, default 0.8)',
    ),
});

const xmlEscape = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
// Wrap a grade Body (the DRX-format 0x81+zstd blob from LmVersion.Body) in a FULL
// Gallery::GyStill.drx — the structure Resolve's ApplyGradeFromDRX actually applies.
//
export const drxEnvelope = (label, bodyHex) => {
  const stillId = crypto.randomUUID();
  const verId = crypto.randomUUID();
  return `<?xml version="1.0" encoding="UTF-8"?>
<!--DbAppVer="19.1.3.0007" DbPrjVer="14"-->
<Gallery::GyStill DbId="${stillId}">
 <FieldsBlob/>
 <SrcHint>${xmlEscape(label)}</SrcHint>
 <SrcType>1</SrcType>
 <GalleryPath/>
 <Label>${xmlEscape(label)}</Label>
 <RecTC>01:00:00:00</RecTC>
 <SrcTC>00:00:00:00</SrcTC>
 <DpxDescriptor>50</DpxDescriptor>
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
 <IncludedInRecording>true</IncludedInRecording>
 <FlatPassEnabled>false</FlatPassEnabled>
 <RGBAOutputEnabled>false</RGBAOutputEnabled>
 <Body>${bodyHex}</Body>
 <UseVersionClipProcParams>true</UseVersionClipProcParams>
 </ListMgt::LmVersion>
 </pClipFullVer>
 <PrimaryCCMode>0</PrimaryCCMode>
</Gallery::GyStill>
`;
};

// Normalize a clip name to a match key: drop path + extension, lowercase,
// collapse separators, strip a trailing VERSION token (_v2, -V12). Only a
// v-prefixed token is a version: stripping any trailing number folded
// SHOT_010 and SHOT_020 onto one key and let a name-tier match cross shots.
export function normalize(name) {
  let n = String(name || '')
    .split('/')
    .pop()
    .replace(/\.[^.]+$/, '')
    .toLowerCase();
  n = n.replace(/[_\-.\s]+/g, ' ').trim();
  n = n.replace(/\s+v\d{1,3}$/, '').trim();
  return n;
}

const num = (v) => {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};
const lower = (v) => (v === null || v === undefined ? '' : String(v).trim().toLowerCase());
const basename = (p) => lower(p).split(/[\\/]/).pop();

/** Source-frame range of a clip, or null when the in-point is unreadable. */
function sourceRange(c) {
  const a = num(c.sourceIn);
  const d = num(c.duration);
  if (a === null || d === null || d <= 0) return null;
  return [a, a + d];
}
function overlapFrames(r1, r2) {
  if (!r1 || !r2) return 0;
  return Math.max(0, Math.min(r1[1], r2[1]) - Math.max(r1[0], r2[0]));
}

const TIERS = [
  // [method, confidence, key(clip) → string|null, needsOverlap]
  ['media-exact', 1.0, null, 'exact'],
  ['media-overlap', 0.95, null, 'overlap'],
  ['reel-overlap', 0.9, (c) => lower(c.reel) || null, 'overlap'],
  ['basename-overlap', 0.85, (c) => basename(c.mediaPath) || null, 'overlap'],
  ['exact-name', 0.75, (c) => (c.name ? String(c.name) : null), 'none'],
  ['media-only', 0.7, null, 'none'],
  ['normalized-name', 0.6, (c) => normalize(c.name) || null, 'none'],
];

/** Media identity keys a clip answers to: its pool item id and its file path.
 * Either equal on both sides means "the same media". */
function mediaKeys(c) {
  const keys = [];
  if (c.poolId) keys.push(`pool:${lower(c.poolId)}`);
  if (c.mediaPath) keys.push(`path:${lower(c.mediaPath)}`);
  return keys;
}

function buildIndex(clips) {
  const idx = { media: new Map(), tiers: new Map() };
  const add = (map, k, c) => {
    if (!k) return;
    if (!map.has(k)) map.set(k, []);
    map.get(k).push(c);
  };
  for (const c of clips) {
    for (const k of mediaKeys(c)) add(idx.media, k, c);
    for (const [method, , keyFn] of TIERS) {
      if (!keyFn) continue;
      if (!idx.tiers.has(method)) idx.tiers.set(method, new Map());
      add(idx.tiers.get(method), keyFn(c), c);
    }
  }
  return idx;
}

/** Candidates that share media identity with the target (deduped). */
function mediaCandidates(target, idx) {
  const seen = new Set();
  const out = [];
  for (const k of mediaKeys(target)) {
    for (const c of idx.media.get(k) || []) {
      const id = c.itemId || c;
      if (seen.has(id)) continue;
      seen.add(id);
      out.push(c);
    }
  }
  return out;
}

/** Pick the best candidate by source-range overlap. Ties (identical overlap)
 * fall to the nearest record start and are flagged ambiguous. */
function bestByOverlap(target, candidates) {
  const tr = sourceRange(target);
  if (!tr) return null;
  let best = null;
  let bestOv = 0;
  let ties = 0;
  for (const c of candidates) {
    const ov = overlapFrames(tr, sourceRange(c));
    if (ov <= 0) continue;
    if (ov > bestOv) {
      best = c;
      bestOv = ov;
      ties = 0;
    } else if (ov === bestOv) {
      ties += 1;
      const d = (x) => Math.abs(num(x.start) - num(target.start));
      if (d(c) < d(best)) best = c;
    }
  }
  if (!best) return null;
  return { src: best, overlap: bestOv, fraction: bestOv / (tr[1] - tr[0]), ambiguous: ties > 0, candidates: candidates.length };
}

/** Match ONE target clip against the source index. Returns
 * { src, method, confidence, ambiguous, candidates, sourceOverlap? } — src null when unmatched. */
export function matchClip(target, idx) {
  const tr = sourceRange(target);
  const tDur = num(target.duration);
  const media = mediaCandidates(target, idx);

  for (const [method, confidence, keyFn, mode] of TIERS) {
    let candidates;
    if (keyFn) candidates = idx.tiers.get(method)?.get(keyFn(target)) || [];
    else candidates = media;
    if (!candidates.length) continue;

    if (mode === 'exact') {
      const hits = candidates.filter((c) => tr && num(c.sourceIn) === tr[0] && num(c.duration) === tDur);
      if (!hits.length) continue;
      const src =
        hits.length === 1 ? hits[0] : hits.reduce((a, b) => (Math.abs(num(b.start) - num(target.start)) < Math.abs(num(a.start) - num(target.start)) ? b : a));
      return { src, method, confidence, ambiguous: hits.length > 1, candidates: hits.length, sourceOverlap: { frames: tDur, fraction: 1 } };
    }
    if (mode === 'overlap') {
      const b = bestByOverlap(target, candidates);
      if (!b) continue;
      return {
        src: b.src,
        method,
        confidence,
        ambiguous: b.ambiguous,
        candidates: b.candidates,
        sourceOverlap: { frames: b.overlap, fraction: Number(b.fraction.toFixed(4)) },
      };
    }
    // mode 'none' — first candidate, nearest record start on ties.
    const src =
      candidates.length === 1
        ? candidates[0]
        : candidates.reduce((a, b) => (Math.abs(num(b.start) - num(target.start)) < Math.abs(num(a.start) - num(target.start)) ? b : a));
    return { src, method, confidence, ambiguous: candidates.length > 1, candidates: candidates.length };
  }
  return { src: null, method: null, confidence: 0, ambiguous: false, candidates: 0 };
}

/** Match every target clip against the source clips (pure; no DB). */
export function matchClips(srcClips, tgtClips) {
  const idx = buildIndex(srcClips);
  return tgtClips.map((t) => ({ target: t, ...matchClip(t, idx) }));
}

const clipRef = (c) => ({
  name: c.name,
  start: num(c.start),
  duration: num(c.duration),
  sourceIn: num(c.sourceIn),
  reel: c.reel || null,
  mediaPath: c.mediaPath || null,
  poolId: c.poolId || null,
});

export const colorTraceTool = {
  name: 'color_trace',
  description:
    'Better ColorTrace — match clips between a SOURCE and TARGET timeline (cross-project, from Project.db, read-only, no Resolve) on media identity (pool id / file path / reel / file name + source-range overlap), names last → a trace plan with a lossless .drx per graded match and a plan.json for timeline_item_color.apply_trace_plan on the live server. Action: plan.',
  async handler({ action, args }) {
    if (action === 'plan') {
      const p = planSchema.parse(args);
      const srcDb = resolveDbPath({ projectDb: p.sourceProjectDb, projectName: p.sourceProjectName });
      const tgtDb = resolveDbPath({ projectDb: p.targetProjectDb, projectName: p.targetProjectName });
      const srcClips = readTimelineClips(srcDb, p.sourceTimeline, 'video', true); // includeGrade
      const tgtClips = readTimelineClips(tgtDb, p.targetTimeline, 'video');
      if (!srcClips.length) throw new Error(`source timeline "${p.sourceTimeline}" has no video clips`);
      if (!tgtClips.length) throw new Error(`target timeline "${p.targetTimeline}" has no video clips`);
      if (p.emitDir) fs.mkdirSync(p.emitDir, { recursive: true });
      const minConfidence = p.minConfidence ?? 0;

      const byMethod = { unmatched: 0 };
      for (const [m] of TIERS) byMethod[m] = 0;
      let gradesReady = 0;
      let ambiguous = 0;
      let belowThreshold = 0;
      const matches = matchClips(srcClips, tgtClips).map((m, i) => {
        const t = m.target;
        byMethod[m.method || 'unmatched'] += 1;
        if (m.ambiguous) ambiguous += 1;
        let gradeApply = null;
        if (m.src && m.confidence < minConfidence) {
          belowThreshold += 1;
          gradeApply = { status: 'below-threshold', sourceClip: m.src.name, confidence: m.confidence, minConfidence };
        } else if (m.src && m.src.gradeBody) {
          gradesReady += 1;
          gradeApply = { status: 'ready', sourceClip: m.src.name, sourceVersion: m.src.gradeVersion || null };
          if (p.emitDir) {
            // emit a .drx (lossless source-grade pass-through) for ApplyGradeFromDRX onto the target clip.
            const drxPath = path.join(p.emitDir, `trace-${String(i).padStart(4, '0')}.drx`);
            fs.writeFileSync(drxPath, drxEnvelope(m.src.name, m.src.gradeBody));
            gradeApply.drxPath = drxPath;
            gradeApply.applyVia = {
              api: 'timeline_item_color.apply_trace_plan',
              target: { timeline: p.targetTimeline, clipName: t.name, start: num(t.start), duration: num(t.duration) },
            };
          }
        } else if (m.src) {
          gradeApply = { status: 'no-source-grade', sourceClip: m.src.name };
        }
        return {
          index: i,
          target: clipRef(t),
          source: m.src ? clipRef(m.src) : null,
          method: m.method,
          confidence: m.confidence,
          ambiguous: m.ambiguous,
          candidates: m.candidates,
          sourceOverlap: m.sourceOverlap || null,
          gradeApply,
        };
      });
      const matched = matches.filter((m) => m.source).length;
      const result = {
        source: { projectDb: srcDb, timeline: p.sourceTimeline, clips: srcClips.length, graded: srcClips.filter((c) => c.gradeBody).length },
        target: { projectDb: tgtDb, timeline: p.targetTimeline, clips: tgtClips.length },
        summary: { matched, unmatched: tgtClips.length - matched, gradesReady, ambiguous, belowThreshold, byMethod },
        emitDir: p.emitDir || null,
        planPath: null,
        matches,
      };
      if (p.emitDir) {
        result.planPath = path.join(p.emitDir, 'plan.json');
        fs.writeFileSync(result.planPath, JSON.stringify({ kind: 'color_trace.plan', createdAt: new Date().toISOString(), ...result }, null, 2));
      }
      return result;
    }
    throw new Error(`Unknown color_trace action: ${action}`);
  },
};
