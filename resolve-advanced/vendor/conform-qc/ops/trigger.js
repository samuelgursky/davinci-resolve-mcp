'use strict';

/**
 * ops/trigger.js — the trigger model (spec §15, DECIDED): a cheap auto-verify
 * (Tier C / math-only) on editorial-sidecar upload that surfaces a QC badge, and
 * a full conform + package + Resolve read-back on-demand via a "Conform" action.
 */

/** On sidecar upload: cheap, math-only, surfaces a badge. Never blocks the upload. */
function onSidecarUpload() {
  return {
    trigger: 'auto-on-upload',
    tier: 'C',
    action: 'verify-math-only',
    cost: 'cheap',
    surfaces: 'qc-badge',
    badge: 'math-verified',
  };
}

/** On the on-demand "Conform" action: the full pipeline (heavy, render-node). */
function onConformAction(opts = {}) {
  return {
    trigger: 'on-demand',
    action: 'full-conform+package+resolve-readback',
    cost: 'heavy',
    runsOn: opts.surface === 'local' ? 'post-assistant' : 'render-node',
    includes: ['reference-tiers', 'compare', 'repair', 'package', opts.surface === 'local' ? 'local-resolve' : 'headless-resolve-readback'],
  };
}

module.exports = { onSidecarUpload, onConformAction };
