/**
 * Frame-level QC (Phases 6–7) — the pixel adjudicator on top of the lineage store.
 * Per cut: a sampled conform frame (highres @oracle frame, transform applied) vs a
 * sampled reference frame (@record position, burn-in masked) → brightness-robust SSIM
 * classify → MATCH/OFFSET/WRONG/REF_OFFLINE/UNREADABLE → category (ok / offset /
 * red-conform / yellow-turnover / blue-ref-offline / review). Verdicts cache in the
 * lineage store; the snapshot diff makes re-runs incremental (only changed cuts re-compared).
 *
 * REF_OFFLINE: the reference frame is (near-)black/flat over its non-burn-in area, so the
 * shot was offline/black UPSTREAM (editorial never rendered it). The reference cannot
 * adjudicate — flagged inconclusive (Blue), NOT a false WRONG against a source that does
 * have picture. This is the check that was missing while reversed/offline clips slipped
 * through: a black reference vs a source-with-picture used to score as a conform error.
 *
 * Sampling is INJECTED (ffmpeg adapters in real use; synthetic buffers in tests) — this
 * module is pure comparison + orchestration, like the rest of the conform-qc core.
 */

import { createRequire } from 'node:module';
import * as lineage from './lineage-db.mjs';

const require = createRequire(import.meta.url);
const metrics = require('../vendor/conform-qc/compare/metrics.js');

const baseCategory = (v) => (v === 'MATCH' ? 'ok' : v === 'OFFSET' ? 'offset' : v === 'WRONG' ? 'wrong' : v === 'REF_OFFLINE' ? 'ref_offline' : 'review');

/**
 * Is the reference frame (near-)black/flat over its non-burn-in area? Such a frame
 * carries no picture to compare against — the shot was offline/black upstream — so the
 * cut must become REF_OFFLINE rather than be classified (a source WITH picture vs a black
 * reference would otherwise score WRONG). Counts the fraction of non-masked pixels at or
 * below `blackLevel`; burn-in pixels (mask===1) are skipped so a TC slate over black still
 * reads as blank. refGray is Float64 0..1, length width*height.
 */
export function referenceIsBlank(refGray, opts = {}) {
  if (!refGray || !refGray.length) return false;
  const mask = opts.mask || null;
  const blackLevel = opts.blackLevel != null ? opts.blackLevel : 0.06;
  const minFraction = opts.blankFraction != null ? opts.blankFraction : 0.96;
  let used = 0;
  let black = 0;
  for (let i = 0; i < refGray.length; i++) {
    if (mask && mask[i]) continue; // skip burn-in region
    used += 1;
    if (refGray[i] <= blackLevel) black += 1;
  }
  if (used < 16) return false; // too little signal to judge
  return black / used >= minFraction;
}

/**
 * Classify one cut from two grayscale buffers (Float64, 0..1, width*height).
 * opts: { width, height, mask, maxShift, thresholds }.
 */
export function classifyCut(conformGray, refGray, opts = {}) {
  const c = metrics.classify(conformGray, refGray, {
    width: opts.width,
    height: opts.height,
    mask: opts.mask,
    maxShift: opts.maxShift,
    thresholds: opts.thresholds,
  });
  let scaleResidual = null;
  if ((c.verdict === 'OFFSET' || c.verdict === 'WRONG') && opts.width && opts.height) {
    try {
      scaleResidual = metrics.findScale(refGray, conformGray, opts.mask || null, opts.width, opts.height, {}).residual;
    } catch {
      /* ignore */
    }
  }
  return {
    verdict: c.verdict,
    category: baseCategory(c.verdict),
    structure: c.structure != null ? +c.structure.toFixed(4) : null,
    psnr: c.psnrNorm != null && Number.isFinite(c.psnrNorm) ? +c.psnrNorm.toFixed(2) : null,
    dx: c.offset ? c.offset.dx : null,
    dy: c.offset ? c.offset.dy : null,
    scale_residual: scaleResidual,
  };
}

/**
 * Refine a base verdict into the marker color (Phase 7):
 * WRONG/OFFSET + oracle satisfiable (source has the frame, aspect ok) → conform (RED)
 * source can't satisfy intent (offline / missing frame / aspect mismatch) → turnover (YELLOW)
 * UNREADABLE → review (human wipe)
 * `sat` = { sourceOnline, frameInRange, aspectOk } from the cut/media (caller supplies).
 */
export function markerCategory(verdict, sat = {}) {
  if (verdict === 'MATCH') return { category: 'ok', color: null };
  if (verdict === 'REF_OFFLINE') return { category: 'ref_offline', color: 'Blue' };
  if (verdict === 'UNREADABLE') return { category: 'review', color: 'Cyan' };
  const satisfiable = sat.sourceOnline !== false && sat.frameInRange !== false && sat.aspectOk !== false;
  if (!satisfiable) return { category: 'turnover', color: 'Yellow' };
  return { category: 'conform', color: 'Red' };
}

/**
 * QC a whole snapshot against a reference. Samplers are injected:
 * opts.sampleConform(cut) -> Float64 gray | null
 * opts.sampleReference(cut) -> Float64 gray | null
 * opts.satisfiability(cut) -> { sourceOnline, frameInRange, aspectOk } (optional → red/yellow split)
 * opts: { referenceRef, width, height, mask, maxShift, incremental(default true), now }
 * Returns { scanned, cached, counts, results }. Verdicts persist in the lineage store.
 */
export async function qcSnapshot(dbPath, snapshotId, opts = {}) {
  const snap = lineage.getSnapshot(dbPath, snapshotId);
  if (!snap) throw new Error(`no snapshot ${snapshotId}`);
  const ref = opts.referenceRef ?? null;
  const results = [];
  let scanned = 0;
  let cached = 0;
  for (const cut of snap.cuts) {
    if (opts.incremental !== false) {
      const existing = lineage.getVerdict(dbPath, snapshotId, cut.cut_index, ref);
      if (existing) {
        cached += 1;
        results.push(existing);
        continue;
      }
    }
    const conform = await opts.sampleConform(cut);
    const reference = await opts.sampleReference(cut);
    let v;
    if (!reference) {
      // can't sample the reference → can't verify → human review
      v = {
        snapshot_id: snapshotId,
        cut_index: cut.cut_index,
        reference_ref: ref,
        reference_frame: cut.record_start,
        verdict: 'UNREADABLE',
        category: 'review',
        ran_at: opts.now ?? null,
      };
    } else if (referenceIsBlank(reference, { mask: opts.mask, blackLevel: opts.refBlackLevel, blankFraction: opts.refBlankFraction })) {
      // reference is black/flat → shot was offline upstream → can't adjudicate (NOT a conform error)
      v = {
        snapshot_id: snapshotId,
        cut_index: cut.cut_index,
        reference_ref: ref,
        reference_frame: cut.record_start,
        verdict: 'REF_OFFLINE',
        category: 'ref_offline',
        ran_at: opts.now ?? null,
      };
    } else if (!conform) {
      // the source couldn't deliver the frame (offline / missing / out of range) → turnover
      v = {
        snapshot_id: snapshotId,
        cut_index: cut.cut_index,
        reference_ref: ref,
        reference_frame: cut.record_start,
        verdict: 'WRONG',
        category: 'turnover',
        ran_at: opts.now ?? null,
      };
    } else {
      const c = classifyCut(conform, reference, opts);
      const sat = opts.satisfiability ? opts.satisfiability(cut) : {};
      const mc = c.verdict === 'MATCH' ? { category: 'ok' } : markerCategory(c.verdict, sat);
      v = {
        snapshot_id: snapshotId,
        cut_index: cut.cut_index,
        reference_ref: ref,
        reference_frame: cut.record_start,
        verdict: c.verdict,
        category: mc.category,
        structure: c.structure,
        psnr: c.psnr,
        dx: c.dx,
        dy: c.dy,
        scale_residual: c.scale_residual,
        ran_at: opts.now ?? null,
      };
    }
    lineage.writeVerdict(dbPath, v);
    results.push(v);
    scanned += 1;
  }
  const counts = {};
  for (const r of results) counts[r.verdict] = (counts[r.verdict] || 0) + 1;
  return { snapshotId, referenceRef: ref, scanned, cached, total: results.length, counts, results };
}

/**
 * Incremental payoff: after a fix produced a NEW snapshot, copy verdicts for UNCHANGED
 * cuts from the prior snapshot so only the diff's changed cuts need re-comparing.
 */
export function propagateVerdicts(dbPath, fromId, toId, referenceRef = null) {
  const d = lineage.diffSnapshots(dbPath, fromId, toId);
  const changedRecs = new Set(d.changed.map((c) => c.record_start));
  const from = lineage.getSnapshot(dbPath, fromId);
  const to = lineage.getSnapshot(dbPath, toId);
  const toByRec = new Map(to.cuts.map((c) => [c.record_start, c]));
  let copied = 0;
  for (const fc of from.cuts) {
    if (changedRecs.has(fc.record_start)) continue; // changed → must re-QC
    const tc = toByRec.get(fc.record_start);
    if (!tc) continue;
    const v = lineage.getVerdict(dbPath, fromId, fc.cut_index, referenceRef);
    if (!v) continue;
    lineage.writeVerdict(dbPath, { ...v, snapshot_id: toId, cut_index: tc.cut_index });
    copied += 1;
  }
  return { copied, mustReQC: [...changedRecs] };
}

/** Build the marker plan (agent places via timeline_markers) from cached verdicts. */
export function markerPlan(dbPath, snapshotId, referenceRef = null) {
  const verdicts = lineage.listVerdicts(dbPath, snapshotId, referenceRef);
  const COLOR = { conform: 'Red', turnover: 'Yellow', review: 'Cyan', ref_offline: 'Blue' };
  return verdicts
    .filter((v) => v.category && v.category !== 'ok')
    .map((v) => ({
      record_start: v.reference_frame,
      color: COLOR[v.category] || 'Red',
      note:
        `${v.verdict}/${v.category}` +
        (v.structure != null ? ` struct=${v.structure}` : '') +
        (v.dx != null ? ` off=${v.dx},${v.dy}` : '') +
        (v.scale_residual != null ? ` scale=${v.scale_residual}` : ''),
    }));
}
