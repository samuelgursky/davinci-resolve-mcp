/**
 * Color Correct Template — Fusion Color Corrector node
 *
 * Full-featured primary color correction via Fusion's ColorCorrector.
 * Useful for per-clip corrections within Fusion compositions
 * (separate from the Color page grade).
 */

module.exports = {
  label: 'Color Correct',
  description: 'Primary color correction via Fusion ColorCorrector — gain, gamma, brightness, contrast, saturation.',
  parameters: {
    gain: { type: 'object', default: { r: 1, g: 1, b: 1 }, description: 'Master gain RGB' },
    gamma: { type: 'object', default: { r: 1, g: 1, b: 1 }, description: 'Master gamma RGB' },
    brightness: { type: 'number', default: 0, description: 'Brightness offset' },
    contrast: { type: 'number', default: 1, description: 'Contrast (1 = unity)' },
    saturation: { type: 'number', default: 1, description: 'Saturation (1 = unity)' },
    tintAngle: { type: 'number', default: 0, description: 'Tint rotation angle' },
    tintStrength: { type: 'number', default: 0, description: 'Tint strength' },
    width: { type: 'number', default: 1920, description: 'Frame width' },
    height: { type: 'number', default: 1080, description: 'Frame height' },
  },

  generate(params = {}) {
    const {
      gain = { r: 1, g: 1, b: 1 },
      gamma = { r: 1, g: 1, b: 1 },
      brightness = 0,
      contrast = 1,
      saturation = 1,
      tintAngle = 0,
      tintStrength = 0,
    } = params;

    const inputs = {};

    // Only set non-default values to keep composition clean
    if (gain.r !== 1 || gain.g !== 1 || gain.b !== 1) {
      inputs.MasterRedGain = gain.r;
      inputs.MasterGreenGain = gain.g;
      inputs.MasterBlueGain = gain.b;
    }
    if (gamma.r !== 1 || gamma.g !== 1 || gamma.b !== 1) {
      inputs.MasterRedGamma = gamma.r;
      inputs.MasterGreenGamma = gamma.g;
      inputs.MasterBlueGamma = gamma.b;
    }
    if (brightness !== 0) inputs.MasterBrightness = brightness;
    if (contrast !== 1) inputs.MasterContrast = contrast;
    if (saturation !== 1) inputs.MasterSaturation = saturation;
    if (tintAngle !== 0) inputs.TintAngle = tintAngle;
    if (tintStrength !== 0) inputs.TintLength = tintStrength;

    return {
      nodes: [
        {
          type: 'MediaIn',
          name: 'MediaIn1',
          inputs: {},
          viewX: 0, viewY: 0,
        },

        {
          type: 'ColorCorrector',
          name: 'CC_Primary',
          inputs,
          connections: {
            Input: 'MediaIn1.Output',
          },
          viewX: 110, viewY: 0,
        },

        {
          type: 'MediaOut',
          name: 'MediaOut1',
          inputs: {},
          connections: {
            Input: 'CC_Primary.Output',
          },
          viewX: 220, viewY: 0,
        },
      ],

      keyframes: [],
    };
  },
};
