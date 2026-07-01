'use strict';

/**
 * oracle/ — the conform Oracle (spec §6).
 *
 * Given a clip + a target id + a sequence context, derive the frame the target
 * software actually shows (and its transform). The Oracle is PLUGGABLE per
 * target: Resolve is the first and only v1 ruleset (spec "Target scope:
 * RESOLVED — Resolve only for v1; Oracle is pluggable"). Premiere/Avid/Flame
 * are added later as their own ruleset modules; the Resolve read-back (P2) is
 * how a ruleset is proven correct.
 */

const resolveTarget = require('./resolve');

const TARGETS = Object.freeze({
  [resolveTarget.id]: resolveTarget,
});

const DEFAULT_TARGET = 'resolve';

/** Look up a target ruleset by id; throws clearly on an unknown target. */
function getTarget(targetId = DEFAULT_TARGET) {
  const t = TARGETS[targetId];
  if (!t) {
    throw new Error(
      `conform-qc oracle: unknown target "${targetId}" (known: ${Object.keys(TARGETS).join(', ')})`,
    );
  }
  return t;
}

/** Derive via the selected target ruleset. */
function derive(clip, ctx, targetId = DEFAULT_TARGET) {
  return getTarget(targetId).derive(clip, ctx);
}

module.exports = { TARGETS, DEFAULT_TARGET, getTarget, derive };
