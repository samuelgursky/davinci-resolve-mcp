/**
 * Resolved DRX Generator
 *
 * Integrates the Tool Resolver with the DRX Generator to provide
 * intent-aware, tool-selection-based grade creation.
 *
 * This module wraps the existing drx-generator.js with tool resolution,
 * ensuring that:
 * - Contrast uses the appropriate tool (Lift/Gain vs. Contrast Corrector)
 * - Exposure uses proper compensation (Offset vs. Gain)
 * - Temperature uses the right approach (global vs. split)
 * - User preferences are respected
 *
 * @module drx/resolved-drx-generator
 */

const toolResolver = require('./tool-resolver');
const vocabularyIntents = require('./vocabulary-intents');
const drxGenerator = require('./drx-generator');

// ═══════════════════════════════════════════════════════════════════════════════
// RESOLVED PARAMETER CONVERSION
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Convert tool-resolved parameters to DRX generator format
 * The tool resolver outputs structured params, this converts them to flat format
 *
 * @param {Object} resolved - Output from toolResolver.resolve()
 * @returns {Object} Flat parameter object for DRX generator
 */
function convertResolvedToFlat(resolved) {
  const flat = {};
  const params = resolved.params || {};

  // ═══════════════════════════════════════════════════════════════════════════
  // Primary Wheels (Lift/Gamma/Gain)
  // ═══════════════════════════════════════════════════════════════════════════

  // Lift
  if (params.liftR !== undefined) flat.liftR = params.liftR;
  if (params.liftG !== undefined) flat.liftG = params.liftG;
  if (params.liftB !== undefined) flat.liftB = params.liftB;
  if (params.liftMaster !== undefined) flat.liftMaster = params.liftMaster;

  // Gamma
  if (params.gammaR !== undefined) flat.gammaR = params.gammaR;
  if (params.gammaG !== undefined) flat.gammaG = params.gammaG;
  if (params.gammaB !== undefined) flat.gammaB = params.gammaB;
  if (params.gammaMaster !== undefined) flat.gammaMaster = params.gammaMaster;

  // Gain
  if (params.gainR !== undefined) flat.gainR = params.gainR;
  if (params.gainG !== undefined) flat.gainG = params.gainG;
  if (params.gainB !== undefined) flat.gainB = params.gainB;
  if (params.gainMaster !== undefined) flat.gainMaster = params.gainMaster;

  // Offset
  if (params.offsetR !== undefined) flat.offsetR = params.offsetR;
  if (params.offsetG !== undefined) flat.offsetG = params.offsetG;
  if (params.offsetB !== undefined) flat.offsetB = params.offsetB;

  // ═══════════════════════════════════════════════════════════════════════════
  // Log Wheels
  // ═══════════════════════════════════════════════════════════════════════════

  if (params.logShadowR !== undefined) flat.logShadowR = params.logShadowR;
  if (params.logShadowG !== undefined) flat.logShadowG = params.logShadowG;
  if (params.logShadowB !== undefined) flat.logShadowB = params.logShadowB;
  if (params.logMidR !== undefined) flat.logMidR = params.logMidR;
  if (params.logMidG !== undefined) flat.logMidG = params.logMidG;
  if (params.logMidB !== undefined) flat.logMidB = params.logMidB;
  if (params.logHighR !== undefined) flat.logHighR = params.logHighR;
  if (params.logHighG !== undefined) flat.logHighG = params.logHighG;
  if (params.logHighB !== undefined) flat.logHighB = params.logHighB;

  // ═══════════════════════════════════════════════════════════════════════════
  // Contrast Corrector
  // ═══════════════════════════════════════════════════════════════════════════

  if (params.contrast !== undefined) flat.contrast = params.contrast;
  if (params.pivot !== undefined) flat.pivot = params.pivot;
  if (params.contrastHighRange !== undefined) flat.contrastHighRange = params.contrastHighRange;
  if (params.contrastLowRange !== undefined) flat.contrastLowRange = params.contrastLowRange;
  if (params.softClipHigh !== undefined) flat.softClipHigh = params.softClipHigh;
  if (params.softClipLow !== undefined) flat.softClipLow = params.softClipLow;

  // ═══════════════════════════════════════════════════════════════════════════
  // Temperature/Tint/Saturation
  // ═══════════════════════════════════════════════════════════════════════════

  if (params.temperature !== undefined) flat.temperature = params.temperature;
  if (params.tint !== undefined) flat.tint = params.tint;
  if (params.saturation !== undefined) flat.saturation = params.saturation;
  if (params.colorBoost !== undefined) flat.colorBoost = params.colorBoost;
  if (params.midtoneDetail !== undefined) flat.midtoneDetail = params.midtoneDetail;

  // ═══════════════════════════════════════════════════════════════════════════
  // HDR Zones
  // ═══════════════════════════════════════════════════════════════════════════

  if (params.hdrDark !== undefined) flat.hdrDark = params.hdrDark;
  if (params.hdrShadow !== undefined) flat.hdrShadow = params.hdrShadow;
  if (params.hdrLight !== undefined) flat.hdrLight = params.hdrLight;
  if (params.hdrHighlight !== undefined) flat.hdrHighlight = params.hdrHighlight;
  if (params.hdrGlobal !== undefined) flat.hdrGlobal = params.hdrGlobal;

  return flat;
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN INTERFACE
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Generate a DRX file with tool-aware parameter resolution
 *
 * @param {Object} options
 * @param {Object} options.adjustments - Raw adjustments from AI or vocabulary
 *   { contrast, exposure, temperature, saturation, tint, shadowLift, etc. }
 * @param {Object} options.intent - Optional intent signals
 *   { contrast: 'punchy', temperature: 'split', etc. }
 * @param {string} options.nodeLabel - Node label for the grade
 * @param {Object} options.userPreferences - Optional user preferences override
 * @returns {Promise<Buffer>} DRX file buffer
 */
async function generateResolvedDRX(options) {
  const {
    adjustments = {},
    intent = {},
    nodeLabel = 'Color Grade',
    userPreferences = null,
  } = options;

  // Apply user preferences if provided
  if (userPreferences) {
    toolResolver.setUserPreferences(userPreferences);
  }

  // Resolve tools based on adjustments and intent
  const resolved = toolResolver.resolve({ adjustments, intent });

  // Log resolution for debugging
  console.log('[ResolvedDRX] Tool resolution:', {
    tools: resolved.tools,
    inputAdjustments: Object.keys(adjustments).filter(k => adjustments[k] !== undefined),
    intent: Object.keys(intent).filter(k => intent[k] !== undefined),
  });

  // Convert to flat format for DRX generator
  const flatParams = convertResolvedToFlat(resolved);

  // Convert flat params to structured format using parseAdjustments
  const gradeParams = drxGenerator.parseAdjustments(flatParams);

  // Generate DRX using existing generator
  const drxContent = await drxGenerator.generateDRX(gradeParams, {
    label: nodeLabel,
  });

  // Convert string to buffer for consistency
  const drxBuffer = Buffer.from(drxContent, 'utf8');

  return {
    buffer: drxBuffer,
    resolved: {
      tools: resolved.tools,
      params: flatParams,
      intent,
      metadata: resolved.metadata,
    },
  };
}

/**
 * Generate a DRX file from a user request string
 * Extracts intents automatically from the request text
 *
 * @param {Object} options
 * @param {string} options.request - User request string (e.g., "make it punchy and warm")
 * @param {Object} options.adjustments - Adjustments from vocabulary/AI lookup
 * @param {string} options.nodeLabel - Node label
 * @param {Object} options.userPreferences - Optional user preferences
 * @returns {Promise<Object>} { buffer, resolved }
 */
async function generateFromRequest(options) {
  const {
    request = '',
    adjustments = {},
    nodeLabel = 'Color Grade',
    userPreferences = null,
  } = options;

  // Extract intents from the request string
  const intent = vocabularyIntents.extractIntentsFromRequest(request);

  console.log('[ResolvedDRX] Extracted intents from request:', {
    request: request.substring(0, 50) + (request.length > 50 ? '...' : ''),
    intent,
  });

  return generateResolvedDRX({
    adjustments,
    intent,
    nodeLabel,
    userPreferences,
  });
}

/**
 * Generate multi-node DRX with tool resolution
 * Each node can have its own adjustments and intent
 *
 * @param {Object} options
 * @param {Array} options.nodes - Array of { adjustments, intent, label }
 * @param {Object} options.userPreferences - Optional user preferences
 * @returns {Promise<Object>} { buffer, resolved }
 */
async function generateMultiNodeResolvedDRX(options) {
  const {
    nodes = [],
    userPreferences = null,
  } = options;

  if (userPreferences) {
    toolResolver.setUserPreferences(userPreferences);
  }

  // Resolve each node
  const resolvedNodes = nodes.map((node, idx) => {
    const resolved = toolResolver.resolve({
      adjustments: node.adjustments || {},
      intent: node.intent || {},
    });

    const flatParams = convertResolvedToFlat(resolved);

    return {
      label: node.label || `Node ${idx + 1}`,
      flatParams,
      // Convert flat params to structured format for DRX generator
      params: drxGenerator.parseAdjustments(flatParams),
      tools: resolved.tools,
      intent: node.intent || {},
    };
  });

  // Convert to format expected by generateMultiNodeDRX
  const nodeConfigs = resolvedNodes.map(node => ({
    label: node.label,
    params: node.params,
  }));

  // Build default serial connections (node 1 → 2 → 3 → ...)
  const connections = [];
  for (let i = 0; i < nodeConfigs.length - 1; i++) {
    connections.push({ from: i + 1, to: i + 2 });
  }

  // Generate using existing multi-node generator
  const drxContent = await drxGenerator.generateMultiNodeDRX(nodeConfigs, connections, {
    label: 'Multi-Node Grade',
  });

  // Convert to buffer
  const drxBuffer = Buffer.from(drxContent, 'utf8');

  return {
    buffer: drxBuffer,
    resolved: resolvedNodes,
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// UTILITY FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Preview tool resolution without generating DRX
 * Useful for debugging or showing users what tools will be used
 *
 * @param {Object} options
 * @param {Object} options.adjustments - Raw adjustments
 * @param {Object} options.intent - Intent signals
 * @returns {Object} Resolution preview
 */
function previewResolution(options) {
  const { adjustments = {}, intent = {} } = options;

  const resolved = toolResolver.resolve({ adjustments, intent });

  // Build human-readable summary
  const summary = [];

  if (resolved.tools.contrast) {
    const tool = toolResolver.getCurrentTool('contrast') || {};
    summary.push({
      adjustment: 'Contrast',
      tool: resolved.tools.contrast,
      toolName: tool.name || resolved.tools.contrast,
      reason: intent.contrast ? `Intent: ${intent.contrast}` : 'Default preference',
    });
  }

  if (resolved.tools.exposure) {
    const tool = toolResolver.getCurrentTool('exposure') || {};
    summary.push({
      adjustment: 'Exposure',
      tool: resolved.tools.exposure,
      toolName: tool.name || resolved.tools.exposure,
      reason: intent.exposure ? `Intent: ${intent.exposure}` : 'Default preference',
    });
  }

  if (resolved.tools.temperature) {
    const tool = toolResolver.getCurrentTool('temperature') || {};
    summary.push({
      adjustment: 'Temperature',
      tool: resolved.tools.temperature,
      toolName: tool.name || resolved.tools.temperature,
      reason: intent.temperature ? `Intent: ${intent.temperature}` : 'Default preference',
    });
  }

  if (resolved.tools.saturation) {
    const tool = toolResolver.getCurrentTool('saturation') || {};
    summary.push({
      adjustment: 'Saturation',
      tool: resolved.tools.saturation,
      toolName: tool.name || resolved.tools.saturation,
      reason: intent.saturation ? `Intent: ${intent.saturation}` : 'Default preference',
    });
  }

  return {
    summary,
    tools: resolved.tools,
    params: resolved.params,
    metadata: resolved.metadata,
  };
}

/**
 * Get available tools for an adjustment type
 * @param {string} adjustmentType
 * @returns {Object[]} Array of tool descriptions
 */
function getAvailableTools(adjustmentType) {
  return toolResolver.getAvailableTools(adjustmentType);
}

/**
 * Set user preferences for the resolver
 * @param {Object} prefs
 */
function setUserPreferences(prefs) {
  toolResolver.setUserPreferences(prefs);
}

/**
 * Get current user preferences
 * @returns {Object}
 */
function getUserPreferences() {
  return toolResolver.defaultResolver.preferences;
}

// ═══════════════════════════════════════════════════════════════════════════════
// EXPORTS
// ═══════════════════════════════════════════════════════════════════════════════

module.exports = {
  // Main generation functions
  generateResolvedDRX,
  generateFromRequest,
  generateMultiNodeResolvedDRX,

  // Utilities
  previewResolution,
  getAvailableTools,
  setUserPreferences,
  getUserPreferences,
  convertResolvedToFlat,

  // Re-export tool resolver for direct access
  toolResolver,

  // Re-export vocabulary intents for direct access
  vocabularyIntents,

  // Re-export original generator for bypass cases
  drxGenerator,
};
