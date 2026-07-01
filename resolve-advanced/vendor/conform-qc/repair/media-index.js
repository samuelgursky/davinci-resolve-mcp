'use strict';

/**
 * repair/media-index.js — a media index for re-resolving sources (spec §3.2 /
 * §9 true-source search). Pure: built from a list of media descriptors; no IO.
 *
 * Resolves by exact basename, by reel+TC, and by naming-variant (proxy↔original,
 * e.g. a "…4K-2K…" proxy → its "…4K…" scan) — the proxy/scan naming relationship.
 */

function normTokens(name) {
  return String(name || '')
    .toLowerCase()
    .replace(/\.[a-z0-9]+$/, '')
    .split(/[^a-z0-9]+/)
    .filter((t) => t.length >= 2);
}

/**
 * A normalized basename key for proxy↔original EXACT matching, before the fuzzy
 * IDF tier. Unlike normTokens this PRESERVES single-char discriminators (a take
 * marker like "#1" vs "#2" — different rescans of the same shot — must not
 * collapse), and only erases the deterministic proxy/duplicate decorations:
 *   - the extension (proxy .mp4 ↔ original .mov),
 *   - the proxy resolution marker "4k-2k" → "4k",
 *   - a trailing "_<n>" Premiere duplicate-import suffix ("…0703a_1" → "…0703a").
 * Whitespace is collapsed; the take marker (#2) and roll/clip ids survive.
 */
function normalizedKey(name) {
  return String(name || '')
    .toLowerCase()
    .replace(/\.[a-z0-9]+$/, '')
    .replace(/4k-2k/g, '4k')
    .replace(/_\d+$/, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/** Proxy-ish tokens that shouldn't block a proxy↔original match. */
const VARIANT_NOISE = new Set(['2k', 'proxy', 'prores', 'h264', 'dnx']);

class MediaIndex {
  /** @param {object[]} media  [{ path, basename, reel?, startTc?, role? }] */
  constructor(media = []) {
    this.media = media.map((m) => ({ ...m, _tokens: new Set(normTokens(m.basename)) }));
    this.byBasenameMap = new Map(this.media.map((m) => [m.basename, m.path]));
    // Normalized-key map for the proxy↔original exact tier. A key with >1
    // candidate is AMBIGUOUS — we store the list and refuse to guess (byNormalized
    // returns null), letting the caller fall to IDF or flag it.
    this.byNormalizedMap = new Map();
    for (const m of this.media) {
      const k = normalizedKey(m.basename);
      if (!this.byNormalizedMap.has(k)) this.byNormalizedMap.set(k, []);
      this.byNormalizedMap.get(k).push(m.path);
    }
    // Document frequency per token, for IDF weighting in findTrueSource: generic
    // tokens (camera/format/resolution words common to nearly every name) weigh
    // ~nothing; distinctive tokens (the roll/date) carry the match. This is what
    // stops a generic-only overlap (e.g. a TEST roll vs a production scan) from
    // scoring high on shared boilerplate.
    this.N = this.media.length;
    this.df = new Map();
    for (const m of this.media) for (const t of m._tokens) this.df.set(t, (this.df.get(t) || 0) + 1);
  }

  /** Inverse document frequency (smoothed): rare/distinctive tokens weigh more. */
  idf(token) {
    return Math.log((this.N + 1) / ((this.df.get(token) || 0) + 1)) + 1;
  }

  byBasename(basename) {
    return this.byBasenameMap.get(basename) || null;
  }

  /**
   * Exact match on the normalized key (proxy↔original, take-marker preserving).
   * Returns the path only when EXACTLY one candidate normalizes to the same key;
   * null when none or when ambiguous (caller falls back to IDF / flags it).
   */
  byNormalized(basename) {
    const hits = this.byNormalizedMap.get(normalizedKey(basename));
    return hits && hits.length === 1 ? hits[0] : null;
  }

  byReelTc(reel, startTc) {
    const m = this.media.find((x) => x.reel === reel && (startTc == null || x.startTc === startTc));
    return m ? m.path : null;
  }

  /**
   * Find the best true-source match for a name (OCR'd or proxy basename), using
   * token overlap with proxy-noise tolerance. Returns { path, score } or null.
   */
  findTrueSource(name, opts = {}) {
    const want = [...new Set(normTokens(name))].filter((t) => !VARIANT_NOISE.has(t));
    if (!want.length) return null;
    // IDF-weighted token overlap (§10.5): distinctive roll/date tokens carry the
    // score; boilerplate (camera/format/resolution words in nearly every name)
    // weighs ~nothing. This is what stops a TEST roll from false-matching a
    // production scan on shared boilerplate alone: they share only generic tokens,
    // so the score stays well under threshold.
    //
    // Origin separation (test vs production, exclude the Tests tree) is the
    // CALLER's job: it's done by index composition — a finishing relink builds the
    // index from the finishing trees only — not by a name heuristic here, because
    // not every test source carries a "test" token (some test/dev rolls are named
    // only by look). opts.excludePathContains lets a caller drop trees inline if it
    // prefers.
    const excludePathContains = opts.excludePathContains || [];
    const totalIdf = want.reduce((s, t) => s + this.idf(t), 0);
    let best = null;
    for (const m of this.media) {
      if (excludePathContains.length && excludePathContains.some((p) => (m.path || '').includes(p))) continue;
      // A match must share at least one DISCRIMINATING token — one not present in
      // every candidate (df < N). Boilerplate alone (camera/format/resolution words
      // shared by the whole index) can never carry a match, so a TEST roll cannot
      // resolve to a production scan on boilerplate even in a small index. (Skipped
      // for a single-candidate index, where df==N for everything by definition.)
      let matchedIdf = 0;
      let discriminating = this.N <= 1;
      for (const t of want) {
        if (!m._tokens.has(t)) continue;
        matchedIdf += this.idf(t);
        if ((this.df.get(t) || 0) < this.N) discriminating = true;
      }
      if (!discriminating) continue;
      const score = totalIdf ? matchedIdf / totalIdf : 0;
      if (!best || score > best.score) best = { path: m.path, basename: m.basename, score };
    }
    const min = opts.minScore != null ? opts.minScore : 0.6;
    return best && best.score >= min ? best : null;
  }
}

module.exports = { MediaIndex, normTokens, normalizedKey };
