/**
 * Tool Registry Descriptor — drx-parameters
 *
 * Single entry describing the parameter library as a whole,
 * rather than 400+ individual parameters.
 */

let paramCount = 0;
let version = '1.0.0';

try {
  const params = require('./index');
  paramCount = params.TOTAL_KNOWN_PARAMS || params.getKnownParamCount?.() || 0;
  version = params.VERSION || '1.0.0';
} catch {
  // Safe fallback
}

module.exports = {
  source: 'drx-parameters',
  version: '0.1.0',
  capabilities: [
    {
      id: 'drxParameters.library',
      name: 'DRX Parameter Library',
      description: `Complete DaVinci Resolve parameter definitions library with ${paramCount || '400+'} parameters. Includes parameter IDs, ranges, validation, codec (protobuf encoding/decoding), and corrector types (Lift, Gain, Gamma, Offset, Contrast, Log Wheels, HDR Zones, Curves, etc.)`,
      type: 'api-method',
      category: 'params.library',
      source: 'drx-parameters',
      tags: ['parameters', 'resolve', 'drx', 'codec', 'validation', 'color'],
      availability: 'static',
      parameterNames: [
        'CORRECTOR_TYPES', 'PARAMETER_IDS', 'PARAMETER_RANGES',
        'encodeParameter', 'validateParameter', 'autoCorrect',
      ],
    },
  ],
};
