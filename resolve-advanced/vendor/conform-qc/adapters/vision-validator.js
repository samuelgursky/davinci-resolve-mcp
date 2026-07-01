'use strict';

/**
 * adapters/vision-validator.js — the VisionValidator adapter interface (spec §8.1).
 *
 * An OPTIONAL, ADVISORY second opinion from a vision LLM (Claude). The core never
 * calls an LLM directly — a surface injects a concrete validator (cloud /
 * post-assistant Anthropic client). When none is injected, the engine runs
 * metric-only. The advisory verdict may RAISE a flag or corroborate; it can
 * NEVER clear a flag, auto-apply, or override the deterministic verdict (§14).
 *
 * Advisory result shape:
 *   { verdict: 'MATCH'|'WRONG'|'UNSURE', confidence: number(0..1), rationale: string,
 *     advisory: true, provenance: { model, promptVersion, framesSent?, tokensUsed? } }
 */

const ADVISORY_VERDICTS = Object.freeze(['MATCH', 'WRONG', 'UNSURE']);

class VisionValidator {
  /**
   * @param {object} referenceFrame  decoded/loadable reference frame (path|buffer|{data,...})
   * @param {object} derivedFrame     decoded/loadable derived frame
   * @param {object} opts             { mode, label, context, budget }
   * @returns {Promise<object>} advisory result (shape above)
   */
  // eslint-disable-next-line class-methods-use-this, no-unused-vars
  async validate(referenceFrame, derivedFrame, opts) {
    throw new Error('VisionValidator.validate must be implemented by an adapter (e.g. the Anthropic-backed one)');
  }
}

/** Duck-typed check. */
function isVisionValidator(obj) {
  return !!obj && typeof obj.validate === 'function';
}

/** Validate/normalize an advisory result so downstream policy can trust its shape. */
function normalizeAdvisory(result) {
  if (!result || !ADVISORY_VERDICTS.includes(result.verdict)) {
    throw new Error(`VisionValidator: verdict must be one of ${ADVISORY_VERDICTS.join('|')}`);
  }
  const confidence = typeof result.confidence === 'number' ? Math.max(0, Math.min(1, result.confidence)) : 0.5;
  return {
    verdict: result.verdict,
    confidence,
    rationale: result.rationale || '',
    advisory: true, // hard-set: a VisionValidator result is ALWAYS advisory
    provenance: result.provenance || { model: 'unknown', promptVersion: '0' },
  };
}

/**
 * Deterministic fake for tests — no LLM, no network. Returns scripted verdicts
 * keyed by opts.label (then opts.mode, then 'default'), and records its calls so
 * a test can assert the cost gate (whether it was consulted at all).
 */
class FakeVisionValidator extends VisionValidator {
  constructor(script = {}) {
    super();
    this.script = script;
    this.calls = [];
  }

  // eslint-disable-next-line class-methods-use-this
  async validate(referenceFrame, derivedFrame, opts = {}) {
    this.calls.push({ opts });
    const key = (opts.label && this.script[opts.label] && opts.label)
      || (opts.mode && this.script[opts.mode] && opts.mode)
      || 'default';
    const scripted = this.script[key] || { verdict: 'UNSURE', confidence: 0.5, rationale: 'fake-default' };
    return normalizeAdvisory({ ...scripted, provenance: { model: 'fake', promptVersion: '0' } });
  }
}

module.exports = { VisionValidator, FakeVisionValidator, isVisionValidator, normalizeAdvisory, ADVISORY_VERDICTS };
