'use strict';

/**
 * package/ — the deliverable package builder (spec §12). Media modes ×
 * formats, V2 flag track, provenance manifest, gated auto-apply (+ undo),
 * ConformPackage record, and delivery sinks.
 *
 * OTIO is the internal canonical (package/otio.js); FCP7 XML / AAF derive from
 * the conformed timeline. full/consolidate media modes require mounted volumes
 * (Tier 2) and are reported BLOCKED here; relink is pure.
 */

const fs = require('fs');
const path = require('path');
const { toOtio } = require('./otio');
const { toFcp7Xml } = require('./emit-fcp7');
const { toAafModel } = require('./emit-aaf');

const MEDIA_MODES = Object.freeze(['relink', 'full', 'consolidate']);
const FORMATS = Object.freeze(['otio', 'fcp7Xml', 'aaf', 'drp']);

/** Per-clip provenance manifest (§11). */
function buildManifest(conformed, opts = {}) {
  const repairByCut = opts.repairByCut || {};
  return {
    target: opts.target || 'resolve',
    oracleVersion: opts.oracleVersion || '1',
    clips: conformed.clips.map((c) => {
      const r = repairByCut[c.cutId] || repairByCut[`seq${c.seqstart}`] || null;
      return {
        cutId: c.cutId || `seq${c.seqstart}`,
        seqstart: c.seqstart,
        source: c.source_basename || null,
        path: c.path || null,
        derivedFrame: c.sourceFrame,
        sampleFrame: c.sampleFrame != null ? c.sampleFrame : null,
        repairStrategy: r ? r.strategy : null,
        repairConfidence: r ? r.confidence : null,
        verifyScore: c.verifyScore != null ? c.verifyScore : null,
      };
    }),
  };
}

/** Build the media descriptor for a mode. relink is pure; full/consolidate need volumes. */
function buildMedia(conformed, mediaMode) {
  if (mediaMode === 'relink') {
    return { mode: 'relink', copied: false, references: conformed.clips.map((c) => c.path).filter(Boolean) };
  }
  if (mediaMode === 'full' || mediaMode === 'consolidate') {
    return { mode: mediaMode, blocked: true, reason: 'requires mounted volumes (Tier 2)' };
  }
  throw new Error(`package: unknown media mode "${mediaMode}" (one of ${MEDIA_MODES.join('|')})`);
}

/**
 * Gated auto-apply (§15): apply ONLY repair results whose mode is 'auto-apply'
 * (deterministic + re-verified). Records an undo manifest. Everything else is
 * left for review (propose-only / flag-v2).
 */
function applyGatedAutoApply(conformed, repairResults) {
  const byCut = Object.fromEntries(repairResults.map((r) => [r.cutId, r]));
  const applied = [];
  const undo = [];
  const deferred = [];
  const clips = conformed.clips.map((c) => {
    const r = byCut[c.cutId || `seq${c.seqstart}`];
    if (r && r.repair && r.repair.mode === 'auto-apply' && r.repair.proposal && r.repair.proposal.fix) {
      const fix = r.repair.proposal.fix;
      const next = { ...c };
      const before = {};
      for (const k of Object.keys(fix)) {
        before[k] = c[k] != null ? c[k] : null;
        next[k] = fix[k];
      }
      applied.push({ cutId: c.cutId, strategy: r.repair.strategy });
      undo.push({ cutId: c.cutId, before });
      return next;
    }
    if (r && r.repair && r.repair.mode !== 'auto-apply') deferred.push({ cutId: c.cutId, mode: r.repair.mode });
    return c;
  });
  return { conformed: { ...conformed, clips }, applied, undo, deferred };
}

/** ConformPackage record (§11) — the delivered package + manifest, versioned. */
function makeConformPackage(meta) {
  return {
    type: 'ConformPackage',
    version: meta.version || 1,
    createdAt: meta.createdAt != null ? meta.createdAt : null,
    mediaMode: meta.mediaMode,
    formats: meta.formats,
    packageKeys: meta.packageKeys || [],
    manifest: meta.manifest || null,
    v2FlagCount: meta.v2FlagCount || 0,
  };
}

/**
 * Build a package descriptor: any subset of formats × a media mode + V2 flag
 * track + manifest. Pure (no IO) — delivery sinks write it out.
 */
function buildPackage(conformed, opts = {}) {
  const mediaMode = opts.mediaMode || 'relink';
  const formats = opts.formats || ['otio'];
  const files = {};
  for (const f of formats) {
    if (f === 'otio') files.otio = toOtio(conformed);
    else if (f === 'fcp7Xml') files.fcp7Xml = toFcp7Xml(conformed, opts);
    else if (f === 'aaf') files.aaf = toAafModel(conformed);
    else if (f === 'drp') files.drp = { blocked: true, reason: 'DRP authoring requires Resolve (Tier 3)' };
    else throw new Error(`package: unknown format "${f}"`);
  }
  const manifest = buildManifest(conformed, opts);
  const v2FlagTrack = opts.v2Flags || [];
  const pkg = { mediaMode, formats, files, media: buildMedia(conformed, mediaMode), v2FlagTrack, manifest };
  pkg.record = makeConformPackage({ mediaMode, formats, manifest, v2FlagCount: v2FlagTrack.length, version: opts.version, createdAt: opts.createdAt });
  return pkg;
}

/** Local delivery sink (post-assistant): write the package to a folder. */
function deliverToFolder(pkg, dir) {
  fs.mkdirSync(dir, { recursive: true });
  const written = [];
  const write = (name, content) => {
    const p = path.join(dir, name);
    fs.writeFileSync(p, typeof content === 'string' ? content : JSON.stringify(content, null, 2));
    written.push(p);
  };
  if (pkg.files.otio) write('conform.otio.json', pkg.files.otio);
  if (pkg.files.fcp7Xml) write('conform.xml', pkg.files.fcp7Xml);
  if (pkg.files.aaf) write('conform.aaf.model.json', pkg.files.aaf);
  write('manifest.json', pkg.manifest);
  if (pkg.v2FlagTrack.length) write('v2-flags.json', pkg.v2FlagTrack);
  return written;
}

/** Cloud delivery sink: enqueue to R2/Download Center via an injected enqueue fn. */
async function deliverToDownloadCenter(pkg, { enqueue, keyPrefix = 'conform/' } = {}) {
  if (typeof enqueue !== 'function') throw new Error('deliverToDownloadCenter: an enqueue fn must be injected');
  const keys = [];
  for (const [fmt, content] of Object.entries(pkg.files)) {
    const key = `${keyPrefix}${fmt}`;
    await enqueue(key, content);
    keys.push(key);
  }
  await enqueue(`${keyPrefix}manifest.json`, pkg.manifest);
  keys.push(`${keyPrefix}manifest.json`);
  // Parity with deliverToFolder: ship the V2 flag track when present, so cloud
  // deliveries surface manual-handling flags too (never a silent drop).
  if (pkg.v2FlagTrack && pkg.v2FlagTrack.length) {
    await enqueue(`${keyPrefix}v2-flags.json`, pkg.v2FlagTrack);
    keys.push(`${keyPrefix}v2-flags.json`);
  }
  return keys;
}

module.exports = {
  MEDIA_MODES,
  FORMATS,
  buildPackage,
  buildManifest,
  buildMedia,
  applyGatedAutoApply,
  makeConformPackage,
  deliverToFolder,
  deliverToDownloadCenter,
};
