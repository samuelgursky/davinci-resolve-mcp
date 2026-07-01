/**
 * Vignette Template — Edge darkening effect
 *
 * Elliptical mask with soft edges over a black background,
 * merged in multiply/darken mode over source footage.
 */

module.exports = {
  label: 'Vignette',
  description: 'Soft edge vignette — darkens frame edges with customizable shape and intensity.',
  parameters: {
    intensity: { type: 'number', default: 0.5, description: 'Vignette intensity (0-1)' },
    softness: { type: 'number', default: 0.35, description: 'Edge softness (0-1)' },
    size: { type: 'number', default: 0.75, description: 'Inner clear area size (0-1)' },
    aspect: { type: 'number', default: 1.3, description: 'Horizontal/vertical aspect ratio' },
    centerX: { type: 'number', default: 0.5, description: 'Center X (0-1)' },
    centerY: { type: 'number', default: 0.5, description: 'Center Y (0-1)' },
    color: { type: 'object', default: { r: 0, g: 0, b: 0 }, description: 'Vignette color (default black)' },
    width: { type: 'number', default: 1920, description: 'Frame width' },
    height: { type: 'number', default: 1080, description: 'Frame height' },
  },

  generate(params = {}) {
    const {
      intensity = 0.5,
      softness = 0.35,
      size = 0.75,
      aspect = 1.3,
      centerX = 0.5,
      centerY = 0.5,
      color = { r: 0, g: 0, b: 0 },
      width = 1920,
      height = 1080,
    } = params;

    return {
      nodes: [
        {
          type: 'MediaIn',
          name: 'MediaIn1',
          inputs: {},
          viewX: 0, viewY: 0,
        },

        // Black (or colored) background for vignette
        {
          type: 'Background',
          name: 'BG_Vignette',
          inputs: {
            TopLeftRed: color.r,
            TopLeftGreen: color.g,
            TopLeftBlue: color.b,
            TopLeftAlpha: 1,
            Width: width,
            Height: height,
            UseFrameFormatSettings: 0,
          },
          viewX: 110, viewY: -33,
        },

        // Elliptical mask — inverted so edges are visible, center is clear
        {
          type: 'EllipseMask',
          name: 'Mask_Vignette',
          inputs: {
            Center: { x: centerX, y: centerY },
            Width: size * aspect,
            Height: size,
            SoftEdge: softness,
            Invert: 1, // invert so edges are opaque
            MaskWidth: width,
            MaskHeight: height,
          },
          viewX: 220, viewY: -66,
        },

        // Merge vignette over source
        {
          type: 'Merge',
          name: 'Merge_Vignette',
          inputs: {
            Blend: intensity,
            ApplyMode: 'Multiply',
          },
          connections: {
            Background: 'MediaIn1.Output',
            Foreground: 'BG_Vignette.Output',
          },
          effectMask: 'Mask_Vignette.Mask',
          viewX: 330, viewY: 0,
        },

        {
          type: 'MediaOut',
          name: 'MediaOut1',
          inputs: {},
          connections: {
            Input: 'Merge_Vignette.Output',
          },
          viewX: 440, viewY: 0,
        },
      ],

      keyframes: [],
    };
  },
};
