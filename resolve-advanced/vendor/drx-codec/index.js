/**
 * drx-codec — DRX Codec Stack
 *
 * Deterministic, offline DRX generation and parsing: node-graph generate/parse,
 * request→grade resolution, tool selection, CDL export, grade merging, and NLP
 * parsing of colorist vocabulary. All local — no LLM, no network.
 *
 * @module drx-codec
 */

// Core generation
const drxGenerator = require('./drx-generator');
const resolvedDrxGenerator = require('./resolved-drx-generator');

// Tool resolution system
const toolResolver = require('./tool-resolver');
const vocabularyIntents = require('./vocabulary-intents');

// DRX parsing
const drxParser = require('./drx-parser');

// CDL export
const cdlExporter = require('./cdl-exporter');

// Grade merging
const drxMerger = require('./drx-merger');

// NLP parsing (deterministic colorist-vocabulary → params)
const colorNlpParser = require('./color-nlp-parser');

// Look recipes / named look presets with concrete adjustment values
const lookRecipes = require('./training-examples');

// P1.1 — extract custom (YRGB) curves from a corrector's parameter list
const extractCustomCurvesModule = require('./extract-custom-curves');
// P1.2 — extract HSL curves (hueVs* / satVs* / lumVs*) from a corrector
const extractHSLCurvesModule = require('./extract-hsl-curves');
// P1.3 — extract HSL qualifier regions from a Corrector Type 2 param list
const extractQualifierModule = require('./extract-qualifier');
// P1.4 — extract power window settings from a Corrector Type 4 param list
const extractPowerWindowModule = require('./extract-power-window');
// P1.5 — extract matte finesse cleanup from a Corrector Type 9 param list
const extractMatteFinesseModule = require('./extract-matte-finesse');
// P1.6 — extract RESOLVEFX/OFX plugin parameter bags from a node's tool list
const extractOFXParamsModule = require('./extract-ofx-params');
// P5.1 — extract per-node LUT references (Resolve "Right-click → LUT")
const extractLutRefsModule = require('./extract-lut-refs');

module.exports = {
  // Core generation
  drxGenerator,
  resolvedDrxGenerator,

  // Tool resolution
  toolResolver,
  vocabularyIntents,

  // Parsing
  drxParser,

  // CDL export
  cdlExporter,

  // Grade merging
  drxMerger,

  // NLP parsing
  colorNlpParser,

  // Look recipes
  lookRecipes,

  // P1.1 — DRX parser parity for custom curves
  extractCustomCurves: extractCustomCurvesModule.extractCustomCurves,

  // P1.2 — DRX parser parity for HSL curves
  extractHSLCurves: extractHSLCurvesModule.extractHSLCurves,

  // P1.3 — DRX parser parity for HSL qualifier regions
  extractQualifier: extractQualifierModule.extractQualifier,

  // P1.4 — DRX parser parity for power windows
  extractPowerWindow: extractPowerWindowModule.extractPowerWindow,

  // P1.5 — DRX parser parity for matte finesse cleanup
  // (external matte refs deferred — see resolve-verifications.md)
  extractMatteFinesse: extractMatteFinesseModule.extractMatteFinesse,

  // P1.6 — DRX parser parity for RESOLVEFX/OFX plugin parameter bags
  // (Film Grain at minimum; P2.1 will expand the tool registry)
  extractOFXParams: extractOFXParamsModule.extractOFXParams,
  extractOFXTools: extractOFXParamsModule.extractOFXTools,

  // P5.1 — DRX parser parity for per-node LUT references
  extractNodeLutRef: extractLutRefsModule.extractNodeLutRef,
  extractDrxLutRefs: extractLutRefsModule.extractDrxLutRefs,

  // Convenience functions (backwards-compatible with post-assistant's old index)
  generateGrade: resolvedDrxGenerator.generateResolvedDRX,
  generateFromRequest: resolvedDrxGenerator.generateFromRequest,
  previewTools: resolvedDrxGenerator.previewResolution,
  extractIntents: (input) => {
    if (typeof input === 'string' && input.includes(' ')) {
      return vocabularyIntents.extractIntentsFromRequest(input);
    }
    return vocabularyIntents.extractIntents(input);
  },
  getAvailableTools: toolResolver.getAvailableTools,
};
