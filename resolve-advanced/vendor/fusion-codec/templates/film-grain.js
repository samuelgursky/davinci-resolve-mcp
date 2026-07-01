/**
 * Film Grain Template — Photochemical grain overlay
 *
 * Adds realistic film grain using Fusion's FilmGrain node
 * with calibrated settings for different film stocks.
 */

module.exports = {
  label: 'Film Grain',
  description: 'Realistic film grain overlay with stock presets (35mm, 16mm, Super 8).',
  parameters: {
    stock: { type: 'string', default: '35mm', description: 'Film stock preset: 35mm, 16mm, super8, subtle, heavy' },
    intensity: { type: 'number', default: 0.5, description: 'Overall grain intensity (0-1)' },
    size: { type: 'number', default: 1.0, description: 'Grain size multiplier' },
    softness: { type: 'number', default: 0.0, description: 'Grain softness (0-1)' },
    monochrome: { type: 'boolean', default: false, description: 'Monochrome grain (no color variation)' },
    width: { type: 'number', default: 1920, description: 'Frame width' },
    height: { type: 'number', default: 1080, description: 'Frame height' },
  },

  generate(params = {}) {
    const {
      stock = '35mm',
      intensity = 0.5,
      size = 1.0,
      softness = 0.0,
      monochrome = false,
      width = 1920,
      height = 1080,
    } = params;

    // Stock presets — calibrated grain characteristics
    const stockPresets = {
      '35mm': {
        power: 0.4 * intensity,
        colorAmount: monochrome ? 0 : 0.3,
        grainSize: 1.0 * size,
        softness: 0.1 + softness * 0.3,
      },
      '16mm': {
        power: 0.65 * intensity,
        colorAmount: monochrome ? 0 : 0.4,
        grainSize: 1.5 * size,
        softness: 0.05 + softness * 0.2,
      },
      'super8': {
        power: 0.85 * intensity,
        colorAmount: monochrome ? 0 : 0.5,
        grainSize: 2.2 * size,
        softness: 0.15 + softness * 0.3,
      },
      'subtle': {
        power: 0.15 * intensity,
        colorAmount: monochrome ? 0 : 0.15,
        grainSize: 0.8 * size,
        softness: 0.2 + softness * 0.3,
      },
      'heavy': {
        power: 1.0 * intensity,
        colorAmount: monochrome ? 0 : 0.6,
        grainSize: 1.8 * size,
        softness: 0.0 + softness * 0.2,
      },
    };

    const preset = stockPresets[stock] || stockPresets['35mm'];

    return {
      nodes: [
        {
          type: 'MediaIn',
          name: 'MediaIn1',
          inputs: {},
          viewX: 0, viewY: 0,
        },

        {
          type: 'FilmGrain',
          name: 'FilmGrain1',
          inputs: {
            Power: preset.power,
            ColorAmount: preset.colorAmount,
            GrainSize: preset.grainSize,
            Softness: preset.softness,
          },
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
            Input: 'FilmGrain1.Output',
          },
          viewX: 220, viewY: 0,
        },
      ],

      keyframes: [],
    };
  },
};
