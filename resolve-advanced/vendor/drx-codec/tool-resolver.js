/**
 * Tool Resolver - Unified Tool Selection Layer
 *
 * Central hub that determines which DaVinci Resolve tool to use for any adjustment,
 * whether from AI copilot, manual tweaks, or basic corrections.
 *
 * Design philosophy (from the masters):
 * - Tom Poole: "I work very hard at finding the right primary grade with just offset and lift-gamma-gain"
 * - Sam Daley: "I approach the grade as if I'm in a telecine environment"
 * - Joe Gawler: "Finding the bespoke look for a project drives my process"
 *
 * The tool choice is downstream of intent - this module bridges that gap.
 *
 * @module drx/tool-resolver
 */

// ═══════════════════════════════════════════════════════════════════════════════
// TOOL DEFINITIONS
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Contrast tool implementations
 * Each tool has a mapping function that converts normalized -1 to +1 values
 * into the actual DRX parameters
 */
const CONTRAST_TOOLS = {
  /**
   * Lift/Gain Spread - Professional default
   * Creates contrast by lowering shadows (lift) and raising highlights (gain)
   * Preserves midtones, gives clean shadow definition
   */
  liftGainSpread: {
    id: 'liftGainSpread',
    name: 'Lift/Gain Spread',
    description: 'Professional default - clean shadow control, preserves midtones',
    whenToUse: [
      'Default for most contrast adjustments',
      'When you want punchy, snappy contrast',
      'When shadow detail preservation matters',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity;
      return {
        liftMaster: -scaled * 0.25,   // Shadows go opposite direction
        gainMaster: scaled * 0.25,     // Highlights follow value (added to 1.0 base)
      };
    },
  },

  /**
   * Contrast Corrector (Type 2)
   * Uses the dedicated contrast slider with pivot control
   * Good for broad, gentle adjustments
   */
  contrastCorrector: {
    id: 'contrastCorrector',
    name: 'Contrast Corrector',
    description: 'Contrast slider + Pivot - broad, gentle adjustments',
    whenToUse: [
      'Gentle, overall contrast changes',
      'When pivot point matters',
      'Quick broadcast-style adjustments',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const pivot = options.pivot || 0.435;
      const scaled = value * intensity;
      return {
        contrast: scaled,  // semantic -1 to +1, parseAdjustments converts to Resolve range
        pivot: pivot,
      };
    },
  },

  /**
   * Lift/Gamma/Gain Full - Maximum tonal control
   * Adjusts all three zones for comprehensive contrast shaping
   */
  liftGammaGainFull: {
    id: 'liftGammaGainFull',
    name: 'Lift/Gamma/Gain Full',
    description: 'All three wheels - maximum tonal control',
    whenToUse: [
      'Complex contrast shaping',
      'When midtone adjustment is also needed',
      'S-curve-like response without actual curves',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity;
      return {
        liftMaster: -scaled * 0.2,
        gammaMaster: scaled * 0.05,    // Slight midtone boost for punch
        gainMaster: scaled * 0.2,
      };
    },
  },

  /**
   * HDR Zones - Zone-based contrast for HDR workflows
   * Adjusts Dark and Highlight zones independently
   */
  hdrZones: {
    id: 'hdrZones',
    name: 'HDR Zones',
    description: 'Zone-based exposure spreads - HDR workflows',
    whenToUse: [
      'HDR content',
      'When you need zone-specific control',
      'Preserving specular highlights while crushing shadows',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity;
      return {
        hdrDark: { exposure: -scaled * 0.8 },      // Stops, -6 to +6
        hdrHighlight: { exposure: scaled * 0.5 },
      };
    },
  },

  /**
   * Log Wheels Spread - Filmic contrast with smooth transitions
   * Uses log wheels for offset-style contrast
   */
  logWheelsSpread: {
    id: 'logWheelsSpread',
    name: 'Log Wheels Spread',
    description: 'Filmic contrast with smooth tonal transitions',
    whenToUse: [
      'Log-encoded footage',
      'Filmic, organic contrast feel',
      'When you want smoother shadow-to-midtone transitions',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity;
      // Log wheels affect R, G, B equally for luminance-only contrast
      const shadowAmount = -scaled * 0.15;
      const highAmount = scaled * 0.15;
      return {
        logShadowR: shadowAmount,
        logShadowG: shadowAmount,
        logShadowB: shadowAmount,
        logHighR: highAmount,
        logHighG: highAmount,
        logHighB: highAmount,
      };
    },
  },
};

/**
 * Exposure tool implementations
 */
const EXPOSURE_TOOLS = {
  /**
   * Offset Master - True exposure compensation
   * Affects entire image equally, like changing ISO
   */
  offsetMaster: {
    id: 'offsetMaster',
    name: 'Offset',
    description: 'True exposure compensation - affects entire image equally',
    whenToUse: [
      'Overall brightness adjustment',
      'Technical exposure correction',
      'When you want even adjustment across all tones',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity * 0.2;  // Offset is sensitive
      return {
        offsetR: scaled,
        offsetG: scaled,
        offsetB: scaled,
      };
    },
  },

  /**
   * Gain Master - Highlight-focused brightness
   * Traditional "exposure" control, primarily affects highlights
   */
  gainMaster: {
    id: 'gainMaster',
    name: 'Gain Master',
    description: 'Highlight-focused brightness adjustment',
    whenToUse: [
      'Brightening highlights specifically',
      'When shadows should remain stable',
      'Traditional video-style exposure',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity;
      return {
        gainMaster: scaled * 0.5,  // Added to 1.0 base
      };
    },
  },

  /**
   * Lift/Gamma/Gain Combo - Balanced exposure
   * Distributes exposure change across all tonal ranges
   */
  liftGammaGainCombo: {
    id: 'liftGammaGainCombo',
    name: 'Lift/Gamma/Gain Balanced',
    description: 'Balanced exposure using all three wheels',
    whenToUse: [
      'Natural-feeling brightness changes',
      'When you want to maintain tonal relationships',
      'Filmic exposure adjustments',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity;
      return {
        liftMaster: scaled * 0.12,
        gammaMaster: scaled * 0.25,
        gainMaster: scaled * 0.18,
      };
    },
  },

  /**
   * HDR Global - HDR global zone exposure
   * Uses HDR wheels global zone for exposure compensation
   */
  hdrGlobal: {
    id: 'hdrGlobal',
    name: 'HDR Global Zone',
    description: 'HDR Global zone exposure - full range control',
    whenToUse: [
      'HDR workflows',
      'When working in HDR zone-based grading',
      'Large exposure adjustments (up to ±6 stops)',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity;
      return {
        hdrGlobal: { exposure: scaled * 3 },  // -6 to +6 stops range
      };
    },
  },

  /**
   * Gamma Master - Midtone-focused brightness
   * Adjusts perceived brightness without crushing shadows or blowing highlights
   */
  gammaMaster: {
    id: 'gammaMaster',
    name: 'Gamma Master',
    description: 'Midtone-focused brightness - preserves shadow/highlight detail',
    whenToUse: [
      'Adjusting perceived brightness without clipping',
      'When shadow and highlight detail must be preserved',
      'Subtle brightness adjustments',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity;
      return {
        gammaMaster: scaled * 0.35,
      };
    },
  },
};

/**
 * Temperature tool implementations
 */
const TEMPERATURE_TOOLS = {
  /**
   * Temperature Slider - Global temperature shift
   * Simple, direct Kelvin offset
   */
  temperatureSlider: {
    id: 'temperatureSlider',
    name: 'Temperature Slider',
    description: 'Global temperature shift - direct Kelvin control',
    whenToUse: [
      'Simple warm/cool adjustments',
      'Technical white balance correction',
      'When the whole image needs the same shift',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity;
      return {
        temperature: scaled,  // semantic -1 to +1, parseAdjustments converts to wheel values
      };
    },
  },

  /**
   * Lift/Gain Split - Classic teal/orange
   * Warm highlights, cool shadows (or vice versa)
   */
  liftGainSplit: {
    id: 'liftGainSplit',
    name: 'Lift/Gain Color Split',
    description: 'Classic teal/orange - shadows vs highlights color split',
    whenToUse: [
      'Cinematic teal and orange look',
      'When shadows and highlights should have different temperatures',
      'Creative color grading',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity;
      // Positive = warm highlights, cool shadows
      // Negative = cool highlights, warm shadows
      return {
        liftR: -scaled * 0.08,
        liftB: scaled * 0.08,
        gainR: scaled * 0.08,
        gainB: -scaled * 0.08,
      };
    },
  },

  /**
   * Log Wheels Temperature - Filmic temperature transitions
   * Uses log wheels for smoother color transitions between tones
   */
  logWheelsTemp: {
    id: 'logWheelsTemp',
    name: 'Log Wheels Temperature',
    description: 'Filmic temperature with smooth transitions',
    whenToUse: [
      'Log-encoded footage',
      'When you want subtle, filmic temperature shifts',
      'Professional film-style color',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity;
      // Warm = add red, remove blue
      return {
        logShadowR: scaled * 0.06,
        logShadowB: -scaled * 0.06,
        logMidR: scaled * 0.04,
        logMidB: -scaled * 0.04,
        logHighR: scaled * 0.06,
        logHighB: -scaled * 0.06,
      };
    },
  },

  /**
   * Gain RGB Only - Warm/cool highlights only
   * Affects only the highlight range
   */
  gainRGB: {
    id: 'gainRGB',
    name: 'Gain RGB (Highlights)',
    description: 'Temperature shift in highlights only',
    whenToUse: [
      'Warming or cooling just the highlights',
      'Sunset/golden hour on bright areas',
      'When shadows should stay neutral',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity;
      return {
        gainR: scaled * 0.12,
        gainB: -scaled * 0.12,
      };
    },
  },

  /**
   * Lift RGB Only - Warm/cool shadows only
   * Affects only the shadow range
   */
  liftRGB: {
    id: 'liftRGB',
    name: 'Lift RGB (Shadows)',
    description: 'Temperature shift in shadows only',
    whenToUse: [
      'Warming or cooling just the shadows',
      'Adding teal to shadows while keeping highlights neutral',
      'When highlights should stay neutral',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity;
      return {
        liftR: scaled * 0.1,
        liftB: -scaled * 0.1,
      };
    },
  },
};

/**
 * Saturation tool implementations
 */
const SATURATION_TOOLS = {
  /**
   * Saturation Slider - Global saturation
   * Simple multiplier on all colors
   */
  saturationSlider: {
    id: 'saturationSlider',
    name: 'Saturation Slider',
    description: 'Global saturation - affects all colors equally',
    whenToUse: [
      'Simple saturation boost or reduction',
      'When all colors should be affected equally',
      'Quick adjustments',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity;
      return {
        saturation: scaled,  // semantic -1 to +1, parseAdjustments converts to Resolve range
      };
    },
  },

  /**
   * Color Boost - Intelligent saturation
   * Protects already-saturated areas from over-saturation
   */
  colorBoost: {
    id: 'colorBoost',
    name: 'Color Boost',
    description: 'Intelligent saturation - protects already-saturated areas',
    whenToUse: [
      'Boosting saturation without oversaturating',
      'Skin tone protection',
      'Natural-looking saturation increases',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity;
      return {
        colorBoost: Math.max(0, scaled * 50),  // 0-100 range
      };
    },
  },

  /**
   * Per-Zone Saturation - HDR zone saturation control
   * Adjusts saturation in specific luminance zones
   */
  hdrZoneSaturation: {
    id: 'hdrZoneSaturation',
    name: 'HDR Zone Saturation',
    description: 'Zone-based saturation - different saturation per luminance zone',
    whenToUse: [
      'HDR workflows',
      'When you want less saturation in highlights (natural)',
      'Zone-specific saturation control',
    ],
    mapping: (value, options = {}) => {
      const intensity = options.intensity || 1.0;
      const scaled = value * intensity;
      // Slightly less saturation boost in highlights (more natural)
      return {
        hdrDark: { saturation: 1.0 + (scaled * 0.4) },
        hdrShadow: { saturation: 1.0 + (scaled * 0.5) },
        hdrLight: { saturation: 1.0 + (scaled * 0.4) },
        hdrHighlight: { saturation: 1.0 + (scaled * 0.3) },
      };
    },
  },
};

// ═══════════════════════════════════════════════════════════════════════════════
// INTENT MAPPINGS
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Maps intent keywords to preferred tools
 * These are used when the AI or vocabulary provides intent signals
 */
const INTENT_TO_TOOL = {
  contrast: {
    // Snappy, punchy, dynamic
    punchy: 'liftGainSpread',
    snappy: 'liftGainSpread',
    dynamic: 'liftGainSpread',
    pop: 'liftGainSpread',

    // Filmic, organic, smooth
    filmic: 'logWheelsSpread',
    organic: 'logWheelsSpread',
    smooth: 'logWheelsSpread',
    film: 'logWheelsSpread',

    // Soft, gentle, broadcast
    soft: 'contrastCorrector',
    gentle: 'contrastCorrector',
    broadcast: 'contrastCorrector',
    subtle: 'contrastCorrector',

    // HDR, zone-based
    hdr: 'hdrZones',
    zone: 'hdrZones',
    zonal: 'hdrZones',

    // Full control
    full: 'liftGammaGainFull',
    comprehensive: 'liftGammaGainFull',

    // Default
    default: 'liftGainSpread',
  },

  exposure: {
    // Overall brightness
    overall: 'offsetMaster',
    global: 'offsetMaster',
    even: 'offsetMaster',
    correction: 'offsetMaster',

    // Highlight-focused
    highlights: 'gainMaster',
    bright: 'gainMaster',
    hot: 'gainMaster',

    // Shadow-focused (uses lift)
    shadows: 'liftMaster',
    dark: 'liftMaster',

    // Midtone-focused
    midtones: 'gammaMaster',
    perceived: 'gammaMaster',

    // Balanced
    balanced: 'liftGammaGainCombo',
    natural: 'liftGammaGainCombo',
    filmic: 'liftGammaGainCombo',

    // HDR
    hdr: 'hdrGlobal',
    zone: 'hdrGlobal',

    // Default
    default: 'offsetMaster',
  },

  temperature: {
    // Global
    global: 'temperatureSlider',
    overall: 'temperatureSlider',
    correction: 'temperatureSlider',
    whiteBalance: 'temperatureSlider',

    // Split (teal/orange)
    split: 'liftGainSplit',
    tealOrange: 'liftGainSplit',
    cinematic: 'liftGainSplit',
    blockbuster: 'liftGainSplit',

    // Filmic
    filmic: 'logWheelsTemp',
    organic: 'logWheelsTemp',
    smooth: 'logWheelsTemp',

    // Highlight only
    highlightOnly: 'gainRGB',
    highlights: 'gainRGB',
    warmHighlights: 'gainRGB',
    coolHighlights: 'gainRGB',

    // Shadow only
    shadowOnly: 'liftRGB',
    shadows: 'liftRGB',
    warmShadows: 'liftRGB',
    coolShadows: 'liftRGB',

    // Default
    default: 'temperatureSlider',
  },

  saturation: {
    // Global
    global: 'saturationSlider',
    overall: 'saturationSlider',
    simple: 'saturationSlider',

    // Smart/protected
    smart: 'colorBoost',
    protected: 'colorBoost',
    skinSafe: 'colorBoost',
    natural: 'colorBoost',

    // Zone-based
    hdr: 'hdrZoneSaturation',
    zone: 'hdrZoneSaturation',
    zonal: 'hdrZoneSaturation',

    // Default
    default: 'saturationSlider',
  },
};

// ═══════════════════════════════════════════════════════════════════════════════
// DEFAULT USER PREFERENCES
// ═══════════════════════════════════════════════════════════════════════════════

const DEFAULT_USER_PREFERENCES = {
  // Default tool choices (when no intent specified)
  defaultTools: {
    contrast: 'liftGainSpread',
    exposure: 'offsetMaster',
    temperature: 'temperatureSlider',
    saturation: 'saturationSlider',
  },

  // Intensity multipliers (1.0 = as-is, >1 = stronger, <1 = subtler)
  intensityMultipliers: {
    contrast: 1.0,
    exposure: 1.0,
    temperature: 1.0,
    saturation: 1.0,
    tint: 1.0,
    shadowLift: 1.0,
    highlightCompression: 1.0,
  },

  // Wheels mode preference ('primary', 'log', 'hdr')
  wheelsMode: 'primary',

  // When to use per-channel vs master
  perChannelThreshold: 0.15,  // Use per-channel when color splits > this

  // Learned patterns (populated from training data)
  learnedPatterns: {
    preferredContrastRange: [0.15, 0.4],
    preferredSaturationRange: [0.85, 1.2],
    commonLooks: [],
  },
};

// ═══════════════════════════════════════════════════════════════════════════════
// TOOL RESOLVER CLASS
// ═══════════════════════════════════════════════════════════════════════════════

class ToolResolver {
  constructor(userPreferences = {}) {
    this.preferences = { ...DEFAULT_USER_PREFERENCES, ...userPreferences };
    this.tools = {
      contrast: CONTRAST_TOOLS,
      exposure: EXPOSURE_TOOLS,
      temperature: TEMPERATURE_TOOLS,
      saturation: SATURATION_TOOLS,
    };
  }

  /**
   * Update user preferences
   * @param {Object} prefs - New preferences to merge
   */
  setUserPreferences(prefs) {
    this.preferences = {
      ...this.preferences,
      ...prefs,
      defaultTools: { ...this.preferences.defaultTools, ...prefs.defaultTools },
      intensityMultipliers: { ...this.preferences.intensityMultipliers, ...prefs.intensityMultipliers },
    };
  }

  /**
   * Get the tool to use for a given adjustment type and intent
   * @param {string} adjustmentType - 'contrast', 'exposure', 'temperature', 'saturation'
   * @param {string} intent - Optional intent keyword
   * @returns {string} Tool ID
   */
  selectTool(adjustmentType, intent = null) {
    const intentMap = INTENT_TO_TOOL[adjustmentType];
    if (!intentMap) {
      console.warn(`[ToolResolver] Unknown adjustment type: ${adjustmentType}`);
      return null;
    }

    // If intent provided, look it up
    if (intent && intentMap[intent]) {
      return intentMap[intent];
    }

    // Fall back to user's default preference
    const userDefault = this.preferences.defaultTools[adjustmentType];
    if (userDefault) {
      return userDefault;
    }

    // Ultimate fallback
    return intentMap.default;
  }

  /**
   * Get the intensity multiplier for an adjustment type
   * @param {string} adjustmentType
   * @returns {number}
   */
  getIntensityMultiplier(adjustmentType) {
    return this.preferences.intensityMultipliers[adjustmentType] || 1.0;
  }

  /**
   * Resolve a single adjustment to DRX parameters
   * @param {string} adjustmentType - 'contrast', 'exposure', etc.
   * @param {number} value - Normalized value (-1 to +1)
   * @param {Object} options - { intent, pivot, etc. }
   * @returns {Object} DRX parameters
   */
  resolveAdjustment(adjustmentType, value, options = {}) {
    const toolId = this.selectTool(adjustmentType, options.intent);
    const tool = this.tools[adjustmentType]?.[toolId];

    if (!tool) {
      console.warn(`[ToolResolver] Tool not found: ${adjustmentType}/${toolId}`);
      return {};
    }

    // Apply intensity multiplier
    const intensity = this.getIntensityMultiplier(adjustmentType) * (options.intensity || 1.0);

    // Get mapping with options
    const params = tool.mapping(value, { ...options, intensity });

    // Log for debugging
    console.log(`[ToolResolver] ${adjustmentType}: value=${value}, tool=${toolId}, intent=${options.intent || 'default'}`);

    return {
      tool: toolId,
      toolName: tool.name,
      params,
    };
  }

  /**
   * Resolve a full adjustment set (from AI or vocabulary)
   * @param {Object} input - { adjustments: {...}, intent: {...} }
   * @returns {Object} Resolved DRX parameters
   */
  resolve(input) {
    const { adjustments = {}, intent = {} } = input;
    const resolved = {
      params: {},
      tools: {},
      metadata: {
        timestamp: Date.now(),
        preferences: this.preferences.defaultTools,
      },
    };

    // Process contrast
    if (adjustments.contrast !== undefined && Math.abs(adjustments.contrast) > 0.001) {
      const result = this.resolveAdjustment('contrast', adjustments.contrast, {
        intent: intent.contrast,
        pivot: adjustments.pivot,
      });
      Object.assign(resolved.params, result.params);
      resolved.tools.contrast = result.tool;
    }

    // Process exposure
    if (adjustments.exposure !== undefined && Math.abs(adjustments.exposure) > 0.001) {
      const result = this.resolveAdjustment('exposure', adjustments.exposure, {
        intent: intent.exposure,
      });
      Object.assign(resolved.params, result.params);
      resolved.tools.exposure = result.tool;
    }

    // Process temperature
    if (adjustments.temperature !== undefined && Math.abs(adjustments.temperature) > 0.001) {
      const result = this.resolveAdjustment('temperature', adjustments.temperature, {
        intent: intent.temperature,
      });
      Object.assign(resolved.params, result.params);
      resolved.tools.temperature = result.tool;
    }

    // Process saturation
    if (adjustments.saturation !== undefined && Math.abs(adjustments.saturation) > 0.001) {
      const result = this.resolveAdjustment('saturation', adjustments.saturation, {
        intent: intent.saturation,
      });
      Object.assign(resolved.params, result.params);
      resolved.tools.saturation = result.tool;
    }

    // Process tint (passthrough — parseAdjustments handles wheel conversion)
    if (adjustments.tint !== undefined && Math.abs(adjustments.tint) > 0.001) {
      const intensity = this.getIntensityMultiplier('tint');
      resolved.params.tint = adjustments.tint * intensity;  // semantic -1 to +1, parseAdjustments converts
    }

    // Process shadow lift (direct to liftMaster unless already set)
    if (adjustments.shadowLift !== undefined && Math.abs(adjustments.shadowLift) > 0.001) {
      const intensity = this.getIntensityMultiplier('shadowLift');
      // Only set if not already set by another tool
      if (resolved.params.liftMaster === undefined) {
        resolved.params.liftMaster = adjustments.shadowLift * intensity * 0.3;
      } else {
        // Add to existing liftMaster
        resolved.params.liftMaster += adjustments.shadowLift * intensity * 0.3;
      }
    }

    // Process highlight compression
    if (adjustments.highlightCompression !== undefined && adjustments.highlightCompression > 0.001) {
      const intensity = this.getIntensityMultiplier('highlightCompression');
      resolved.params.softClipHigh = 1.0 - (adjustments.highlightCompression * intensity * 0.3);
    }

    // Process midtone detail (passthrough — parseAdjustments handles scaling)
    if (adjustments.midtoneDetail !== undefined && Math.abs(adjustments.midtoneDetail) > 0.001) {
      resolved.params.midtoneDetail = adjustments.midtoneDetail;  // semantic -1 to +1, parseAdjustments scales
    }

    // Process pivot (passthrough)
    if (adjustments.pivot !== undefined) {
      resolved.params.pivot = adjustments.pivot;
    }

    // Pass through any per-channel adjustments directly (user explicitly requested)
    this._passPerChannelAdjustments(adjustments, resolved);

    // Pass through log wheels adjustments directly
    this._passLogWheelsAdjustments(adjustments, resolved);

    // Pass through HDR zone adjustments
    this._passHdrZoneAdjustments(adjustments, resolved);

    return resolved;
  }

  /**
   * Pass through per-channel Lift/Gamma/Gain adjustments
   * These are explicit and bypass tool selection
   */
  _passPerChannelAdjustments(adjustments, resolved) {
    const perChannelKeys = [
      'liftR', 'liftG', 'liftB',
      'gammaR', 'gammaG', 'gammaB',
      'gainR', 'gainG', 'gainB',
    ];

    for (const key of perChannelKeys) {
      if (adjustments[key] !== undefined && Math.abs(adjustments[key]) > 0.001) {
        // Don't overwrite if already set by tool
        if (resolved.params[key] === undefined) {
          resolved.params[key] = adjustments[key];
        }
      }
    }

    // Master channels (be careful not to overwrite tool-generated values)
    const masterKeys = ['liftMaster', 'gammaMaster', 'gainMaster'];
    for (const key of masterKeys) {
      if (adjustments[key] !== undefined && Math.abs(adjustments[key]) > 0.001) {
        if (resolved.params[key] === undefined) {
          resolved.params[key] = adjustments[key];
        }
      }
    }
  }

  /**
   * Pass through log wheels adjustments
   */
  _passLogWheelsAdjustments(adjustments, resolved) {
    const logKeys = [
      'logShadowR', 'logShadowG', 'logShadowB',
      'logMidR', 'logMidG', 'logMidB',
      'logHighR', 'logHighG', 'logHighB',
    ];

    for (const key of logKeys) {
      if (adjustments[key] !== undefined && Math.abs(adjustments[key]) > 0.001) {
        if (resolved.params[key] === undefined) {
          resolved.params[key] = adjustments[key];
        }
      }
    }
  }

  /**
   * Pass through HDR zone adjustments
   */
  _passHdrZoneAdjustments(adjustments, resolved) {
    const hdrZones = ['hdrDark', 'hdrShadow', 'hdrLight', 'hdrHighlight', 'hdrGlobal'];

    for (const zone of hdrZones) {
      if (adjustments[zone] !== undefined) {
        if (resolved.params[zone] === undefined) {
          resolved.params[zone] = adjustments[zone];
        } else {
          // Merge zone properties
          resolved.params[zone] = { ...resolved.params[zone], ...adjustments[zone] };
        }
      }
    }
  }

  /**
   * Get information about available tools for a given adjustment type
   * @param {string} adjustmentType
   * @returns {Object[]} Array of tool info objects
   */
  getAvailableTools(adjustmentType) {
    const tools = this.tools[adjustmentType];
    if (!tools) return [];

    return Object.values(tools).map(tool => ({
      id: tool.id,
      name: tool.name,
      description: tool.description,
      whenToUse: tool.whenToUse,
    }));
  }

  /**
   * Get the current tool selection for an adjustment type
   * @param {string} adjustmentType
   * @returns {Object} Tool info
   */
  getCurrentTool(adjustmentType) {
    const toolId = this.preferences.defaultTools[adjustmentType];
    const tool = this.tools[adjustmentType]?.[toolId];
    return tool ? {
      id: tool.id,
      name: tool.name,
      description: tool.description,
    } : null;
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SINGLETON INSTANCE & EXPORTS
// ═══════════════════════════════════════════════════════════════════════════════

// Create default instance
const defaultResolver = new ToolResolver();

module.exports = {
  // Classes
  ToolResolver,

  // Default instance
  defaultResolver,

  // Tool definitions (for inspection/UI)
  CONTRAST_TOOLS,
  EXPOSURE_TOOLS,
  TEMPERATURE_TOOLS,
  SATURATION_TOOLS,

  // Intent mappings
  INTENT_TO_TOOL,

  // Default preferences
  DEFAULT_USER_PREFERENCES,

  // Convenience functions using default resolver
  resolve: (input) => defaultResolver.resolve(input),
  resolveAdjustment: (type, value, options) => defaultResolver.resolveAdjustment(type, value, options),
  selectTool: (type, intent) => defaultResolver.selectTool(type, intent),
  setUserPreferences: (prefs) => defaultResolver.setUserPreferences(prefs),
  getAvailableTools: (type) => defaultResolver.getAvailableTools(type),
  getCurrentTool: (type) => defaultResolver.getCurrentTool(type),
};
