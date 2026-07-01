/**
 * Picture-in-Picture Template — Scaled inset with border
 *
 * Creates a PiP overlay by transforming the foreground (MediaIn)
 * scaled and positioned as an inset. Requires two clips composited
 * via a Merge — designed to work with Fusion's multi-input system.
 *
 * Note: In practice, the "background" connection would need to be
 * wired to a second input (Loader or another MediaIn). This template
 * generates the node structure — the user connects the second source.
 */

module.exports = {
  label: 'Picture in Picture',
  description: 'Scaled inset overlay with optional border/shadow for PiP layouts.',
  parameters: {
    scale: { type: 'number', default: 0.3, description: 'PiP scale (0-1, e.g. 0.3 = 30%)' },
    position: { type: 'string', default: 'bottom-right', description: 'Preset: top-left, top-right, bottom-left, bottom-right' },
    borderWidth: { type: 'number', default: 3, description: 'Border width in pixels (0 for none)' },
    borderColor: { type: 'object', default: { r: 1, g: 1, b: 1 }, description: 'Border color RGB' },
    shadowEnabled: { type: 'boolean', default: true, description: 'Add drop shadow' },
    shadowOffset: { type: 'number', default: 5, description: 'Shadow offset pixels' },
    shadowOpacity: { type: 'number', default: 0.5, description: 'Shadow opacity (0-1)' },
    cornerRadius: { type: 'number', default: 0.008, description: 'Corner radius (0 for square)' },
    width: { type: 'number', default: 1920, description: 'Frame width' },
    height: { type: 'number', default: 1080, description: 'Frame height' },
  },

  generate(params = {}) {
    const {
      scale = 0.3,
      position = 'bottom-right',
      borderWidth = 3,
      borderColor = { r: 1, g: 1, b: 1 },
      shadowEnabled = true,
      shadowOffset = 5,
      shadowOpacity = 0.5,
      cornerRadius = 0.008,
      width = 1920,
      height = 1080,
    } = params;

    const margin = 0.03;
    const halfScale = scale / 2;
    const posMap = {
      'top-left':     { x: margin + halfScale, y: 1 - margin - halfScale },
      'top-right':    { x: 1 - margin - halfScale, y: 1 - margin - halfScale },
      'bottom-left':  { x: margin + halfScale, y: margin + halfScale },
      'bottom-right': { x: 1 - margin - halfScale, y: margin + halfScale },
    };
    const pos = posMap[position] || posMap['bottom-right'];

    const nodes = [
      {
        type: 'MediaIn',
        name: 'MediaIn1',
        inputs: {},
        viewX: 0, viewY: 0,
      },

      // Transform to scale and position the PiP
      {
        type: 'Transform',
        name: 'Transform_PiP',
        inputs: {
          Center: { x: pos.x, y: pos.y },
          Size: scale,
        },
        connections: {
          Input: 'MediaIn1.Output',
        },
        viewX: 110, viewY: 0,
      },

      // Background (this is where the "main" video would connect)
      // Using a black BG as placeholder — user replaces with their source
      {
        type: 'Background',
        name: 'BG_Main',
        inputs: {
          TopLeftRed: 0,
          TopLeftGreen: 0,
          TopLeftBlue: 0,
          TopLeftAlpha: 1,
          Width: width,
          Height: height,
          UseFrameFormatSettings: 0,
        },
        viewX: 0, viewY: -66,
      },
    ];

    let lastMerge;

    // Border (optional)
    if (borderWidth > 0) {
      const borderScale = scale + (borderWidth * 2 / width);
      nodes.push({
        type: 'Background',
        name: 'BG_Border',
        inputs: {
          TopLeftRed: borderColor.r,
          TopLeftGreen: borderColor.g,
          TopLeftBlue: borderColor.b,
          TopLeftAlpha: 1,
          Width: width,
          Height: height,
          UseFrameFormatSettings: 0,
        },
        viewX: 110, viewY: -33,
      });

      nodes.push({
        type: 'RectangleMask',
        name: 'Mask_Border',
        inputs: {
          Center: { x: pos.x, y: pos.y },
          Width: borderScale * (width / height), // adjust for aspect
          Height: borderScale,
          CornerRadius: cornerRadius,
          SoftEdge: 0.001,
          MaskWidth: width,
          MaskHeight: height,
        },
        viewX: 220, viewY: -66,
      });

      nodes.push({
        type: 'Merge',
        name: 'Merge_Border',
        inputs: {},
        connections: {
          Background: 'BG_Main.Output',
          Foreground: 'BG_Border.Output',
        },
        effectMask: 'Mask_Border.Mask',
        viewX: 330, viewY: -33,
      });

      lastMerge = 'Merge_Border';
    } else {
      lastMerge = 'BG_Main';
    }

    // Merge PiP over background
    nodes.push({
      type: 'Merge',
      name: 'Merge_PiP',
      inputs: {},
      connections: {
        Background: `${lastMerge}.Output`,
        Foreground: 'Transform_PiP.Output',
      },
      viewX: 440, viewY: 0,
    });

    // Shadow (optional)
    if (shadowEnabled) {
      nodes.push({
        type: 'Shadow',
        name: 'Shadow_PiP',
        inputs: {
          ShadowOffset: shadowOffset / width,
          Softness: 0.01,
          ShadowAlpha: shadowOpacity,
        },
        connections: {
          Input: 'Merge_PiP.Output',
        },
        viewX: 550, viewY: 0,
      });
    }

    const finalNode = shadowEnabled ? 'Shadow_PiP' : 'Merge_PiP';

    nodes.push({
      type: 'MediaOut',
      name: 'MediaOut1',
      inputs: {},
      connections: {
        Input: `${finalNode}.Output`,
      },
      viewX: 660, viewY: 0,
    });

    return { nodes, keyframes: [] };
  },
};
