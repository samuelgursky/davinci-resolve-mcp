'use strict';

/**
 * ops/local-conform.js — the §12 LOCAL conform: the shared conform core
 * (ops/conform-core.js) driven by LOCAL adapters — a filesystem media index
 * (a `find` over a footage folder) — delivering the package to a chosen local
 * folder. The core takes injected media-source and delivery-sink adapters, so a
 * host can compose it with other sources/sinks; only those two ends differ.
 */

const fs = require('fs');
const { spawnSync } = require('child_process');

const { buildConformPackage, modelFromTurnover } = require('./conform-core');
const P = require('../packaging');

/** List the video media under a footage folder (the filesystem media index input). */
function listFootage(footageDir, { findPath = 'find' } = {}) {
  const r = spawnSync(findPath, [footageDir, '-iname', '*.mov', '-o', '-iname', '*.mp4'], {
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  if (r.status !== 0) throw new Error(`local-conform: find failed in ${footageDir}: ${(r.stderr || '').slice(-200)}`);
  return r.stdout
    .split('\n')
    .filter((l) => l && !l.includes('/._'))
    .map((p) => ({ path: p, basename: p.split('/').pop() }));
}

/**
 * Run a local conform end-to-end (turnover → verify → relink → package → folder).
 * @param {object} req {
 *   model?|xmlPath?, footageDir?, media?, outputDir,
 *   target?, formats?, minScore?, version?, referenceProvider?, visionValidator?, thresholds?, findPath?
 * }
 * @returns {Promise<{summary, perCut, relink, dropped, delivered:string[], outputDir}>}
 */
async function runLocalConform(req = {}) {
  const { footageDir, outputDir } = req;
  if (!outputDir) throw new Error('local-conform: outputDir required');

  // Local adapter — filesystem media index (a `find`), unless a media list is injected.
  const media = req.media || (() => {
    if (!footageDir || !fs.existsSync(footageDir)) throw new Error(`local-conform: footageDir not found: ${footageDir}`);
    return listFootage(footageDir, { findPath: req.findPath });
  })();

  const core = await buildConformPackage({ ...req, media });
  const delivered = P.deliverToFolder(core.pkg, outputDir);

  return {
    summary: core.report.summary,
    perCut: core.report.perCut,
    relink: core.relink,
    dropped: core.dropped,
    delivered,
    outputDir,
  };
}

module.exports = { runLocalConform, listFootage, modelFromTurnover };
