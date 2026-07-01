/**
 * Title Card Template — Full-frame title with background
 *
 * Clean title card with main title, optional subtitle,
 * over a solid or gradient background. Fades in/out.
 */

module.exports = {
  label: 'Title Card',
  description: 'Full-frame title card with main title, optional subtitle, and fade transitions.',
  parameters: {
    title: { type: 'string', default: 'Title', description: 'Main title text' },
    subtitle: { type: 'string', default: '', description: 'Optional subtitle text' },
    font: { type: 'string', default: 'Futura', description: 'Font family' },
    titleSize: { type: 'number', default: 0.1, description: 'Title font size (0-1)' },
    textColor: { type: 'object', default: { r: 1, g: 1, b: 1 }, description: 'Text color RGB' },
    bgColor: { type: 'object', default: { r: 0.02, g: 0.02, b: 0.04 }, description: 'Background color RGB' },
    fadeIn: { type: 'number', default: 24, description: 'Fade in duration (frames)' },
    fadeOut: { type: 'number', default: 24, description: 'Fade out duration (frames)' },
    holdDuration: { type: 'number', default: 72, description: 'Hold duration (frames)' },
    width: { type: 'number', default: 1920, description: 'Frame width' },
    height: { type: 'number', default: 1080, description: 'Frame height' },
  },

  generate(params = {}) {
    const {
      title = 'Title',
      subtitle = '',
      font = 'Futura',
      titleSize = 0.1,
      textColor = { r: 1, g: 1, b: 1 },
      bgColor = { r: 0.02, g: 0.02, b: 0.04 },
      fadeIn = 24,
      fadeOut = 24,
      holdDuration = 72,
      width = 1920,
      height = 1080,
    } = params;

    const totalDuration = fadeIn + holdDuration + fadeOut;
    const hasSubtitle = subtitle && subtitle.length > 0;

    // Vertical positioning: center title, subtitle below
    const titleY = hasSubtitle ? 0.54 : 0.5;
    const subtitleY = 0.42;

    const nodes = [
      // Background
      {
        type: 'Background',
        name: 'BG_Title',
        inputs: {
          TopLeftRed: bgColor.r,
          TopLeftGreen: bgColor.g,
          TopLeftBlue: bgColor.b,
          TopLeftAlpha: 1,
          Width: width,
          Height: height,
          UseFrameFormatSettings: 0,
        },
        viewX: 0, viewY: 0,
      },

      // Main title
      {
        type: 'TextPlus',
        name: 'Text_Title',
        inputs: {
          StyledText: title,
          Font: font,
          Style: 'Bold',
          Size: titleSize,
          Center: { x: 0.5, y: titleY },
          Red1: textColor.r,
          Green1: textColor.g,
          Blue1: textColor.b,
          HorizontalJustificationNew: 1, // center
          VerticalJustificationNew: 1,
          Width: width,
          Height: height,
          Tracking: 0.05, // slightly wide tracking for titles
        },
        viewX: 0, viewY: 33,
      },

      // Merge title over background
      {
        type: 'Merge',
        name: 'Merge_Title',
        inputs: {},
        connections: {
          Background: 'BG_Title.Output',
          Foreground: 'Text_Title.Output',
        },
        viewX: 220, viewY: 0,
      },
    ];

    let lastMerge = 'Merge_Title';

    // Subtitle (optional)
    if (hasSubtitle) {
      nodes.push({
        type: 'TextPlus',
        name: 'Text_Subtitle',
        inputs: {
          StyledText: subtitle,
          Font: font,
          Style: 'Regular',
          Size: titleSize * 0.45,
          Center: { x: 0.5, y: subtitleY },
          Red1: textColor.r * 0.7,
          Green1: textColor.g * 0.7,
          Blue1: textColor.b * 0.7,
          HorizontalJustificationNew: 1,
          VerticalJustificationNew: 1,
          Tracking: 0.12,
          Width: width,
          Height: height,
        },
        viewX: 110, viewY: 66,
      });

      nodes.push({
        type: 'Merge',
        name: 'Merge_Subtitle',
        inputs: {},
        connections: {
          Background: 'Merge_Title.Output',
          Foreground: 'Text_Subtitle.Output',
        },
        viewX: 330, viewY: 0,
      });

      lastMerge = 'Merge_Subtitle';
    }

    // Final merge with MediaIn (so title card composites over video if present)
    nodes.splice(0, 0, {
      type: 'MediaIn',
      name: 'MediaIn1',
      inputs: {},
      viewX: -110, viewY: 0,
    });

    // Dissolve/blend the title card over the source
    nodes.push({
      type: 'Dissolve',
      name: 'Dissolve_Fade',
      inputs: {
        Mix: 1,
      },
      connections: {
        Background: 'MediaIn1.Output',
        Foreground: `${lastMerge}.Output`,
      },
      viewX: 440, viewY: 0,
    });

    // MediaOut
    nodes.push({
      type: 'MediaOut',
      name: 'MediaOut1',
      inputs: {},
      connections: {
        Input: 'Dissolve_Fade.Output',
      },
      viewX: 550, viewY: 0,
    });

    return {
      nodes,
      keyframes: [
        // Fade in
        { tool: 'Dissolve_Fade', input: 'Mix', time: 0, value: 0 },
        { tool: 'Dissolve_Fade', input: 'Mix', time: fadeIn, value: 1 },
        // Hold
        { tool: 'Dissolve_Fade', input: 'Mix', time: fadeIn + holdDuration, value: 1 },
        // Fade out
        { tool: 'Dissolve_Fade', input: 'Mix', time: totalDuration, value: 0 },
      ],
    };
  },
};
