'use strict';

/**
 * repair/ — the repair strategy LADDER (spec §9).
 *
 * For a cut that failed verification, try strategies in order; the first that
 * detects proposes a fix. The fix is RE-VERIFIED (re-sample + compare) before
 * acceptance; deterministic strategies that re-verify clean ≥ gate auto-apply
 * (§15), everything else is propose-only (human approves). The diagnosis class +
 * outcome are recorded to ConformKnowledge so confidence improves with use.
 *
 * Unrepairable / low-confidence → flag to the V2 track (one annotated clip).
 */

const { ConformKnowledge } = require('../knowledge');
const strategies = require('./strategies');

const DEFAULT_ORDER = [
  strategies.scaleDoubleCount,
  strategies.subclipOffset,
  strategies.ticksRetime,
  strategies.staleRelink,
];

/**
 * @param {object} opts {
 *   order?            strategy list (default DEFAULT_ORDER)
 *   knowledge?        a ConformKnowledge store (created if absent)
 *   confidenceGate?   default 0.90 (§15 SSIM threshold)
 *   reverify?(cut, proposal, ctx) -> Promise<{ ok:boolean, confidence:number }>  optional re-sample+compare
 * }
 */
function makeRepairLadder(opts = {}) {
  const order = opts.order || DEFAULT_ORDER;
  const knowledge = opts.knowledge || new ConformKnowledge();
  const gate = opts.confidenceGate != null ? opts.confidenceGate : 0.9;

  async function repair(cut, ctx = {}) {
    for (const s of order) {
      if (!s.detect(cut, ctx)) continue;
      const proposal = s.propose(cut, ctx);
      const hasFix = proposal && proposal.fix != null;

      // Re-verify the proposed fix if a verifier is injected; else trust the
      // strategy's own confidence (deterministic strategies derive exact values).
      let reverified = null;
      let confidence = proposal && proposal.confidence != null ? proposal.confidence : null;
      if (opts.reverify && hasFix) {
        reverified = await opts.reverify(cut, proposal, ctx);
        confidence = reverified.confidence;
      }

      const reverifyOk = reverified ? reverified.ok : true;
      const accepted = hasFix && s.deterministic && reverifyOk && (confidence == null || confidence >= gate);
      const mode = accepted ? 'auto-apply' : (hasFix ? (s.deterministic ? 'auto-rejected' : 'propose-only') : 'flag-v2');
      const outcome = hasFix && reverifyOk ? 'success' : 'failure';
      knowledge.record({ class: s.klass, scope: proposal.scope }, { strategy: s.id, outcome });

      return {
        strategy: s.id,
        klass: s.klass,
        deterministic: !!s.deterministic,
        proposal,
        accepted,
        mode,
        confidence,
        diagnosis: proposal.diagnosis,
      };
    }
    // Nothing matched — irreducible, goes to V2.
    knowledge.record({ class: 'unrepairable', scope: cut.cutId }, { strategy: 'flag-v2', outcome: 'failure' });
    return { strategy: null, klass: 'unrepairable', accepted: false, mode: 'flag-v2', diagnosis: 'no repair strategy matched — flag to V2' };
  }

  return { knowledge, repair, order };
}

module.exports = { makeRepairLadder, DEFAULT_ORDER, strategies };
