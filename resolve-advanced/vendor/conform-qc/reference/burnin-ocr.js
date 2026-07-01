'use strict';

/**
 * reference/burnin-ocr.js — Tier A ground truth (spec §7): read the source
 * timecode + filename BURNED INTO a review render, so a cut is verified as
 * "content matches AND came from the named source." This is the mechanism that
 * recovers the true source of a mismatched cut (e.g. a reversed/subclip whose
 * frame can't be trusted from the editorial offsets alone).
 *
 * Uses tesseract (system dep) with a dark-lift pre-pass (review renders are
 * often temped dark) and optional MULTI-FRAME CONSENSUS (vote across frames) per
 * the spec. OCR is noisy, so identity matching is FUZZY (token overlap), not
 * exact — a misread camera/roll word still resolves because the distinctive
 * tokens (roll/date) pin the source.
 *
 * tesseract is invoked as a subprocess; callers should skip-if-absent.
 */

const sharp = require('sharp');
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

// Default burn-in regions (fractions of W/H) for a common review-render template.
const DEFAULT_REGIONS = Object.freeze({
  bottom: { x0: 0.0, y0: 0.93, x1: 1.0, y1: 1.0 }, // filename (left) + record TC (right)
  topTc: { x0: 0.34, y0: 0.06, x1: 0.66, y1: 0.18 }, // centered source TC
});

const TC_RE = /\b(\d{2}:\d{2}:\d{2}[:;]\d{2})\b/;

function tokenize(text) {
  return String(text || '')
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((t) => t.length >= 2);
}

/** Fraction of the expected source-name tokens that appear in the OCR tokens. */
function identityOverlap(ocrText, expectedName) {
  const want = new Set(tokenize(expectedName));
  if (want.size === 0) return 0;
  const got = new Set(tokenize(ocrText));
  let hit = 0;
  for (const t of want) if (got.has(t)) hit += 1;
  return hit / want.size;
}

async function ocrRegion(framePath, region, lift) {
  const meta = await sharp(framePath).metadata();
  const W = meta.width;
  const H = meta.height;
  const left = Math.max(0, Math.round(region.x0 * W));
  const top = Math.max(0, Math.round(region.y0 * H));
  const width = Math.min(W - left, Math.round((region.x1 - region.x0) * W));
  const height = Math.min(H - top, Math.round((region.y1 - region.y0) * H));
  let img = sharp(framePath).extract({ left, top, width, height }).greyscale().normalise();
  if (lift && lift !== 1) img = img.linear(lift, 0).normalise();
  const buf = await img.resize({ width: width * 2 }).png().toBuffer();
  const tmp = path.join(os.tmpdir(), `cqc-ocr-${process.pid}-${left}-${top}.png`);
  fs.writeFileSync(tmp, buf);
  try {
    return execFileSync('tesseract', [tmp, 'stdout', '--psm', '7'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
  } finally {
    fs.rmSync(tmp, { force: true });
  }
}

/**
 * Read the burn-in from one frame (or several, for consensus).
 * @param {string|string[]} frames  frame path(s)
 * @param {object} opts { regions?, lift? }
 * @returns {Promise<{ sourceTc: string|null, ocrText: string, perFrame: object[] }>}
 */
async function readBurnIn(frames, opts = {}) {
  const list = Array.isArray(frames) ? frames : [frames];
  const regions = { ...DEFAULT_REGIONS, ...(opts.regions || {}) };
  const lift = opts.lift || 1;
  const perFrame = [];
  for (const f of list) {
    const bottom = await ocrRegion(f, regions.bottom, lift);
    let topTc = '';
    try {
      topTc = await ocrRegion(f, regions.topTc, lift);
    } catch (e) {
      /* top TC optional */
    }
    const tcMatch = (topTc.match(TC_RE) || bottom.match(TC_RE) || [])[1] || null;
    perFrame.push({ frame: f, bottom, topTc, tc: tcMatch });
  }
  // Consensus: the most common non-null TC across frames; concatenated bottom text.
  const tcVotes = {};
  for (const r of perFrame) if (r.tc) tcVotes[r.tc] = (tcVotes[r.tc] || 0) + 1;
  const sourceTc = Object.keys(tcVotes).sort((a, b) => tcVotes[b] - tcVotes[a])[0] || null;
  const ocrText = perFrame.map((r) => r.bottom).join(' ');
  return { sourceTc, ocrText, perFrame };
}

module.exports = { readBurnIn, identityOverlap, tokenize, DEFAULT_REGIONS, TC_RE };
