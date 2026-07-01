'use strict';

/**
 * report/ — the UI-agnostic QC report model (spec §11).
 *
 * One report per verify/conform run; one entry per cut. Serializes to the
 * `metadata.editorial.qc` shape (§11) so the API/UI can read it without knowing
 * the engine internals.
 *
 * Status vocabulary (per cut):
 *   MATCH | OFFSET | WRONG | UNREADABLE  — content-identity verdicts (had a reference)
 *   REVIEW                               — escalated to a human (e.g. vision dispute)
 *   MATH-VERIFIED                        — Tier C: Oracle-consistent, no picture proof
 *
 * Tier (§7): A (burned ref) | B (clean ref + sidecar) | C (no reference).
 *
 * BADGE RULE (non-negotiable, spec §7): "no picture, no content-verified." A
 * `content-verified` badge requires an actual frame comparison (Tier A/B with a
 * MATCH/OFFSET). Tier C can only ever be `math-verified`.
 */

const REPORT_VERDICTS = Object.freeze(['MATCH', 'OFFSET', 'WRONG', 'UNREADABLE', 'REVIEW', 'MATH-VERIFIED']);

function makeReport(meta = {}) {
  return {
    runAt: meta.runAt != null ? meta.runAt : null,
    target: meta.target || 'resolve',
    oracleVersion: meta.oracleVersion || '1',
    tier: meta.tier || null,
    summary: { matched: 0, offset: 0, wrong: 0, flagged: 0, review: 0, mathVerified: 0, unreadable: 0 },
    perCut: [],
    packageKeys: [],
  };
}

/**
 * The verified badge for a cut. Enforces "no picture, no content-verified":
 *  - content-verified  ONLY when a reference frame was compared (MATCH/OFFSET).
 *  - math-verified      when there was no reference (Tier C) and the Oracle ran.
 *  - null               for WRONG / UNREADABLE / REVIEW (no positive claim).
 */
function badgeFor(cut) {
  if (cut.hasReference) {
    if (cut.status === 'MATCH' || cut.status === 'OFFSET') return 'content-verified';
    return null; // a reference existed but it did NOT verify
  }
  // No reference frame — the strongest claim possible is math-verified.
  if (cut.status === 'MATH-VERIFIED' || cut.status === 'MATCH' || cut.status === 'OFFSET') {
    return 'math-verified';
  }
  return null;
}

function addCut(report, cut) {
  if (!REPORT_VERDICTS.includes(cut.status)) {
    throw new Error(`report: unknown status "${cut.status}" (one of ${REPORT_VERDICTS.join('|')})`);
  }
  const badge = badgeFor(cut);
  // Guard the non-negotiable: a no-reference cut can NEVER carry content-verified.
  if (!cut.hasReference && badge === 'content-verified') {
    throw new Error('report: content-verified badge requires a reference frame (no picture, no content-verified)');
  }
  const entry = {
    cutId: cut.cutId,
    seqstart: cut.seqstart != null ? cut.seqstart : null,
    status: cut.status,
    tier: cut.tier || (cut.hasReference ? 'B' : 'C'),
    hasReference: !!cut.hasReference,
    derivedSourceFrame: cut.derivedSourceFrame != null ? cut.derivedSourceFrame : null,
    derivedSampleFrame: cut.derivedSampleFrame != null ? cut.derivedSampleFrame : null,
    scale: cut.scale != null ? cut.scale : null,
    refScore: cut.refScore != null ? cut.refScore : null,
    offset: cut.offset || null,
    diagnosis: cut.diagnosis || null,
    repair: cut.repair || null,
    advisory: cut.advisory || null,
    identity: cut.identity || null,
    escalated: !!cut.escalated,
    visionConsulted: !!cut.visionConsulted,
    finalAction: cut.finalAction || null,
    badge,
  };
  report.perCut.push(entry);
  switch (cut.status) {
    case 'MATCH':
      report.summary.matched += 1;
      break;
    case 'OFFSET':
      report.summary.offset += 1;
      break;
    case 'WRONG':
      report.summary.wrong += 1;
      report.summary.flagged += 1;
      break;
    case 'REVIEW':
      report.summary.review += 1;
      report.summary.flagged += 1;
      break;
    case 'UNREADABLE':
      report.summary.unreadable += 1;
      report.summary.flagged += 1;
      break;
    case 'MATH-VERIFIED':
      report.summary.mathVerified += 1;
      break;
    default:
      break;
  }
  return entry;
}

/** Serialize to the documented `metadata.editorial.qc` shape (§11). */
function toMetadataQc(report) {
  return {
    runAt: report.runAt,
    target: report.target,
    oracleVersion: report.oracleVersion,
    tier: report.tier,
    summary: { ...report.summary },
    perCut: report.perCut.map((c) => ({
      cutId: c.cutId,
      status: c.status,
      derivedFrame: c.derivedSourceFrame,
      refScore: c.refScore,
      diagnosis: c.diagnosis,
      repair: c.repair,
      badge: c.badge,
    })),
    packageKeys: [...report.packageKeys],
  };
}

module.exports = { REPORT_VERDICTS, makeReport, badgeFor, addCut, toMetadataQc };
