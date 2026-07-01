/**
 * Fusion Composition Generator — Programmatic .comp File Creation
 *
 * Generates DaVinci Resolve Fusion composition files (.comp) from
 * a declarative node specification. Analogous to drx-generator for
 * the Color page — this is the composition engine.
 *
 * The .comp format is plaintext Lua-like syntax that Resolve's Fusion page
 * can import via TimelineItem.ImportFusionComp(path).
 *
 * @module fusion-codec/composition-generator
 */

const RESOLVE_VERSION = '19.1';

// ─── Serialization Helpers ───────────────────────────────────────────────

/**
 * Serialize a JavaScript value to Fusion script syntax
 */
function serializeValue(value, indent = 0) {
  if (value === null || value === undefined) return 'nil';
  if (typeof value === 'boolean') return value ? '1' : '0';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return `"${value.replace(/"/g, '\\"')}"`;

  // Point/XY table: { x: 0.5, y: 0.5 } → { 0.5, 0.5 }
  if (typeof value === 'object' && 'x' in value && 'y' in value && Object.keys(value).length === 2) {
    return `{ ${value.x}, ${value.y} }`;
  }

  // RGB table: { r: 1, g: 0.5, b: 0 } → { 1, 0.5, 0 }
  if (typeof value === 'object' && 'r' in value && 'g' in value && 'b' in value) {
    return `{ ${value.r}, ${value.g}, ${value.b} }`;
  }

  // Generic array
  if (Array.isArray(value)) {
    const items = value.map(v => serializeValue(v, indent + 1));
    return `{ ${items.join(', ')} }`;
  }

  // Generic object → Lua table
  if (typeof value === 'object') {
    const pad = '\t'.repeat(indent + 1);
    const entries = Object.entries(value).map(
      ([k, v]) => `${pad}${k} = ${serializeValue(v, indent + 1)}`
    );
    return `{\n${entries.join(',\n')}\n${'\t'.repeat(indent)}}`;
  }

  return String(value);
}

/**
 * Serialize a single input value with optional Input wrapper
 */
function serializeInput(name, value, indent) {
  const pad = '\t'.repeat(indent);

  // Connection reference: "ToolName.Output" → special syntax
  if (typeof value === 'string' && value.includes('.') && !value.startsWith('"')) {
    return `${pad}${name} = Input { SourceOp = "${value.split('.')[0]}", Source = "${value.split('.')[1]}" },`;
  }

  // Keyframed value: { keyframes: [{time, value}, ...] }
  if (typeof value === 'object' && value !== null && value.keyframes) {
    const kfEntries = value.keyframes.map(kf =>
      `\t\t\t\t[${kf.time}] = ${serializeValue(kf.value)}`
    ).join(',\n');
    return `${pad}${name} = Input {\n${pad}\tSourceOp = "Path1",\n${pad}\tSource = "Value",\n${pad}\tKeyFrames = {\n${kfEntries}\n${pad}\t}\n${pad}},`;
  }

  // Simple value
  return `${pad}${name} = Input { Value = ${serializeValue(value, indent)} },`;
}

// ─── Node Serialization ─────────────────────────────────────────────────

/**
 * Generate the Fusion script text for a single tool/node
 */
function serializeNode(node) {
  const name = node.name || `${node.type}1`;
  const lines = [];

  lines.push(`\t${node.type} {`);
  lines.push(`\t\tCtrlWZoom = false,`);
  if (node.viewX !== undefined && node.viewY !== undefined) {
    lines.push(`\t\tViewInfo = OperatorInfo { Pos = { ${node.viewX}, ${node.viewY} } },`);
  }
  lines.push(`\t\tInputs = {`);

  // Emit inputs
  if (node.inputs) {
    for (const [inputName, inputValue] of Object.entries(node.inputs)) {
      lines.push(serializeInput(inputName, inputValue, 3));
    }
  }

  // Emit connections as inputs
  if (node.connections) {
    for (const [inputName, sourceRef] of Object.entries(node.connections)) {
      const [srcTool, srcOutput] = sourceRef.includes('.')
        ? sourceRef.split('.')
        : [sourceRef, 'Output'];
      lines.push(`\t\t\t${inputName} = Input {`);
      lines.push(`\t\t\t\tSourceOp = "${srcTool}",`);
      lines.push(`\t\t\t\tSource = "${srcOutput}",`);
      lines.push(`\t\t\t},`);
    }
  }

  // Effect mask connection
  if (node.effectMask) {
    const [srcTool, srcOutput] = node.effectMask.includes('.')
      ? node.effectMask.split('.')
      : [node.effectMask, 'Mask'];
    lines.push(`\t\t\tEffectMask = Input {`);
    lines.push(`\t\t\t\tSourceOp = "${srcTool}",`);
    lines.push(`\t\t\t\tSource = "${srcOutput}",`);
    lines.push(`\t\t\t},`);
  }

  lines.push(`\t\t},`);

  // Custom name via UserControls/NameSet
  if (node.name && node.name !== `${node.type}1`) {
    lines.push(`\t\tName = "${node.name}",`);
  }

  lines.push(`\t},`);

  return { name, script: lines.join('\n') };
}

// ─── Composition Generator ──────────────────────────────────────────────

/**
 * Generate a complete Fusion .comp file from a node specification.
 *
 * @param {Object} spec - Composition specification
 * @param {Array} spec.nodes - Array of node definitions
 * @param {Array} [spec.keyframes] - Optional keyframe definitions
 * @param {Object} [spec.metadata] - Optional metadata
 * @param {Object} [options] - Generation options
 * @param {string} [options.label] - Composition label
 * @param {number} [options.width=1920] - Composition width
 * @param {number} [options.height=1080] - Composition height
 * @param {number} [options.fps=24] - Frame rate
 * @param {number} [options.startFrame=0] - Start frame
 * @param {number} [options.endFrame=100] - End frame
 * @returns {string} The .comp file content as a string
 */
function generateComp(spec, options = {}) {
  const {
    label = 'Composition',
    width = 1920,
    height = 1080,
    fps = 24,
    startFrame = 0,
    endFrame = 100,
  } = options;

  const nodes = spec.nodes || [];
  if (nodes.length === 0) {
    throw new Error('At least one node is required');
  }

  // Auto-assign view positions if not specified
  let viewX = 0;
  for (const node of nodes) {
    if (node.viewX === undefined) {
      node.viewX = viewX;
      node.viewY = node.viewY || 0;
      viewX += 110; // horizontal spacing
    }
  }

  // Build the tool name → node map for validation
  const nodeNames = new Set(nodes.map(n => n.name || `${n.type}1`));

  // Serialize all nodes
  const serializedNodes = nodes.map(n => serializeNode(n));

  // Build the composition script
  const lines = [];

  lines.push(`{`);
  lines.push(`\tTools = ordered() {`);

  for (const { name, script } of serializedNodes) {
    lines.push(`\t-- ${name}`);
    lines.push(script);
    lines.push('');
  }

  lines.push(`\t},`);

  // Active tool (last node before MediaOut, or last node)
  const lastNonOutput = nodes.filter(n => n.type !== 'MediaOut').pop();
  if (lastNonOutput) {
    lines.push(`\tActiveTool = "${lastNonOutput.name || lastNonOutput.type + '1'}",`);
  }

  lines.push(`}`);

  return lines.join('\n');
}

/**
 * Generate a .comp from a named template with parameters.
 *
 * @param {string} templateName - Template identifier
 * @param {Object} params - Template-specific parameters
 * @param {Object} [options] - Generation options (width, height, fps, etc.)
 * @returns {{ compContent: string, label: string, nodeCount: number, breakdown: Object }}
 */
function generateFromTemplate(templateName, params = {}, options = {}) {
  const template = loadTemplate(templateName);
  if (!template) {
    throw new Error(`Template "${templateName}" not found. Use listTemplates() for available templates.`);
  }

  const spec = template.generate(params);
  const label = params.label || template.label || templateName;
  const compContent = generateComp(spec, { ...options, label });

  return {
    compContent,
    label,
    nodeCount: spec.nodes.length,
    breakdown: {
      template: templateName,
      description: template.description,
      nodes: spec.nodes.map(n => ({ name: n.name, type: n.type })),
      parameters: params,
    },
  };
}

/**
 * Convert a composition spec to a sequence of API calls
 * for the OSS MCP fusion_comp tool (live API path).
 *
 * @param {Object} spec - Same spec format as generateComp
 * @returns {Array<Object>} Array of { action, params } objects
 */
function specToApiCalls(spec) {
  const calls = [];
  const nodes = spec.nodes || [];

  // Start undo group
  calls.push({ action: 'start_undo', params: { name: 'Composition' } });

  // Add all tools
  for (const node of nodes) {
    const name = node.name || `${node.type}1`;
    calls.push({
      action: 'add_tool',
      params: {
        tool_type: node.type,
        name,
        x: node.viewX || 0,
        y: node.viewY || 0,
      },
    });
  }

  // Set inputs (parameters)
  for (const node of nodes) {
    const name = node.name || `${node.type}1`;
    if (node.inputs) {
      for (const [inputName, value] of Object.entries(node.inputs)) {
        // Skip connection-like values — those go through connect
        if (typeof value === 'string' && value.includes('.')) continue;
        calls.push({
          action: 'set_input',
          params: { tool_name: name, input_name: inputName, value },
        });
      }
    }
  }

  // Wire connections
  for (const node of nodes) {
    const name = node.name || `${node.type}1`;
    if (node.connections) {
      for (const [inputName, sourceRef] of Object.entries(node.connections)) {
        const [srcTool, srcOutput] = sourceRef.includes('.')
          ? sourceRef.split('.')
          : [sourceRef, 'Output'];
        calls.push({
          action: 'connect',
          params: {
            target_tool: name,
            input_name: inputName,
            source_tool: srcTool,
            output_name: srcOutput,
          },
        });
      }
    }
    if (node.effectMask) {
      const [srcTool] = node.effectMask.includes('.')
        ? node.effectMask.split('.')
        : [node.effectMask];
      calls.push({
        action: 'connect',
        params: {
          target_tool: name,
          input_name: 'EffectMask',
          source_tool: srcTool,
        },
      });
    }
  }

  // Set keyframes
  if (spec.keyframes) {
    for (const kf of spec.keyframes) {
      calls.push({
        action: 'add_keyframe',
        params: {
          tool_name: kf.tool,
          input_name: kf.input,
          time: kf.time,
          value: kf.value,
        },
      });
    }
  }

  // End undo group
  calls.push({ action: 'end_undo', params: { keep: true } });

  return calls;
}

// ─── Template Registry ──────────────────────────────────────────────────

const TEMPLATES = {};

function registerTemplate(name, template) {
  TEMPLATES[name] = template;
}

function loadTemplate(name) {
  // Lazy-load from templates directory
  if (!TEMPLATES[name]) {
    try {
      const template = require(`./templates/${name}`);
      TEMPLATES[name] = template;
    } catch {
      return null;
    }
  }
  return TEMPLATES[name];
}

function listTemplates() {
  // Load all templates
  const templateFiles = [
    'lower-third',
    'title-card',
    'text-overlay',
    'vignette',
    'watermark',
    'blur-region',
    'picture-in-picture',
    'film-grain',
    'color-correct',
  ];

  const templates = [];
  for (const name of templateFiles) {
    const t = loadTemplate(name);
    if (t) {
      templates.push({
        name,
        label: t.label,
        description: t.description,
        parameters: t.parameters || {},
      });
    }
  }
  return templates;
}

// ─── Exports ────────────────────────────────────────────────────────────

module.exports = {
  generateComp,
  generateFromTemplate,
  specToApiCalls,
  serializeValue,
  serializeNode,
  registerTemplate,
  loadTemplate,
  listTemplates,
};
