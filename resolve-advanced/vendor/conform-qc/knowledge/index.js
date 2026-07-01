'use strict';

/**
 * knowledge/ — ConformKnowledge, the LIVING failure-mode catalog (spec §9, §11).
 *
 * The catalog is not a fixed list — it grows from every run. Each diagnosed
 * failure (its successful repair strategy + outcome) is recorded keyed by a
 * pattern signature, so the next conform recognizes it faster and with higher
 * confidence. This is the seam where LLM-assisted diagnosis plugs in (§15): an
 * LLM proposes a strategy for a NOVEL signature; the deterministic engine
 * verifies and records the outcome here. The store itself is pure data + math —
 * no LLM, no IO. A surface injects persistence (cloud: DB; local: a file).
 *
 * Entry shape (§11): { patternSignature, strategy, successes, failures,
 *   occurrences, confidence, exampleRunIds[] }.
 */

/** Build a canonical, stable signature from a diagnosis descriptor (or pass a string). */
function signatureFor(diagnosis) {
  if (diagnosis == null) throw new Error('conform-qc knowledge: diagnosis is required');
  if (typeof diagnosis === 'string') return diagnosis;
  const parts = [diagnosis.class || diagnosis.failureMode];
  // scope narrows a pattern to where it recurs (e.g. a per-file offset is keyed
  // by file so each file's constant is learned independently).
  if (diagnosis.scope) parts.push(String(diagnosis.scope));
  if (diagnosis.target) parts.push(String(diagnosis.target));
  const sig = parts.filter(Boolean).join(':');
  if (!sig) throw new Error('conform-qc knowledge: diagnosis has no class/failureMode');
  return sig;
}

/** Laplace-smoothed success rate — defined even with zero observations. */
function confidenceOf(successes, failures) {
  return (successes + 1) / (successes + failures + 2);
}

class ConformKnowledge {
  /** @param {object[]} [seed] prior entries (e.g. loaded from persistence). */
  constructor(seed) {
    this.map = new Map();
    if (Array.isArray(seed)) {
      for (const e of seed) {
        const successes = e.successes || 0;
        const failures = e.failures || 0;
        this.map.set(e.patternSignature, {
          patternSignature: e.patternSignature,
          strategy: e.strategy || null,
          successes,
          failures,
          occurrences: e.occurrences != null ? e.occurrences : successes + failures,
          confidence: confidenceOf(successes, failures),
          exampleRunIds: Array.isArray(e.exampleRunIds) ? [...e.exampleRunIds] : [],
        });
      }
    }
  }

  /** Look up by signature (string) or diagnosis descriptor. null if unseen. */
  query(diagnosis) {
    return this.map.get(signatureFor(diagnosis)) || null;
  }

  /**
   * Record a diagnosed outcome. Upserts by signature; accrues confidence.
   * @param {string|object} diagnosis
   * @param {{strategy?:string, outcome:'success'|'failure', exampleRunId?:string}} obs
   * @returns {object} the updated entry
   */
  record(diagnosis, obs) {
    if (!obs || (obs.outcome !== 'success' && obs.outcome !== 'failure')) {
      throw new Error("conform-qc knowledge: outcome must be 'success' or 'failure'");
    }
    const patternSignature = signatureFor(diagnosis);
    let e = this.map.get(patternSignature);
    if (!e) {
      e = {
        patternSignature,
        strategy: obs.strategy || null,
        successes: 0,
        failures: 0,
        occurrences: 0,
        confidence: confidenceOf(0, 0),
        exampleRunIds: [],
      };
      this.map.set(patternSignature, e);
    }
    e.occurrences += 1;
    if (obs.outcome === 'success') e.successes += 1;
    else e.failures += 1;
    // The latest strategy that worked becomes the recommended one.
    if (obs.strategy && obs.outcome === 'success') e.strategy = obs.strategy;
    else if (obs.strategy && !e.strategy) e.strategy = obs.strategy;
    if (obs.exampleRunId && !e.exampleRunIds.includes(obs.exampleRunId)) {
      e.exampleRunIds.push(obs.exampleRunId);
    }
    e.confidence = confidenceOf(e.successes, e.failures);
    return e;
  }

  /** All entries (for persistence / inspection). */
  all() {
    return [...this.map.values()].map((e) => ({ ...e, exampleRunIds: [...e.exampleRunIds] }));
  }

  get size() {
    return this.map.size;
  }
}

module.exports = { ConformKnowledge, signatureFor, confidenceOf };
