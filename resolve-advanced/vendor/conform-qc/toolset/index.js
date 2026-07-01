'use strict';

/**
 * toolset/ — agent-callable tool definitions (spec §12) exposing the core
 * primitives (verify / conform / insert / package) as MCP/CLI tools an LLM can
 * drive live against cloud or local media. The agent ORCHESTRATES; the truth
 * loop it invokes stays deterministic — tool descriptions say so explicitly
 * (verdicts are deterministic; vision/LLM output is advisory-only, §8.1).
 */

const { verify } = require('../ops/verify');
const pkg = require('../packaging');

const TOOLS = Object.freeze([
  {
    name: 'conform_qc_verify',
    description:
      'Run the read-only verify pass over a conform model (parse->oracle->reference->compare->report). ' +
      'Verdicts (MATCH/OFFSET/WRONG/REVIEW/MATH-VERIFIED) are DETERMINISTIC; any vision/LLM input is advisory-only and never overrides them.',
    input_schema: {
      type: 'object',
      additionalProperties: false,
      properties: { model: { type: 'object' }, options: { type: 'object' } },
      required: ['model'],
    },
  },
  {
    name: 'conform_qc_package',
    description:
      'Build a deliverable package (media mode × formats {otio,fcp7Xml,aaf,drp}) + V2 flag track + provenance manifest from a conformed timeline. ' +
      'Auto-apply is gated to deterministic, re-verified fixes; everything else is propose-only.',
    input_schema: {
      type: 'object',
      additionalProperties: false,
      properties: { conformed: { type: 'object' }, mediaMode: { type: 'string', enum: ['relink', 'full', 'consolidate'] }, formats: { type: 'array', items: { type: 'string' } } },
      required: ['conformed'],
    },
  },
]);

/** Dispatch a tool call to the underlying primitive (the deps are injected). */
async function dispatch(name, input, deps = {}) {
  switch (name) {
    case 'conform_qc_verify':
      return (deps.verify || verify)(input.model, input.options || {});
    case 'conform_qc_package':
      return (deps.buildPackage || pkg.buildPackage)(input.conformed, { mediaMode: input.mediaMode, formats: input.formats });
    default:
      throw new Error(`toolset: unknown tool "${name}"`);
  }
}

module.exports = { TOOLS, dispatch };
