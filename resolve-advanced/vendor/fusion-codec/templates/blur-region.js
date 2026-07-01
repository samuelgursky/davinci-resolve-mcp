/**
 * Blur Region Template — Selective area blur
 *
 * Rectangular or elliptical blur for obscuring faces, license plates,
 * or sensitive information. Configurable shape and blur amount.
 */

module.exports = {
  label: 'Blur Region',
  description: 'Selective region blur for obscuring faces, plates, or sensitive areas.',
  parameters: {
    centerX: { type: 'number', default: 0.5, description: 'Region center X (0-1)' },
    centerY: { type: 'number', default: 0.5, description: 'Region center Y (0-1)' },
    regionWidth: { type: 'number', default: 0.15, description: 'Region width (0-1)' },
    regionHeight: { type: 'number', default: 0.15, description: 'Region height (0-1)' },
    blurAmount: { type: 'number', default: 30, description: 'Blur strength (pixels)' },
    shape: { type: 'string', default: 'ellipse', description: 'Shape: rectangle or ellipse' },
    softEdge: { type: 'number', default: 0.02, description: 'Edge feathering' },
    width: { type: 'number', default: 1920, description: 'Frame width' },
    height: { type: 'number', default: 1080, description: 'Frame height' },
  },

  generate(params = {}) {
    const {
      centerX = 0.5,
      centerY = 0.5,
      regionWidth = 0.15,
      regionHeight = 0.15,
      blurAmount = 30,
      shape = 'ellipse',
      softEdge = 0.02,
      width = 1920,
      height = 1080,
    } = params;

    const maskType = shape === 'rectangle' ? 'RectangleMask' : 'EllipseMask';

    return {
      nodes: [
        {
          type: 'MediaIn',
          name: 'MediaIn1',
          inputs: {},
          viewX: 0, viewY: 0,
        },

        // Blur the entire image
        {
          type: 'Blur',
          name: 'Blur_Region',
          inputs: {
            XBlurSize: blurAmount,
            LockXY: 1, // lock X/Y blur together
          },
          connections: {
            Input: 'MediaIn1.Output',
          },
          viewX: 110, viewY: -33,
        },

        // Mask to restrict blur to region
        {
          type: maskType,
          name: 'Mask_Region',
          inputs: {
            Center: { x: centerX, y: centerY },
            Width: regionWidth,
            Height: regionHeight,
            SoftEdge: softEdge,
            MaskWidth: width,
            MaskHeight: height,
          },
          viewX: 220, viewY: -66,
        },

        // Merge blurred region over original
        {
          type: 'Merge',
          name: 'Merge_Blur',
          inputs: {},
          connections: {
            Background: 'MediaIn1.Output',
            Foreground: 'Blur_Region.Output',
          },
          effectMask: 'Mask_Region.Mask',
          viewX: 330, viewY: 0,
        },

        {
          type: 'MediaOut',
          name: 'MediaOut1',
          inputs: {},
          connections: {
            Input: 'Merge_Blur.Output',
          },
          viewX: 440, viewY: 0,
        },
      ],

      keyframes: [],
    };
  },
};
