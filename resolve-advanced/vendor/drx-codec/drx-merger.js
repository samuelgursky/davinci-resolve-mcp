/**
 * DRX Merger - Combine existing grade with new adjustments
 *
 * Takes parsed nodes from an existing DRX and new adjustment nodes,
 * combines them into a single DRX with proper node IDs and connections.
 *
 * Used for "Refine" workflow: preserves existing grade while appending new nodes.
 *
 * @module drx/drx-merger
 */

const { generateMultiNodeDRX } = require('./drx-generator');
const drxParams = require('../drx-parameters');

/**
 * Build default node parameters using the shared DRX parameter library
 * @returns {Object} - Default parameter structure for a DRX node
 */
function buildDefaultNodeParams() {
  return {
    lift: {
      r: drxParams.getDefault('lift', 'r'),
      g: drxParams.getDefault('lift', 'g'),
      b: drxParams.getDefault('lift', 'b'),
      master: drxParams.getDefault('lift', 'master'),
    },
    gamma: {
      r: drxParams.getDefault('gamma', 'r'),
      g: drxParams.getDefault('gamma', 'g'),
      b: drxParams.getDefault('gamma', 'b'),
      master: drxParams.getDefault('gamma', 'master'),
    },
    gain: {
      r: drxParams.getDefault('gain', 'r'),
      g: drxParams.getDefault('gain', 'g'),
      b: drxParams.getDefault('gain', 'b'),
      master: drxParams.getDefault('gain', 'master'),
    },
    offset: {
      r: drxParams.getDefault('offset', 'r'),
      g: drxParams.getDefault('offset', 'g'),
      b: drxParams.getDefault('offset', 'b'),
    },
    saturation: drxParams.getDefault('saturation', 'master'),
    contrast: drxParams.getDefault('contrast', 'master'),
    pivot: drxParams.getDefault('pivotFine', 'master'),
  };
}

/**
 * Convert parsed node structure to generator format
 *
 * @param {Object} parsedNode - Node from drx-parser
 * @param {number} newId - New node ID to assign
 * @param {number} xOffset - X position offset
 * @returns {Object} - Node in generator format
 */
function convertParsedNode(parsedNode, newId, xOffset = 0) {
  // Ensure label is a string (handle Buffer, object, or string)
  let label = parsedNode.label;
  if (Buffer.isBuffer(label)) {
    label = label.toString('utf8');
  } else if (typeof label === 'object' && label !== null) {
    // Handle case where parser returned an object instead of string
    label = `Node ${newId}`;
  } else if (typeof label !== 'string') {
    label = `Node ${newId}`;
  }
  // Check for "[object Object]" string which indicates a conversion issue
  if (!label || label.trim() === '' || label === '[object Object]') {
    label = `Existing Node ${newId}`;
  }

  // Get params, ensuring proper structure - use shared library for defaults
  const defaultParams = buildDefaultNodeParams();

  // Deep merge parsed params with defaults
  const params = parsedNode.params ? {
    lift: { ...defaultParams.lift, ...(parsedNode.params.lift || {}) },
    gamma: { ...defaultParams.gamma, ...(parsedNode.params.gamma || {}) },
    gain: { ...defaultParams.gain, ...(parsedNode.params.gain || {}) },
    offset: { ...defaultParams.offset, ...(parsedNode.params.offset || {}) },
    saturation: parsedNode.params.saturation ?? defaultParams.saturation,
    contrast: parsedNode.params.contrast ?? defaultParams.contrast,
    pivot: parsedNode.params.pivot ?? defaultParams.pivot,
  } : defaultParams;

  console.log(`[DRX Merger] Converting node: id=${parsedNode.id}, label="${label}", has params:`, !!parsedNode.params);

  return {
    id: newId,
    label,
    xPos: (parsedNode.xPos || 190) + xOffset,
    yPos: parsedNode.yPos || 180,
    enabled: parsedNode.enabled !== false,
    params,
  };
}

/**
 * Merge existing nodes with new adjustment nodes
 *
 * @param {Array} existingNodes - Nodes from parsed DRX
 * @param {Array} newNodes - New nodes from adjustment generation
 * @param {Object} options - Merge options
 * @returns {Object} - Combined nodes and connections
 */
function mergeNodes(existingNodes, newNodes, options = {}) {
  const {
    nodeSpacing = 270,
    baseX = 190,
    baseY = 180,
  } = options;

  const combinedNodes = [];
  const connections = [];

  console.log(`[DRX Merger] Merging ${existingNodes.length} existing + ${newNodes.length} new nodes`);

  // PRESERVE original node IDs - find the range
  let minId = Infinity;
  let maxId = 0;
  let currentX = baseX;

  // First pass: add existing nodes PRESERVING their original IDs
  for (const existingNode of existingNodes) {
    const originalId = existingNode.id;
    if (originalId < minId) minId = originalId;
    if (originalId > maxId) maxId = originalId;

    // Ensure label is a string (handle Buffer, object, or string)
    let label = existingNode.label;
    if (Buffer.isBuffer(label)) {
      label = label.toString('utf8');
    } else if (typeof label === 'object' && label !== null) {
      // Handle case where parser returned an object instead of string
      label = `Node ${originalId}`;
    } else if (typeof label !== 'string') {
      label = `Node ${originalId}`;
    }
    // Check for "[object Object]" string which indicates a conversion issue
    if (!label || label.trim() === '' || label === '[object Object]') {
      label = `Existing Node ${originalId}`;
    }

    const node = {
      id: originalId,  // PRESERVE original ID
      label,
      xPos: existingNode.xPos || currentX,
      yPos: existingNode.yPos || baseY,
      enabled: existingNode.enabled !== false,
      params: existingNode.params || buildDefaultNodeParams(),
    };
    combinedNodes.push(node);

    console.log(`[DRX Merger] Existing node id=${originalId}: "${node.label}"`);
    currentX = Math.max(currentX, (existingNode.xPos || baseX) + nodeSpacing);
  }

  // Then add new adjustment nodes, continuing from maxId+1
  let nextId = maxId + 1;
  for (const newNode of newNodes) {
    const node = {
      id: nextId,
      label: newNode.label || `Adjustment ${nextId}`,
      xPos: currentX,
      yPos: newNode.yPos || baseY,
      enabled: newNode.enabled !== false,
      params: newNode.params,
    };
    combinedNodes.push(node);

    console.log(`[DRX Merger] New node id=${nextId}: "${node.label}"`);
    nextId++;
    currentX += nodeSpacing;
  }

  // Sort by ID to ensure proper order
  combinedNodes.sort((a, b) => a.id - b.id);

  // Create connections based on ACTUAL node IDs (not indices)
  const nodeIds = combinedNodes.map(n => n.id);
  for (let i = 0; i < nodeIds.length - 1; i++) {
    connections.push({
      from: nodeIds[i],
      to: nodeIds[i + 1],
    });
  }

  console.log(`[DRX Merger] Created ${connections.length} connections: ${nodeIds.join(' → ')}`);

  // Calculate baseNodeId for generator (minId - 1, so generator's baseNodeId + 1 = minId)
  const baseNodeId = minId - 1;
  const lastNodeId = nextId - 1;

  return {
    nodes: combinedNodes,
    connections,
    firstNodeId: minId,
    lastNodeId: lastNodeId,
    baseNodeId: baseNodeId,  // Pass to generator
  };
}

/**
 * Generate a merged DRX file from existing and new nodes
 *
 * @param {Object} existingDRX - Parsed DRX structure from drx-parser
 * @param {Array} newNodes - New adjustment nodes (from parseAdjustmentsToNodes)
 * @param {Object} metadata - Optional metadata overrides
 * @returns {Promise<string>} - Complete DRX XML content
 */
async function generateMergedDRX(existingDRX, newNodes, metadata = {}) {
  // Merge the node lists
  const merged = mergeNodes(existingDRX.nodes, newNodes);

  // PRESERVE ORIGINAL IDs MODE: Keep existing node IDs, assign new ones sequentially
  // Analysis shows Resolve calculates F9/F10 markers based on actual node IDs:
  //   - F9.F1 = firstNodeId + 6
  //   - F10.F1 = lastNodeId + 7
  //   - F9.F3.F1 = firstNodeId + 22
  //   - F10.F3.F1 = lastNodeId + 23
  // Using fresh IDs breaks this relationship

  // Find the max ID from existing nodes to continue from
  const existingMaxId = Math.max(...existingDRX.nodes.map(n => n.id));
  let nextId = existingMaxId + 1;

  // Assign IDs: preserve existing, assign new sequential IDs to new nodes
  const nodesWithIds = merged.nodes.map((node, index) => {
    if (index < existingDRX.nodes.length) {
      // Existing node - preserve its ID
      return { ...node, id: existingDRX.nodes[index].id };
    } else {
      // New node - assign next sequential ID
      return { ...node, id: nextId++ };
    }
  });

  const firstNodeId = nodesWithIds[0].id;
  const lastNodeId = nodesWithIds[nodesWithIds.length - 1].id;

  // Create connections with actual node IDs
  const connections = [];
  for (let i = 0; i < nodesWithIds.length - 1; i++) {
    connections.push({
      from: nodesWithIds[i].id,
      to: nodesWithIds[i + 1].id,
    });
  }

  // Use metadata from existing DRX, with overrides
  const drxMetadata = {
    label: metadata.label || `${existingDRX.label || 'Grade'} (Refined)`,
    width: metadata.width || existingDRX.width || 1920,
    height: metadata.height || existingDRX.height || 1080,
    sourceTimeline: metadata.sourceTimeline || existingDRX.sourceTimeline || 'Timeline 1',
    sourceTC: metadata.sourceTC || existingDRX.sourceTC || '00:00:00:00',
    recordTC: metadata.recordTC || existingDRX.recordTC || '01:00:00:00',
    // Preserve pTrackVer from original if available
    pTrackVerXml: existingDRX.pTrackVerXml || null,
    // PRESERVE MODE: use actual node IDs
    preserveNodeIds: true,
    baseNodeId: lastNodeId,  // version = lastNodeId
    firstNodeId: firstNodeId,
    lastNodeId: lastNodeId,
  };

  console.log(`[DRX Merger] Generating merged DRX with ${nodesWithIds.length} nodes (PRESERVED IDs ${firstNodeId}-${lastNodeId})`);

  // Generate the combined DRX with preserved node IDs
  return generateMultiNodeDRX(nodesWithIds, connections, drxMetadata);
}

/**
 * Quick merge: parse existing DRX file and merge with new nodes
 *
 * @param {string} existingDRXPath - Path to existing DRX file
 * @param {Array} newNodes - New adjustment nodes
 * @param {Object} metadata - Optional metadata overrides
 * @returns {Promise<string>} - Complete DRX XML content
 */
async function quickMerge(existingDRXPath, newNodes, metadata = {}) {
  const { parseDRX } = require('./drx-parser');

  console.log(`[DRX Merger] Quick merge: parsing ${existingDRXPath}`);
  const existingDRX = await parseDRX(existingDRXPath);

  console.log(`[DRX Merger] Existing DRX has ${existingDRX.nodes.length} nodes`);
  return generateMergedDRX(existingDRX, newNodes, metadata);
}

/**
 * Merge from DRX content string (not file)
 *
 * @param {string} existingDRXContent - DRX XML content
 * @param {Array} newNodes - New adjustment nodes
 * @param {Object} metadata - Optional metadata overrides
 * @returns {Promise<string>} - Complete DRX XML content
 */
async function mergeFromContent(existingDRXContent, newNodes, metadata = {}) {
  const { parseDRXContent } = require('./drx-parser');

  console.log(`[DRX Merger] Merging from content`);
  const existingDRX = await parseDRXContent(existingDRXContent);

  console.log(`[DRX Merger] Existing DRX has ${existingDRX.nodes.length} nodes`);
  return generateMergedDRX(existingDRX, newNodes, metadata);
}

module.exports = {
  mergeNodes,
  generateMergedDRX,
  quickMerge,
  mergeFromContent,
  convertParsedNode,
  buildDefaultNodeParams,
  // Re-export shared library for convenience
  drxParams,
};
