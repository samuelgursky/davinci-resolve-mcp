'use strict';

/**
 * repair/analysis.js — correctness checks + the proposed-timeline / V2-flag-track
 * assembler (spec §9). Pure functions.
 */

/**
 * Dupes / repeated source (§9): a correctness check, not a repair. Group clips
 * by resolved source; report clusters where one source feeds many cuts.
 * Returns [{ source, count, cutIds }] for sources used more than once.
 */
function detectDupes(clips, keyOf = (c) => c.source_basename) {
  const groups = new Map();
  for (const c of clips) {
    const k = keyOf(c);
    if (k == null) continue;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(c.cutId != null ? c.cutId : c.seqstart);
  }
  return [...groups.entries()]
    .filter(([, ids]) => ids.length > 1)
    .map(([source, cutIds]) => ({ source, count: cutIds.length, cutIds }));
}

/**
 * Build a PROPOSED corrected timeline + a V2 flag track from repair results
 * (§9). Auto-applied deterministic fixes land in the corrected timeline;
 * everything else (propose-only, auto-rejected, flag-v2, unrepairable) becomes
 * ONE annotated V2 clip with a V1 gap — nothing is auto-applied silently.
 *
 * @param {object[]} results  [{ cutId, seqstart, repair: <ladder result> }]
 * @returns {{ correctedTimeline: object[], v2Flags: object[], summary: object }}
 */
function proposeTimeline(results) {
  const correctedTimeline = [];
  const v2Flags = [];
  for (const r of results) {
    const rep = r.repair || {};
    if (rep.mode === 'auto-apply' && rep.proposal && rep.proposal.fix) {
      correctedTimeline.push({ cutId: r.cutId, seqstart: r.seqstart, applied: rep.proposal.fix, strategy: rep.strategy, v1Gap: false });
    } else {
      // Irreducible / needs review: keep a V1 gap and annotate one V2 clip.
      correctedTimeline.push({ cutId: r.cutId, seqstart: r.seqstart, applied: null, v1Gap: true });
      v2Flags.push({
        cutId: r.cutId,
        seqstart: r.seqstart,
        mode: rep.mode || 'flag-v2',
        klass: rep.klass || 'unrepairable',
        note: rep.diagnosis || 'flagged for review',
        proposedFix: rep.proposal ? rep.proposal.fix : null,
      });
    }
  }
  return {
    correctedTimeline,
    v2Flags,
    summary: { cuts: results.length, autoApplied: correctedTimeline.filter((c) => !c.v1Gap).length, flagged: v2Flags.length },
  };
}

module.exports = { detectDupes, proposeTimeline };
