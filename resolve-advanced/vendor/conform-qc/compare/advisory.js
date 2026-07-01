'use strict';

/**
 * compare/advisory.js — the advisory vision-validation POLICY (spec §8.1 + §15).
 *
 * Two pure functions encode the hard authority limits so a known failure mode
 * (§14: an LLM "fixing" clips that were already correct) can never recur:
 *
 *  - shouldConsultVision(): cost gate — only consult the vision LLM where pixel
 *    math is weakest (borderline band / alignment mode / stubborn propose-only
 *    repairs). A clear MATCH or clear WRONG is NOT consulted.
 *  - reconcile(): the deterministic verdict is authority. The advisory verdict
 *    may CORROBORATE or RAISE a flag (→ human REVIEW); it can NEVER clear a flag,
 *    flip a deterministic WRONG to MATCH, or promote anything to auto-apply.
 *
 * No LLM here — this is the deterministic policy around the (optional) LLM call.
 */

const DEFAULT_BAND = Object.freeze({ borderlineLo: 0.85, borderlineHi: 0.93 });

/** The action a deterministic verdict maps to (§15 auto-apply policy). */
function actionFor(verdict) {
  switch (verdict) {
    case 'MATCH':
      return 'auto-apply-eligible'; // deterministic gate (§15) still decides
    case 'OFFSET':
      return 'propose'; // measured offsets are propose-only
    case 'WRONG':
      return 'flag-v2';
    case 'REVIEW':
      return 'human-review';
    default:
      return 'flag-v2'; // UNREADABLE etc.
  }
}

/**
 * Should we spend a vision call on this cut?
 * @param {object} det  deterministic result { verdict, structure }
 * @param {object} opts { mode, proposeOnlyRepair, thresholds }
 */
function shouldConsultVision(det, opts = {}) {
  const band = { ...DEFAULT_BAND, ...(opts.thresholds || {}) };
  const mode = opts.mode || 'content-identity';
  // Alignment mode: the structural metric doesn't apply — vision is the primary signal.
  if (mode === 'alignment') return true;
  // Stubborn propose-only repairs (wrong-source, aspect, per-file offset, residual).
  if (opts.proposeOnlyRepair) return true;
  // Borderline content-identity score — least confident region of the metric.
  const s = det && det.structure;
  if (typeof s === 'number' && s >= band.borderlineLo && s <= band.borderlineHi) return true;
  // Clear MATCH (above band) or clear WRONG (below band): don't spend the call.
  return false;
}

/** Do the deterministic and advisory verdicts agree? */
function agrees(detVerdict, advVerdict) {
  if (advVerdict === 'MATCH') return detVerdict === 'MATCH' || detVerdict === 'OFFSET';
  if (advVerdict === 'WRONG') return detVerdict === 'WRONG';
  return false; // UNSURE never counts as agreement
}

/**
 * Reconcile a deterministic verdict with an optional advisory verdict.
 * The deterministic verdict is authority. Returns:
 *   { verdict, finalAction, advisory, escalated, reason }
 *
 * Invariants (asserted by tests):
 *  - advisory can never flip a deterministic WRONG to MATCH (it escalates instead).
 *  - advisory can never produce 'auto-apply' — only the deterministic MATCH path
 *    is 'auto-apply-eligible', and a dispute downgrades it to human REVIEW.
 *  - any disagreement, or a vision-raised concern, → human REVIEW (never auto-resolved).
 */
function reconcile(det, advisory) {
  const base = {
    verdict: det.verdict,
    finalAction: actionFor(det.verdict),
    advisory: advisory || null,
    escalated: false,
    reason: 'deterministic',
  };
  if (!advisory) return base;

  if (advisory.advisory !== true) {
    throw new Error('reconcile: advisory result must be marked advisory:true (use VisionValidator)');
  }

  if (agrees(det.verdict, advisory.verdict)) {
    // Corroboration. Does NOT elevate authority — auto-apply eligibility still
    // comes from the deterministic verdict + the §15 gate, never from vision.
    return { ...base, reason: 'corroborated' };
  }

  // Disagreement (incl. vision saying WRONG/UNSURE on a deterministic MATCH, or
  // vision saying MATCH on a deterministic WRONG). Vision NEVER clears or flips —
  // it routes to a human. This is the only thing it's allowed to force.
  return {
    verdict: 'REVIEW',
    finalAction: 'human-review',
    advisory,
    escalated: true,
    reason: `advisory(${advisory.verdict}) disputes deterministic(${det.verdict})`,
  };
}

module.exports = { DEFAULT_BAND, actionFor, shouldConsultVision, agrees, reconcile };
