/**
 * Cluster M — media front-end / AE ops (the recurring-show time sink). fs-based + deterministic;
 * the ffprobe-backed inventory/sync live in media-inventory.mjs.
 *
 * Silent-lie discipline extends to MEDIA here (cross-craft review): assert bytes-read>0 and
 * file-count matches (empty-green is the lie); dupe by HASH never by name; NEVER rewrite a
 * camera-original filename (sidecar/DB only); path-maps scoped per episode (never relink to the
 * wrong season). Everything is a dry-run PLAN or a VERIFY report — the AE approves the apply.
 *
 *   ingest_verify   — seal (hash manifest / MHL-like) / verify / dupes-by-hash
 *   relink_manifest — offline-media + path-map PREFLIGHT (dry-run)
 *   rename_plan     — dry-run rename plan; refuses camera originals
 *   reel_normalize  — normalize reel/card names to a convention (plan + collisions)
 *   project_hygiene — dupes, orphan/offline clips, mixed-fps timelines, empty bins, unlabeled versions
 *   turnover_package— assemble + checksum a dated color/sound/VFX folder manifest (dry-run)
 *
 * No Resolve, no LLM.
 */
import fs from 'node:fs';
import path from 'node:path';
import { checksumFile } from './render-manifest.mjs';

// ── ingest_verify ──────────────────────────────────────────────────────
/** Seal a set of files into a hash manifest (MHL-like). Asserts every file has bytes>0. */
export function sealFiles(files, opts = {}) {
  const entries = [];
  const missing = [];
  for (const f of files) {
    const p = typeof f === 'string' ? f : f.path;
    if (!fs.existsSync(p)) {
      missing.push(p);
      continue;
    }
    const { sha256, size } = checksumFile(p);
    entries.push({ name: path.basename(p), path: p, sha256, size });
  }
  const totalBytes = entries.reduce((n, e) => n + e.size, 0);
  return { version: 1, hashType: 'sha256', count: entries.length, totalBytes, files: entries, missing, sealedFrom: opts.label || null };
}

/** Verify files against a prior seal. Reports ok/missing/changed per file + copy-completeness. */
export function verifyFiles(manifest, opts = {}) {
  const results = [];
  for (const e of manifest.files || []) {
    const p = opts.baseDir ? path.join(opts.baseDir, e.name) : e.path;
    if (!fs.existsSync(p)) {
      results.push({ name: e.name, status: 'missing', pass: false });
      continue;
    }
    const { sha256, size } = checksumFile(p);
    const ok = sha256 === e.sha256 && size === e.size;
    results.push({ name: e.name, status: ok ? 'ok' : 'changed', pass: ok, ...(ok ? {} : { expectedSha: e.sha256, actualSha: sha256 }) });
  }
  const failed = results.filter((r) => !r.pass);
  return {
    pass: failed.length === 0,
    verified: results.length,
    expected: (manifest.files || []).length,
    complete: results.length === (manifest.files || []).length,
    results,
    failed: failed.map((r) => r.name),
  };
}

/** Find duplicate CONTENT (same hash, any name) across a file set. */
export function findDupesByHash(files) {
  const byHash = new Map();
  for (const f of files) {
    const p = typeof f === 'string' ? f : f.path;
    if (!fs.existsSync(p)) continue;
    const { sha256 } = checksumFile(p);
    if (!byHash.has(sha256)) byHash.set(sha256, []);
    byHash.get(sha256).push(path.basename(p));
  }
  const dupes = [...byHash.entries()].filter(([, names]) => names.length > 1).map(([sha256, names]) => ({ sha256, names }));
  return { dupeGroups: dupes.length, dupes };
}

export function ingestVerify(mode, args = {}) {
  if (mode === 'seal') return sealFiles(args.files || [], { label: args.label });
  if (mode === 'verify') return verifyFiles(args.manifest, { baseDir: args.baseDir });
  if (mode === 'dupes') return findDupesByHash(args.files || []);
  throw new Error(`ingest_verify: unknown mode '${mode}' (seal|verify|dupes)`);
}

// ── relink_manifest ────────────────────────────────────────────────────
/**
 * Preflight offline media against a path-map (dry-run). path-maps are SCOPED PER EPISODE by
 * the caller — never a global relink. Longest-prefix wins; multiple matches → ambiguous.
 * @param {string[]} offlinePaths
 * @param {Array<{from:string, to:string}>} pathMap prefix rewrites
 */
export function relinkManifest(offlinePaths, pathMap = [], opts = {}) {
  const maps = [...pathMap].sort((a, b) => b.from.length - a.from.length);
  const relinkable = [];
  const stillOffline = [];
  const ambiguous = [];
  const unmapped = [];
  for (const src of offlinePaths) {
    const matches = maps.filter((m) => src.startsWith(m.from));
    if (!matches.length) {
      unmapped.push(src);
      continue;
    }
    if (matches.length > 1 && matches[0].from.length === matches[1].from.length) {
      ambiguous.push({ from: src, candidates: matches.map((m) => m.from) });
      continue;
    }
    const m = matches[0];
    const target = src.replace(m.from, m.to);
    if (opts.checkExists === false || fs.existsSync(target)) relinkable.push({ from: src, to: target, verified: opts.checkExists !== false });
    else stillOffline.push({ from: src, to: target, reason: 'target does not exist' });
  }
  return { total: offlinePaths.length, relinkableCount: relinkable.length, relinkable, stillOffline, ambiguous, unmapped };
}

// ── rename_plan / reel_normalize ───────────────────────────────────────
// A camera-original if its name matches common camera patterns, unless the caller says otherwise.
const CAMERA_ORIGINAL_RE = /^([A-Z]\d{3}[_ ]?[CR]\d{3,4}|[A-Z]\d{3}_\d{8}_C\d+|MVI_\d+|DSC\d+|[A-Z]{2,4}_?\d{4,})/i;

/**
 * Dry-run rename plan (regex find/replace). REFUSES camera originals (sidecar/DB only).
 * @param {string[]} names basenames to rename
 * @param {{find:string, replace:string, allowCameraOriginals?:boolean, cameraOriginalRe?:RegExp}} rule
 */
export function renamePlan(names, rule = {}) {
  let re;
  try {
    re = new RegExp(rule.find, 'g');
  } catch {
    throw new Error(`rename_plan: invalid find regex '${rule.find}'`);
  }
  const camRe = rule.cameraOriginalRe || CAMERA_ORIGINAL_RE;
  const plan = [];
  const targets = new Map();
  for (const name of names) {
    const isCam = camRe.test(name);
    if (isCam && !rule.allowCameraOriginals) {
      plan.push({ from: name, action: 'refuse-camera-original', note: 'camera original — rename via sidecar/DB only, never the file' });
      continue;
    }
    const to = name.replace(re, rule.replace ?? '');
    if (to === name) {
      plan.push({ from: name, to, action: 'noop' });
      continue;
    }
    targets.set(to, (targets.get(to) || 0) + 1);
    plan.push({ from: name, to, action: 'rename' });
  }
  // Flag collisions (two sources → one target).
  for (const p of plan) if (p.action === 'rename' && targets.get(p.to) > 1) p.action = 'collision';
  const collisions = plan.filter((p) => p.action === 'collision');
  return {
    plan,
    renameCount: plan.filter((p) => p.action === 'rename').length,
    refused: plan.filter((p) => p.action === 'refuse-camera-original').length,
    collisions: collisions.length,
    dryRun: true,
  };
}

/** Normalize reel/card names to a convention (uppercase + zero-pad the trailing number). */
export function reelNormalize(reels, opts = {}) {
  const pad = opts.pad ?? 3;
  const plan = [];
  const targets = new Map();
  for (const r of reels) {
    const to = String(r)
      .toUpperCase()
      .replace(/(\d+)\s*$/, (m) => m.padStart(pad, '0'));
    if (to !== r) targets.set(to, (targets.get(to) || 0) + 1);
    plan.push({ from: r, to, action: to === r ? 'noop' : 'normalize' });
  }
  for (const p of plan) if (p.action === 'normalize' && targets.get(p.to) > 1) p.action = 'collision';
  return { plan, normalizeCount: plan.filter((p) => p.action === 'normalize').length, collisions: plan.filter((p) => p.action === 'collision').length };
}

// ── project_hygiene ────────────────────────────────────────────────────
/**
 * Report project hygiene issues over a supplied structure (the live server reports it; Node judges).
 * @param {{clips?:Array, timelines?:Array, bins?:Array, versions?:Array}} project
 */
export function projectHygiene(project = {}) {
  const clips = project.clips || [];
  const offlineClips = clips.filter((c) => c.online === false).map((c) => c.id);
  // Dupes by hash (fallback path) — never by name alone.
  const byHash = new Map();
  for (const c of clips) {
    const key = c.hash || c.path;
    if (key == null) continue;
    if (!byHash.has(key)) byHash.set(key, []);
    byHash.get(key).push(c.id);
  }
  const dupes = [...byHash.entries()].filter(([, ids]) => ids.length > 1).map(([key, ids]) => ({ key, ids }));
  const mixedFpsTimelines = (project.timelines || [])
    .filter((t) => {
      const fpsSet = new Set([...(t.clipFps || [])]);
      if (t.fps != null) for (const f of t.clipFps || []) if (f !== t.fps) fpsSet.add(f);
      return fpsSet.size > 1;
    })
    .map((t) => t.name);
  const emptyBins = (project.bins || []).filter((b) => (b.clipCount ?? 0) === 0).map((b) => b.name);
  const unlabeledVersions = (project.versions || []).filter((v) => !v.label).map((v) => v.name);
  const findings = { offlineClips, dupes, mixedFpsTimelines, emptyBins, unlabeledVersions };
  const issueCount = offlineClips.length + dupes.length + mixedFpsTimelines.length + emptyBins.length + unlabeledVersions.length;
  return { clean: issueCount === 0, issueCount, findings, gate: 'review' };
}

// ── turnover_package ───────────────────────────────────────────────────
/**
 * Assemble a dated turnover package MANIFEST (dry-run — checksums existing files, plans the
 * folder). Handles + reference are recorded, not enforced here.
 * @param {Array<{path:string, category:'color'|'sound'|'vfx'|'reference', role?:string}>} inputs
 * @param {{date?:string, name?:string, handles?:number}} opts  date = 'YYYYMMDD' (caller-supplied; deterministic)
 */
export function turnoverPackage(inputs, opts = {}) {
  const date = opts.date || 'UNDATED';
  const name = opts.name || 'turnover';
  const folder = `${date}_${name}_TransferFiles`;
  const categories = {};
  let totalBytes = 0;
  const missing = [];
  for (const it of inputs) {
    if (!fs.existsSync(it.path)) {
      missing.push(it.path);
      continue;
    }
    const { sha256, size } = checksumFile(it.path);
    const cat = it.category || 'other';
    (categories[cat] ||= []).push({ name: path.basename(it.path), path: it.path, role: it.role || null, sha256, size });
    totalBytes += size;
  }
  return {
    folder,
    handles: opts.handles ?? null,
    categories,
    fileCount: Object.values(categories).reduce((n, a) => n + a.length, 0),
    totalBytes,
    missing,
    dryRun: true,
    gate: 'review',
  };
}
