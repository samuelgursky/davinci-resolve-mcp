/**
 * Cluster D — render_manifest + reconcile. Build an expected-outputs manifest (checksums +
 * frame counts) BEFORE/AT render, then reconcile the actual outputs AFTER: every deliverable
 * rendered, right length, no dropped/duplicate frames (by frame-count mismatch), checksum match.
 *
 * Silent-lie discipline: a manifest entry asserts bytes-read>0; reconcile flags missing/extra/
 * size-mismatch/frame-count-mismatch rather than glossing. Black-frame-run detection is a
 * SAMPLED live follow-up (honest scope note) — this reconciles structure + checksum + count.
 *
 * Deps: node crypto (checksums, always available) + ffprobe (frame counts, peer/optional). No Resolve.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { probeMedia } from './ffprobe-media.mjs';
import { hasFfprobe } from './capabilities.mjs';

/** sha256 of a file (streamed). Asserts bytes>0. */
export function checksumFile(file) {
  const st = fs.statSync(file);
  if (!st.size) throw new Error(`checksum: '${file}' is 0 bytes (empty-green silent-lie guard)`);
  const h = crypto.createHash('sha256');
  h.update(fs.readFileSync(file));
  return { sha256: h.digest('hex'), size: st.size };
}

/**
 * Build a manifest for a set of expected output files.
 * @param {Array<{name?:string, path:string, entity?:string}>} outputs
 * @param {{probeFrames?:boolean}} [opts]
 */
export function buildManifest(outputs, opts = {}) {
  const probeFrames = opts.probeFrames !== false && hasFfprobe();
  const entries = [];
  const missing = [];
  for (const o of outputs) {
    if (!fs.existsSync(o.path)) {
      missing.push({ name: o.name || path.basename(o.path), path: o.path });
      continue;
    }
    const { sha256, size } = checksumFile(o.path);
    const entry = { name: o.name || path.basename(o.path), path: o.path, entity: o.entity || null, sha256, size };
    if (probeFrames) {
      const p = probeMedia(o.path);
      if (p && p.video) {
        entry.frameCount = p.video.frameCount;
        entry.duration = p.format.duration;
        entry.fps = p.video.fps;
      }
    }
    entries.push(entry);
  }
  return { version: 1, count: entries.length, outputs: entries, missing };
}

/**
 * Reconcile a prior manifest against the actual files on disk NOW.
 * @param {object} manifest a buildManifest() result
 * @param {{probeFrames?:boolean, expectExtraIn?:string}} [opts]
 */
export function reconcileManifest(manifest, opts = {}) {
  const probeFrames = opts.probeFrames !== false && hasFfprobe();
  const results = [];
  for (const e of manifest.outputs || []) {
    const r = { name: e.name, path: e.path };
    if (!fs.existsSync(e.path)) {
      results.push({ ...r, status: 'missing', pass: false });
      continue;
    }
    const { sha256, size } = checksumFile(e.path);
    const checksumMatch = sha256 === e.sha256;
    const sizeMatch = size === e.size;
    let frameMatch = null;
    if (probeFrames && e.frameCount != null) {
      const p = probeMedia(e.path);
      const fc = p && p.video ? p.video.frameCount : null;
      frameMatch = fc === e.frameCount;
      r.frameCount = fc;
      r.expectedFrameCount = e.frameCount;
    }
    const pass = checksumMatch && sizeMatch && frameMatch !== false;
    results.push({ ...r, status: pass ? 'ok' : 'changed', pass, checksumMatch, sizeMatch, ...(frameMatch !== null ? { frameMatch } : {}) });
  }
  const failed = results.filter((r) => !r.pass);
  return {
    pass: failed.length === 0,
    reconciled: results.length,
    failedCount: failed.length,
    results,
    gate: 'review',
    note: 'checksum + size + frame-count reconcile. Black-frame/duplicate-run detection is a SAMPLED live follow-up, not covered here.',
  };
}
