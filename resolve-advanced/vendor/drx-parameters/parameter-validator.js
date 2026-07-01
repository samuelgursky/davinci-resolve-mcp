/**
 * DRX Parameter Validation
 *
 * Validates parameter values against DaVinci Resolve limits
 * and professional colorist recommendations.
 *
 * @module drx-parameters/parameter-validator
 */

const { PARAMETER_RANGES, getRange, clamp, isDefault } = require('./parameter-ranges');
const { CORRECTOR_TYPES } = require('./corrector-types');

/**
 * Validation severity levels
 */
const SEVERITY = {
  ERROR: 'error',     // Invalid value that won't work
  WARNING: 'warning', // Value outside recommended range
  INFO: 'info',       // Informational note
};

/**
 * Professional recommended limits (more conservative than absolute limits)
 * Based on colorist best practices for maintaining image quality
 */
const PROFESSIONAL_LIMITS = {
  // Gain should rarely exceed 2x to avoid clipping
  gain: { r: { max: 2.0 }, g: { max: 2.0 }, b: { max: 2.0 }, master: { max: 2.0 } },

  // Lift extremes crush blacks or lift fog
  lift: { r: { min: -0.5, max: 0.5 }, g: { min: -0.5, max: 0.5 }, b: { min: -0.5, max: 0.5 }, master: { min: -0.3, max: 0.3 } },

  // Gamma extremes look unnatural
  gamma: { r: { min: -0.3, max: 0.3 }, g: { min: -0.3, max: 0.3 }, b: { min: -0.3, max: 0.3 }, master: { min: -0.3, max: 0.3 } },

  // Saturation over 2x is rarely professional
  saturation: { master: { max: 2.0 } },

  // Extreme contrast loses detail
  contrast: { master: { min: 0.7, max: 1.5 } },

  // Large temperature shifts look unnatural
  temperature: { master: { min: -2000, max: 2000 } },

  // Tint extremes are green/magenta push
  tint: { master: { min: -50, max: 50 } },
};

/**
 * Broadcast safe limits (legal video levels)
 * For Rec.709 SDR delivery
 */
const BROADCAST_LIMITS = {
  // Gain must not exceed 1.0 for legal highlights (100%)
  gain: { r: { max: 1.0 }, g: { max: 1.0 }, b: { max: 1.0 }, master: { max: 1.0 } },

  // Lift below 0 is illegal (below 0 IRE)
  lift: { r: { min: 0.0 }, g: { min: 0.0 }, b: { min: 0.0 }, master: { min: 0.0 } },

  // Saturation should be moderate for broadcast
  saturation: { master: { max: 1.2 } },
};

/**
 * Validation result object
 */
class ValidationResult {
  constructor() {
    this.valid = true;
    this.issues = [];
  }

  addIssue(severity, control, channel, message, value, limit) {
    this.issues.push({ severity, control, channel, message, value, limit });
    if (severity === SEVERITY.ERROR) {
      this.valid = false;
    }
  }

  hasErrors() {
    return this.issues.some(i => i.severity === SEVERITY.ERROR);
  }

  hasWarnings() {
    return this.issues.some(i => i.severity === SEVERITY.WARNING);
  }

  getErrors() {
    return this.issues.filter(i => i.severity === SEVERITY.ERROR);
  }

  getWarnings() {
    return this.issues.filter(i => i.severity === SEVERITY.WARNING);
  }

  toJSON() {
    return {
      valid: this.valid,
      errorCount: this.getErrors().length,
      warningCount: this.getWarnings().length,
      issues: this.issues,
    };
  }
}

/**
 * Validate a single parameter value against absolute limits
 * @param {string} control - Control name
 * @param {string} channel - Channel name
 * @param {number} value - Value to validate
 * @returns {ValidationResult}
 */
function validateParameter(control, channel, value) {
  const result = new ValidationResult();
  const range = getRange(control, channel);

  if (!range) {
    result.addIssue(
      SEVERITY.WARNING,
      control,
      channel,
      `Unknown parameter ${control}.${channel}`,
      value,
      null
    );
    return result;
  }

  // Check absolute limits
  if (value < range.min) {
    result.addIssue(
      SEVERITY.ERROR,
      control,
      channel,
      `Value ${value} below minimum ${range.min}`,
      value,
      range.min
    );
  } else if (value > range.max) {
    result.addIssue(
      SEVERITY.ERROR,
      control,
      channel,
      `Value ${value} above maximum ${range.max}`,
      value,
      range.max
    );
  }

  return result;
}

/**
 * Validate parameters against professional recommendations
 * @param {object} params - Semantic parameters object
 * @returns {ValidationResult}
 */
function validateProfessional(params) {
  const result = new ValidationResult();

  for (const [control, channels] of Object.entries(params)) {
    const limits = PROFESSIONAL_LIMITS[control];
    if (!limits) continue;

    for (const [channel, value] of Object.entries(channels)) {
      const channelLimits = limits[channel];
      if (!channelLimits) continue;

      if (channelLimits.min !== undefined && value < channelLimits.min) {
        result.addIssue(
          SEVERITY.WARNING,
          control,
          channel,
          `Value ${value.toFixed(3)} below recommended minimum ${channelLimits.min}`,
          value,
          channelLimits.min
        );
      }

      if (channelLimits.max !== undefined && value > channelLimits.max) {
        result.addIssue(
          SEVERITY.WARNING,
          control,
          channel,
          `Value ${value.toFixed(3)} above recommended maximum ${channelLimits.max}`,
          value,
          channelLimits.max
        );
      }
    }
  }

  return result;
}

/**
 * Validate parameters for broadcast delivery
 * @param {object} params - Semantic parameters object
 * @returns {ValidationResult}
 */
function validateBroadcast(params) {
  const result = new ValidationResult();

  for (const [control, channels] of Object.entries(params)) {
    const limits = BROADCAST_LIMITS[control];
    if (!limits) continue;

    for (const [channel, value] of Object.entries(channels)) {
      const channelLimits = limits[channel];
      if (!channelLimits) continue;

      if (channelLimits.min !== undefined && value < channelLimits.min) {
        result.addIssue(
          SEVERITY.ERROR,
          control,
          channel,
          `Value ${value.toFixed(3)} below broadcast legal minimum ${channelLimits.min}`,
          value,
          channelLimits.min
        );
      }

      if (channelLimits.max !== undefined && value > channelLimits.max) {
        result.addIssue(
          SEVERITY.ERROR,
          control,
          channel,
          `Value ${value.toFixed(3)} above broadcast legal maximum ${channelLimits.max}`,
          value,
          channelLimits.max
        );
      }
    }
  }

  return result;
}

/**
 * Validate all parameters against absolute limits
 * @param {object} params - Semantic parameters object
 * @returns {ValidationResult}
 */
function validateAll(params) {
  const result = new ValidationResult();

  for (const [control, channels] of Object.entries(params)) {
    for (const [channel, value] of Object.entries(channels)) {
      const paramResult = validateParameter(control, channel, value);
      result.issues.push(...paramResult.issues);
      if (paramResult.hasErrors()) {
        result.valid = false;
      }
    }
  }

  return result;
}

/**
 * Auto-correct parameters to valid range
 * @param {object} params - Semantic parameters object
 * @returns {object} Corrected parameters
 */
function autoCorrect(params) {
  const corrected = {};

  for (const [control, channels] of Object.entries(params)) {
    corrected[control] = {};

    for (const [channel, value] of Object.entries(channels)) {
      corrected[control][channel] = clamp(control, channel, value);
    }
  }

  return corrected;
}

/**
 * Check if grade has any non-default values
 * @param {object} params - Semantic parameters object
 * @param {number} tolerance - Tolerance for floating point comparison
 * @returns {boolean}
 */
function hasActualGrade(params, tolerance = 0.001) {
  for (const [control, channels] of Object.entries(params)) {
    for (const [channel, value] of Object.entries(channels)) {
      if (!isDefault(control, channel, value, tolerance)) {
        return true;
      }
    }
  }
  return false;
}

/**
 * Get a summary of what adjustments are present
 * @param {object} params - Semantic parameters object
 * @param {number} tolerance - Tolerance for floating point comparison
 * @returns {object} Summary of adjustments
 */
function getAdjustmentSummary(params, tolerance = 0.001) {
  const summary = {
    hasLift: false,
    hasGamma: false,
    hasGain: false,
    hasOffset: false,
    hasSaturation: false,
    hasContrast: false,
    hasTemperature: false,
    hasTint: false,
    adjustmentCount: 0,
    nonNeutralParams: [],
  };

  const controlFlags = {
    lift: 'hasLift',
    gamma: 'hasGamma',
    gain: 'hasGain',
    offset: 'hasOffset',
    saturation: 'hasSaturation',
    contrast: 'hasContrast',
    temperature: 'hasTemperature',
    tint: 'hasTint',
  };

  for (const [control, channels] of Object.entries(params)) {
    for (const [channel, value] of Object.entries(channels)) {
      if (!isDefault(control, channel, value, tolerance)) {
        summary.adjustmentCount++;
        summary.nonNeutralParams.push({ control, channel, value });

        if (controlFlags[control]) {
          summary[controlFlags[control]] = true;
        }
      }
    }
  }

  return summary;
}

/**
 * Calculate the visual impact score of a grade
 * Higher score = more aggressive adjustments
 * @param {object} params - Semantic parameters object
 * @returns {number} Impact score (0-100)
 */
function calculateImpactScore(params) {
  const { getVisualImpactWeight, getRange } = require('./parameter-ranges');
  let totalScore = 0;
  let maxScore = 0;

  for (const [control, channels] of Object.entries(params)) {
    const weight = getVisualImpactWeight(control);

    for (const [channel, value] of Object.entries(channels)) {
      const range = getRange(control, channel);
      if (!range) continue;

      // Calculate normalized deviation from default
      const defaultVal = range.default;
      const maxDeviation = Math.max(
        Math.abs(range.max - defaultVal),
        Math.abs(defaultVal - range.min)
      );
      const deviation = Math.abs(value - defaultVal);
      const normalizedDeviation = deviation / maxDeviation;

      totalScore += normalizedDeviation * weight;
      maxScore += weight;
    }
  }

  if (maxScore === 0) return 0;
  return Math.round((totalScore / maxScore) * 100);
}

module.exports = {
  SEVERITY,
  PROFESSIONAL_LIMITS,
  BROADCAST_LIMITS,
  ValidationResult,
  validateParameter,
  validateProfessional,
  validateBroadcast,
  validateAll,
  autoCorrect,
  hasActualGrade,
  getAdjustmentSummary,
  calculateImpactScore,
};
