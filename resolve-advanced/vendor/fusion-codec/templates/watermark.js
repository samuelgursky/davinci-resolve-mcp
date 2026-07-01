/**
 * Watermark Template — Logo/text overlay for review copies
 *
 * Semi-transparent text watermark with configurable position,
 * rotation, and tiling options.
 */

module.exports = {
  label: 'Watermark',
  description: 'Semi-transparent text watermark for review copies. Supports diagonal and tiled modes.',
  parameters: {
    text: { type: 'string', default: 'CONFIDENTIAL', description: 'Watermark text' },
    font: { type: 'string', default: 'Arial', description: 'Font family' },
    fontSize: { type: 'number', default: 0.08, description: 'Font size (0-1)' },
    opacity: { type: 'number', default: 0.15, description: 'Watermark opacity (0-1)' },
    color: { type: 'object', default: { r: 1, g: 1, b: 1 }, description: 'Text color RGB' },
    angle: { type: 'number', default: -30, description: 'Rotation angle (degrees)' },
    position: { type: 'string', default: 'center', description: 'Position: center, bottom-right, top-left' },
    width: { type: 'number', default: 1920, description: 'Frame width' },
    height: { type: 'number', default: 1080, description: 'Frame height' },
  },

  generate(params = {}) {
    const {
      text = 'CONFIDENTIAL',
      font = 'Arial',
      fontSize = 0.08,
      opacity = 0.15,
      color = { r: 1, g: 1, b: 1 },
      angle = -30,
      position = 'center',
      width = 1920,
      height = 1080,
    } = params;

    const posMap = {
      'center': { x: 0.5, y: 0.5 },
      'bottom-right': { x: 0.8, y: 0.1 },
      'top-left': { x: 0.2, y: 0.9 },
    };
    const pos = posMap[position] || posMap['center'];

    return {
      nodes: [
        {
          type: 'MediaIn',
          name: 'MediaIn1',
          inputs: {},
          viewX: 0, viewY: 0,
        },

        {
          type: 'TextPlus',
          name: 'Text_Watermark',
          inputs: {
            StyledText: text,
            Font: font,
            Style: 'Bold',
            Size: fontSize,
            Center: { x: pos.x, y: pos.y },
            Red1: color.r,
            Green1: color.g,
            Blue1: color.b,
            HorizontalJustificationNew: 1,
            VerticalJustificationNew: 1,
            LayoutRotation: angle,
            Tracking: 0.2,
            Width: width,
            Height: height,
          },
          viewX: 110, viewY: 33,
        },

        {
          type: 'Merge',
          name: 'Merge_Watermark',
          inputs: {
            Blend: opacity,
          },
          connections: {
            Background: 'MediaIn1.Output',
            Foreground: 'Text_Watermark.Output',
          },
          viewX: 220, viewY: 0,
        },

        {
          type: 'MediaOut',
          name: 'MediaOut1',
          inputs: {},
          connections: {
            Input: 'Merge_Watermark.Output',
          },
          viewX: 330, viewY: 0,
        },
      ],

      keyframes: [],
    };
  },
};
