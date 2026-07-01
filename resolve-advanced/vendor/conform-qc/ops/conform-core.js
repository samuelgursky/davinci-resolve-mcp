'use strict';

/**
 * ops/conform-core.js — the surface-agnostic conform core shared by the local
 * (post-assistant) and cloud (render-node/library) runtimes. Given a turnover
 * (raw XML or parsed model) and a media list, it: parses + filters → verifies →
 * relinks (IDF true-source) → builds a CONFORMED timeline → builds a package.
 *
 * It does NOT choose where media comes from (a `find` vs a library listing) or
 * where the package goes (a folder vs an enqueue sink) — those are the adapters
 * the local/cloud wrappers inject. This is what makes the two surfaces the SAME
 * core (spec §12): only the media source and the delivery sink differ.
 */

const fs = require('fs');

const oracle = require('../oracle');
const { verify } = require('./verify');
const { parseGeometry } = require('../parse');
const { MediaIndex } = require('../repair/media-index');
const P = require('../packaging');

/** Premiere tick rate (ticks/second); ticksPerFrame = this / fps. */
const PREMIERE_TICKS_PER_SECOND = 254016000000;

/** Premiere generators / slugs — not gradeable camera media, never conformed. */
const GENERATOR_SOURCE = /^(universal counting leader|universal leader|black video|bars and tone|slug|color matte|transparent video)$/i;

/**
 * Parse a turnover XML into a ConformModel, dropping non-conformable clips:
 * off-timeline positions (seqstart < 0) and Premiere generators/slugs (leader,
 * black, bars). Returns { model, dropped[] } — dropped is surfaced, never silent.
 */
function modelFromTurnover(xmlPath) {
  const parsed = parseGeometry(fs.readFileSync(xmlPath, 'utf8'));
  const fps = parsed.sequence && parsed.sequence.fps;
  if (!fps) throw new Error(`conform-core: turnover has no sequence fps: ${xmlPath}`);
  const conformable = [];
  const dropped = [];
  for (const c of parsed.clips) {
    const stem = String(c.source_basename || '').replace(/\.[a-z0-9]+$/i, '').trim();
    if (!Number.isInteger(c.seqstart) || c.seqstart < 0) {
      dropped.push({ seqstart: c.seqstart, source_basename: c.source_basename, reason: 'off-timeline (seqstart < 0)' });
    } else if (!c.source_basename || GENERATOR_SOURCE.test(stem)) {
      dropped.push({ seqstart: c.seqstart, source_basename: c.source_basename, reason: 'generator/slug (no camera media)' });
    } else {
      conformable.push(c);
    }
  }
  const model = { sequence: parsed.sequence, ticksPerFrame: PREMIERE_TICKS_PER_SECOND / fps, clips: conformable };
  return { model, dropped };
}

/**
 * Build a conform package from a turnover + media list (no delivery).
 * @param {object} req {
 *   model?|xmlPath?, media: [{path,basename,...}], target?, formats?, minScore?,
 *   version?, referenceProvider?, visionValidator?, thresholds?
 * }
 * @returns {Promise<{report, conformed, relink:{resolved,unresolved,total}, dropped, v2Flags, pkg}>}
 */
async function buildConformPackage(req = {}) {
  let model = req.model;
  let dropped = [];
  if (!model && req.xmlPath) {
    if (!fs.existsSync(req.xmlPath)) throw new Error(`conform-core: xmlPath not found: ${req.xmlPath}`);
    ({ model, dropped } = modelFromTurnover(req.xmlPath));
  }
  if (!model || !model.sequence || !Array.isArray(model.clips)) {
    throw new Error('conform-core: a model { sequence, ticksPerFrame, clips[] } or an xmlPath is required');
  }
  if (!Array.isArray(req.media)) throw new Error('conform-core: media[] (the media index input) is required');

  const target = req.target || 'resolve';
  const formats = req.formats || ['otio', 'fcp7Xml'];
  const minScore = req.minScore != null ? req.minScore : 0.55;
  const index = new MediaIndex(req.media);

  // VERIFY — read-only. Tier C (math-verified) unless content adapters are injected.
  const report = await verify(model, {
    target,
    referenceProvider: req.referenceProvider,
    visionValidator: req.visionValidator,
    thresholds: req.thresholds,
  });

  // RELINK — resolve each distinct source (exact basename, then IDF true-source).
  const ctx = { ticksPerFrame: model.ticksPerFrame, sequenceWidth: model.sequence.width };
  const pathByBase = new Map();
  const resolved = [];
  const unresolved = [];
  for (const c of model.clips) {
    if (pathByBase.has(c.source_basename)) continue;
    const exact = index.byBasename(c.source_basename);
    const norm = exact ? null : index.byNormalized(c.source_basename);
    const m = exact
      ? { path: exact, basename: c.source_basename, score: 1 }
      : norm
        ? { path: norm, basename: norm.split('/').pop(), score: 1 }
        : index.findTrueSource(c.source_basename, { minScore });
    pathByBase.set(c.source_basename, m ? m.path : null);
    if (m) resolved.push({ base: c.source_basename, path: m.path, score: m.score });
    else unresolved.push(c.source_basename);
  }

  // CONFORMED timeline — Oracle source/sample frames + scale, with resolved paths.
  const conformed = {
    sequence: model.sequence,
    ticksPerFrame: model.ticksPerFrame,
    clips: model.clips.map((c) => {
      const d = oracle.derive(c, ctx);
      return {
        cutId: `seq${c.seqstart}`,
        seqstart: c.seqstart,
        seqend: c.seqend,
        sourceFrame: d.derivedSourceFrame,
        sampleFrame: d.derivedSampleFrame,
        scale: d.derivedScaleCorrected,
        source_basename: c.source_basename,
        srcW: c.srcW,
        srcH: c.srcH,
        path: pathByBase.get(c.source_basename) || `file://unresolved/${c.source_basename}`,
      };
    }),
  };

  const v2Flags = unresolved.map((b) => ({
    kind: 'unresolved-source',
    source_basename: b,
    note: 'no media matched — manual relink',
  }));
  const pkg = P.buildPackage(conformed, { mediaMode: 'relink', formats, v2Flags, version: req.version });

  return { report, conformed, relink: { resolved, unresolved, total: pathByBase.size }, dropped, v2Flags, pkg };
}

module.exports = { buildConformPackage, modelFromTurnover, PREMIERE_TICKS_PER_SECOND };
