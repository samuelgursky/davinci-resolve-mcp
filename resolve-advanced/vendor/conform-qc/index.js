'use strict';

/**
 * conform-qc — Conform QC & Repair Engine (pure core + injected adapters).
 *
 * Core principle: a filename match is NOT a conform. The only truth is the
 * frame the target software actually shows, derived by the Oracle and compared
 * to a reference. Every feature was verified end-to-end against staged golden
 * captures (a full production reel) before landing; the live acceptance
 * harnesses that exercise real media are maintained outside the repo, and
 * fixture-dependent tests skip when the git-ignored golden material is absent.
 */

const path = require('path');

// Module surface. Listed here so maintainers share one map of the architecture.
const MODULES = Object.freeze([
  'parse', // turnover -> ConformModel (geometry/conform-field capture)
  'oracle', // ConformModel + target + seqRes -> derived frame & transform
  'reference', // ground-truth providers (burn-in OCR, TC-sidecar, clean-ref)
  'compare', // derived-vs-reference frame diff; content + alignment modes
  'ops', // operations: conform | patch | insert (vfx/topaz/regrade/graphic)
  'match', // element -> timeline slot (shot-id / plate-TC / edge-frame / explicit)
  'repair', // strategy ladder + diagnosis + confidence
  'knowledge', // ConformKnowledge: pattern signature -> strategy -> outcome
  'packaging', // deliverable (media modes x formats) + V2 flag track + manifest (dir is 'packaging' not 'package' — the latter shadows package.json in Node resolution)
  'report', // per-cut / per-element QC report model (UI-agnostic)
]);

/** Absolute path to the staged ground-truth fixtures directory. */
function fixturesRoot() {
  return path.join(__dirname, '__fixtures__');
}

/**
 * Absolute path to the golden-answer fixture directory (a full-reel capture used
 * as the oracle/comparator answer key; git-ignored client material on a fresh
 * clone, so the dependent tests skip when it is absent).
 */
function reelFixtureDir() {
  return path.join(fixturesRoot(), 'sample-reel-01');
}

module.exports = {
  PACKAGE: 'conform-qc',
  MODULES,
  fixturesRoot,
  reelFixtureDir,
};
