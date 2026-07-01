/**
 * Text Overlay Template — Simple text burn-in
 *
 * Timecode, date, watermark text, or any simple text overlay.
 * Single TextPlus merged over source.
 */

module.exports = {
  label: 'Text Overlay',
  description: 'Simple text burn-in for timecode, dates, labels, or any overlay text.',
  parameters: {
    text: { type: 'string', default: 'OVERLAY TEXT', description: 'Text to display' },
    font: { type: 'string', default: 'Courier New', description: 'Font family' },
    fontSize: { type: 'number', default: 0.04, description: 'Font size (0-1)' },
    position: { type: 'string', default: 'top-left', description: 'Preset: top-left, top-center, top-right, bottom-left, bottom-center, bottom-right, center' },
    textColor: { type: 'object', default: { r: 1, g: 1, b: 1 }, description: 'Text color RGB' },
    opacity: { type: 'number', default: 0.6, description: 'Text opacity (0-1)' },
    bgEnabled: { type: 'boolean', default: false, description: 'Add background box behind text' },
    bgColor: { type: 'object', default: { r: 0, g: 0, b: 0 }, description: 'Background box color' },
    bgOpacity: { type: 'number', default: 0.5, description: 'Background box opacity' },
    width: { type: 'number', default: 1920, description: 'Frame width' },
    height: { type: 'number', default: 1080, description: 'Frame height' },
  },

  generate(params = {}) {
    const {
      text = 'OVERLAY TEXT',
      font = 'Courier New',
      fontSize = 0.04,
      position = 'top-left',
      textColor = { r: 1, g: 1, b: 1 },
      opacity = 0.6,
      bgEnabled = false,
      bgColor = { r: 0, g: 0, b: 0 },
      bgOpacity = 0.5,
      width = 1920,
      height = 1080,
    } = params;

    const positionMap = {
      'top-left':      { x: 0.08, y: 0.92, hJust: 0 },
      'top-center':    { x: 0.5,  y: 0.92, hJust: 1 },
      'top-right':     { x: 0.92, y: 0.92, hJust: 2 },
      'bottom-left':   { x: 0.08, y: 0.08, hJust: 0 },
      'bottom-center': { x: 0.5,  y: 0.08, hJust: 1 },
      'bottom-right':  { x: 0.92, y: 0.08, hJust: 2 },
      'center':        { x: 0.5,  y: 0.5,  hJust: 1 },
    };
    const pos = positionMap[position] || positionMap['top-left'];

    const nodes = [
      {
        type: 'MediaIn',
        name: 'MediaIn1',
        inputs: {},
        viewX: 0, viewY: 0,
      },
      {
        type: 'TextPlus',
        name: 'Text_Overlay',
        inputs: {
          StyledText: text,
          Font: font,
          Style: 'Bold',
          Size: fontSize,
          Center: { x: pos.x, y: pos.y },
          Red1: textColor.r,
          Green1: textColor.g,
          Blue1: textColor.b,
          HorizontalJustificationNew: pos.hJust,
          VerticalJustificationNew: 1,
          Width: width,
          Height: height,
        },
        viewX: 110, viewY: 33,
      },
      {
        type: 'Merge',
        name: 'Merge_Text',
        inputs: {
          Blend: opacity,
        },
        connections: {
          Background: 'MediaIn1.Output',
          Foreground: 'Text_Overlay.Output',
        },
        viewX: 220, viewY: 0,
      },
    ];

    let lastMerge = 'Merge_Text';

    // Optional background box
    if (bgEnabled) {
      // Insert background elements before the text merge
      nodes.splice(1, 0,
        {
          type: 'Background',
          name: 'BG_TextBox',
          inputs: {
            TopLeftRed: bgColor.r,
            TopLeftGreen: bgColor.g,
            TopLeftBlue: bgColor.b,
            TopLeftAlpha: bgOpacity,
            Width: width,
            Height: height,
            UseFrameFormatSettings: 0,
          },
          viewX: 110, viewY: -33,
        },
        {
          type: 'RectangleMask',
          name: 'Mask_TextBox',
          inputs: {
            Center: { x: pos.x, y: pos.y },
            Width: 0.25,
            Height: 0.05,
            CornerRadius: 0.003,
            SoftEdge: 0.002,
            MaskWidth: width,
            MaskHeight: height,
          },
          viewX: 220, viewY: -66,
        }
      );

      // Insert box merge before text merge
      const textMergeIdx = nodes.findIndex(n => n.name === 'Merge_Text');
      nodes.splice(textMergeIdx, 0, {
        type: 'Merge',
        name: 'Merge_Box',
        inputs: {},
        connections: {
          Background: 'MediaIn1.Output',
          Foreground: 'BG_TextBox.Output',
        },
        effectMask: 'Mask_TextBox.Mask',
        viewX: 330, viewY: 0,
      });

      // Update text merge to use box output as background
      const textMerge = nodes.find(n => n.name === 'Merge_Text');
      textMerge.connections.Background = 'Merge_Box.Output';
      textMerge.viewX = 440;
    }

    // MediaOut
    nodes.push({
      type: 'MediaOut',
      name: 'MediaOut1',
      inputs: {},
      connections: {
        Input: `${lastMerge}.Output`,
      },
      viewX: nodes[nodes.length - 1].viewX + 110,
      viewY: 0,
    });

    return { nodes, keyframes: [] };
  },
};
