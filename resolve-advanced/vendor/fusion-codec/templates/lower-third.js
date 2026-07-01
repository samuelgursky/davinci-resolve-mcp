/**
 * Lower Third Template — Name/title overlay
 *
 * Generates a lower third with primary text, subtitle,
 * background bar with mask, and Merge chain back to MediaIn/MediaOut.
 */

module.exports = {
  label: 'Lower Third',
  description: 'Animated lower third with name and title text over a semi-transparent bar.',
  parameters: {
    text: { type: 'string', default: 'Name', description: 'Primary text (name)' },
    subtitle: { type: 'string', default: 'Title', description: 'Secondary text (title/role)' },
    font: { type: 'string', default: 'Open Sans', description: 'Font family' },
    fontSize: { type: 'number', default: 0.065, description: 'Primary text size (0-1 relative)' },
    position: { type: 'string', default: 'bottom-left', description: 'Preset position: bottom-left, bottom-center, bottom-right' },
    textColor: { type: 'object', default: { r: 1, g: 1, b: 1 }, description: 'Text color RGB (0-1)' },
    barColor: { type: 'object', default: { r: 0.08, g: 0.08, b: 0.12 }, description: 'Bar background color RGB (0-1)' },
    barOpacity: { type: 'number', default: 0.75, description: 'Bar opacity (0-1)' },
    accentColor: { type: 'object', default: { r: 0.9, g: 0.65, b: 0.2 }, description: 'Accent line color RGB (0-1)' },
    width: { type: 'number', default: 1920, description: 'Frame width' },
    height: { type: 'number', default: 1080, description: 'Frame height' },
  },

  generate(params = {}) {
    const {
      text = 'Name',
      subtitle = 'Title',
      font = 'Open Sans',
      fontSize = 0.065,
      position = 'bottom-left',
      textColor = { r: 1, g: 1, b: 1 },
      barColor = { r: 0.08, g: 0.08, b: 0.12 },
      barOpacity = 0.75,
      accentColor = { r: 0.9, g: 0.65, b: 0.2 },
      width = 1920,
      height = 1080,
    } = params;

    // Position presets
    const positions = {
      'bottom-left': { barX: 0.22, barY: 0.12, textX: 0.06, nameY: 0.145, subtitleY: 0.095 },
      'bottom-center': { barX: 0.5, barY: 0.12, textX: 0.35, nameY: 0.145, subtitleY: 0.095 },
      'bottom-right': { barX: 0.78, barY: 0.12, textX: 0.63, nameY: 0.145, subtitleY: 0.095 },
    };
    const pos = positions[position] || positions['bottom-left'];

    return {
      nodes: [
        // MediaIn — auto-created by Resolve, but we reference it
        {
          type: 'MediaIn',
          name: 'MediaIn1',
          inputs: {},
          viewX: 0, viewY: 0,
        },

        // Background bar
        {
          type: 'Background',
          name: 'BG_Bar',
          inputs: {
            TopLeftRed: barColor.r,
            TopLeftGreen: barColor.g,
            TopLeftBlue: barColor.b,
            TopLeftAlpha: barOpacity,
            Width: width,
            Height: height,
            UseFrameFormatSettings: 0,
            Type: 'Solid',
          },
          viewX: 110, viewY: -33,
        },

        // Rectangle mask for the bar
        {
          type: 'RectangleMask',
          name: 'Mask_Bar',
          inputs: {
            Center: { x: pos.barX, y: pos.barY },
            Width: 0.4,
            Height: 0.07,
            CornerRadius: 0.003,
            SoftEdge: 0.002,
            MaskWidth: width,
            MaskHeight: height,
          },
          viewX: 220, viewY: -66,
        },

        // Accent line (thin colored bar on left edge)
        {
          type: 'Background',
          name: 'BG_Accent',
          inputs: {
            TopLeftRed: accentColor.r,
            TopLeftGreen: accentColor.g,
            TopLeftBlue: accentColor.b,
            TopLeftAlpha: 1,
            Width: width,
            Height: height,
            UseFrameFormatSettings: 0,
          },
          viewX: 110, viewY: -99,
        },

        // Thin accent line mask
        {
          type: 'RectangleMask',
          name: 'Mask_Accent',
          inputs: {
            Center: { x: pos.barX - 0.195, y: pos.barY },
            Width: 0.004,
            Height: 0.06,
            SoftEdge: 0.001,
            MaskWidth: width,
            MaskHeight: height,
          },
          viewX: 220, viewY: -132,
        },

        // Primary text (name)
        {
          type: 'TextPlus',
          name: 'Text_Name',
          inputs: {
            StyledText: text,
            Font: font,
            Style: 'Bold',
            Size: fontSize,
            Center: { x: pos.textX, y: pos.nameY },
            Red1: textColor.r,
            Green1: textColor.g,
            Blue1: textColor.b,
            HorizontalJustificationNew: 0, // left-aligned
            VerticalJustificationNew: 1,   // center
            Width: width,
            Height: height,
          },
          viewX: 110, viewY: 33,
        },

        // Subtitle text (title/role)
        {
          type: 'TextPlus',
          name: 'Text_Subtitle',
          inputs: {
            StyledText: subtitle,
            Font: font,
            Style: 'Regular',
            Size: fontSize * 0.6,
            Center: { x: pos.textX, y: pos.subtitleY },
            Red1: textColor.r * 0.7,
            Green1: textColor.g * 0.7,
            Blue1: textColor.b * 0.7,
            HorizontalJustificationNew: 0,
            VerticalJustificationNew: 1,
            Width: width,
            Height: height,
          },
          viewX: 110, viewY: 66,
        },

        // Merge bar over source
        {
          type: 'Merge',
          name: 'Merge_Bar',
          inputs: {},
          connections: {
            Background: 'MediaIn1.Output',
            Foreground: 'BG_Bar.Output',
          },
          effectMask: 'Mask_Bar.Mask',
          viewX: 330, viewY: 0,
        },

        // Merge accent over bar
        {
          type: 'Merge',
          name: 'Merge_Accent',
          inputs: {},
          connections: {
            Background: 'Merge_Bar.Output',
            Foreground: 'BG_Accent.Output',
          },
          effectMask: 'Mask_Accent.Mask',
          viewX: 440, viewY: 0,
        },

        // Merge name text
        {
          type: 'Merge',
          name: 'Merge_Name',
          inputs: {},
          connections: {
            Background: 'Merge_Accent.Output',
            Foreground: 'Text_Name.Output',
          },
          viewX: 550, viewY: 0,
        },

        // Merge subtitle text
        {
          type: 'Merge',
          name: 'Merge_Subtitle',
          inputs: {},
          connections: {
            Background: 'Merge_Name.Output',
            Foreground: 'Text_Subtitle.Output',
          },
          viewX: 660, viewY: 0,
        },

        // MediaOut
        {
          type: 'MediaOut',
          name: 'MediaOut1',
          inputs: {},
          connections: {
            Input: 'Merge_Subtitle.Output',
          },
          viewX: 770, viewY: 0,
        },
      ],

      keyframes: [
        // Bar width animates in (wipe from left)
        { tool: 'Mask_Bar', input: 'Width', time: 0, value: 0 },
        { tool: 'Mask_Bar', input: 'Width', time: 12, value: 0.4 },
        // Accent fades in slightly after bar
        { tool: 'Merge_Accent', input: 'Blend', time: 0, value: 0 },
        { tool: 'Merge_Accent', input: 'Blend', time: 8, value: 1 },
        // Text fades in after bar reveals
        { tool: 'Merge_Name', input: 'Blend', time: 6, value: 0 },
        { tool: 'Merge_Name', input: 'Blend', time: 14, value: 1 },
        { tool: 'Merge_Subtitle', input: 'Blend', time: 10, value: 0 },
        { tool: 'Merge_Subtitle', input: 'Blend', time: 18, value: 1 },
      ],
    };
  },
};
