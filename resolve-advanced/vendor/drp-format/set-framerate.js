/**
 * set-framerate — **relabel** a Resolve `.drp` timeline frame rate in place.
 *
 * This is a *relabel*, not a retime: it rewrites the timeline `FrameRate` blob(s) to a new fps
 * while leaving every clip's integer Start/Duration/In/Out and every `MediaFrameRate` (clip
 * *source* rate) untouched. The frame count is identical; only the rate the timeline is
 * interpreted at changes. Use this to fix a contaminated tag — e.g. a caption/export step that
 * stamped 23.976 onto a 24.000 timeline whose frames are actually correct.
 *
 * Why offline: Resolve locks a timeline's frame rate once the timeline exists (writable only when
 * a project has 0 timelines), so an imported `.drp` can never be relabelled *through* Resolve —
 * only retimed.
 *
 * Where fps lives in a real DRP (verified against templates/media-clip-h264.drp, a Resolve export):
 *   - timeline rate  → `<FrameRate>[double fps][double 0]</FrameRate>` in MediaPool/<folder>/MpFolder.xml
 *   - clip source    → `<MediaFrameRate>…</MediaFrameRate>` (LEFT ALONE — different tag)
 *   - project.xml / Gallery.xml carry no fps.
 * The exact tag `<FrameRate>` never substring-matches `<MediaFrameRate>` (char before "FrameRate"
 * is "a", not "<"), so a `<FrameRate>`-scoped rewrite is inherently clip-safe.
 *
 * @module drp-format/set-framerate
 */

const fs = require('node:fs');
const JSZip = require('jszip');
const { decodeRateBlob, encodeRateBlob } = require('./media-blobs');

// Exact timeline FrameRate blob element. `[^]` (not `.`) so a stray newline can't break the match.
const FRAMERATE_BLOB_RE = /<FrameRate>([0-9a-fA-F]{32})<\/FrameRate>/g;

async function loadZip(drpInput) {
  const buf = Buffer.isBuffer(drpInput) ? drpInput : await fs.promises.readFile(drpInput);
  return JSZip.loadAsync(buf);
}

/**
 * Relabel every timeline FrameRate blob in a `.drp` to `targetFps`.
 *
 * @param {string|Buffer} drpInput  Path to a `.drp` (or its Buffer).
 * @param {number} targetFps        New timeline fps (e.g. 24, 23.976, 25).
 * @returns {Promise<{ buffer: Buffer, changes: Array<{entry:string, from:number, to:number}>, timelineFrameRates:number[] }>}
 * @throws if the target is not a finite positive number or no timeline FrameRate blob is found.
 */
async function setTimelineFrameRate(drpInput, targetFps) {
  if (typeof targetFps !== 'number' || !Number.isFinite(targetFps) || targetFps <= 0) {
    throw new Error(`set-framerate: targetFps must be a positive finite number, got ${targetFps}`);
  }
  const zip = await loadZip(drpInput);
  const newHex = encodeRateBlob(targetFps); // [double fps][double 0], 32 hex chars

  const entries = [];
  zip.forEach((p, e) => { if (!e.dir && /\.xml$/i.test(p)) entries.push(p); });

  const changes = [];
  const seenRates = [];
  for (const entry of entries) {
    const xml = await zip.file(entry).async('string');
    if (!FRAMERATE_BLOB_RE.test(xml)) continue;
    FRAMERATE_BLOB_RE.lastIndex = 0;
    const next = xml.replace(FRAMERATE_BLOB_RE, (_m, hex) => {
      const from = decodeRateBlob(hex);
      if (from != null) seenRates.push(from);
      // Round-trip guard: only record a real change; still rewrite so the blob's
      // trailing 8 bytes are canonicalised to zero.
      if (from == null || Math.abs(from - targetFps) > 1e-6) {
        changes.push({ entry, from: from ?? NaN, to: targetFps });
      }
      return `<FrameRate>${newHex}</FrameRate>`;
    });
    zip.file(entry, next);
  }

  if (seenRates.length === 0) {
    throw new Error('set-framerate: no timeline <FrameRate> blob found — not a .drp with a timeline?');
  }

  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return { buffer, changes, timelineFrameRates: seenRates };
}

/** Read-only: report the timeline frame rate(s) in a `.drp` without modifying it. */
async function readTimelineFrameRates(drpInput) {
  const zip = await loadZip(drpInput);
  const rates = [];
  const entries = [];
  zip.forEach((p, e) => { if (!e.dir && /\.xml$/i.test(p)) entries.push(p); });
  for (const entry of entries) {
    const xml = await zip.file(entry).async('string');
    for (const m of xml.matchAll(FRAMERATE_BLOB_RE)) {
      const fps = decodeRateBlob(m[1]);
      if (fps != null) rates.push({ entry, fps });
    }
  }
  return rates;
}

module.exports = { setTimelineFrameRate, readTimelineFrameRates };
