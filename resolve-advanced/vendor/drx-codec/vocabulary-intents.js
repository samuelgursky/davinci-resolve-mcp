/**
 * Vocabulary Intent Overlay
 *
 * Maps cinematographer vocabulary terms to tool selection intents.
 * This overlay works with the existing CINEMATOGRAPHER_VOCABULARY to provide
 * tool selection guidance without modifying the core vocabulary.
 *
 * The intent signals are used by the ToolResolver to select the appropriate
 * DaVinci Resolve tool for each adjustment.
 *
 * @module drx/vocabulary-intents
 */

// ═══════════════════════════════════════════════════════════════════════════════
// CONTRAST INTENT MAPPINGS
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Terms that indicate specific contrast tool preferences
 */
const CONTRAST_INTENTS = {
  // Punchy/Snappy/Dynamic → Lift/Gain Spread
  punchy: 'punchy',
  punchier: 'punchy',
  punch: 'punchy',
  snappy: 'snappy',
  snappier: 'snappy',
  pop: 'punchy',
  popping: 'punchy',
  poppy: 'punchy',
  dynamic: 'dynamic',
  dynamic_range: 'dynamic',
  bold: 'punchy',
  bolder: 'punchy',
  crisp: 'punchy',
  crisper: 'punchy',
  crispy: 'punchy',
  hard: 'punchy',
  harder: 'punchy',
  harsh: 'punchy',
  harsher: 'punchy',
  aggressive_contrast: 'punchy',
  high_contrast: 'punchy',

  // Filmic/Organic → Log Wheels or Curves
  filmic: 'filmic',
  filmic_contrast: 'filmic',
  organic: 'organic',
  film: 'filmic',
  film_contrast: 'filmic',
  cinematic: 'filmic',
  cinematic_contrast: 'filmic',
  log: 'filmic',
  log_contrast: 'filmic',
  s_curve: 'filmic',

  // Soft/Gentle → Contrast Corrector
  soft: 'soft',
  softer: 'soft',
  softest: 'soft',
  gentle: 'gentle',
  gentler: 'gentle',
  subtle: 'subtle',
  light_contrast: 'subtle',
  medium_contrast: 'soft',
  broadcast_contrast: 'broadcast',
  broadcast: 'broadcast',

  // Flat/Low → Negative contrast, same tools
  flat: 'soft',
  flatter: 'soft',
  flattest: 'soft',
  low_contrast: 'soft',
  no_contrast: 'soft',
  compressed: 'soft',

  // Crushed → Lift/Gain with shadow focus
  crushed: 'punchy',
  crushing: 'punchy',
  clipped: 'punchy',

  // Lifted/Milky → Lift-focused
  milky: 'soft',
  lifted: 'soft',
  lifted_blacks: 'soft',
  lifted_shadows: 'soft',
  raised_blacks: 'soft',

  // Dense/Thick
  dense: 'punchy',
  denser: 'punchy',
  density: 'punchy',
  thick: 'punchy',
  thicker: 'punchy',
  weighted: 'punchy',
  heavy: 'punchy',
  heavier: 'punchy',
};

// ═══════════════════════════════════════════════════════════════════════════════
// EXPOSURE INTENT MAPPINGS
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Terms that indicate specific exposure tool preferences
 */
const EXPOSURE_INTENTS = {
  // Overall/Global → Offset
  bright: 'overall',
  brighter: 'overall',
  brighten: 'overall',
  brightened: 'overall',
  dark: 'overall',
  darker: 'overall',
  darken: 'overall',
  darkened: 'overall',
  exposure: 'overall',
  exposed: 'overall',
  underexposed: 'correction',
  overexposed: 'correction',

  // Highlight-focused → Gain
  hot: 'highlights',
  hotter: 'highlights',
  blown: 'highlights',
  clipped_highlights: 'highlights',
  highlight: 'highlights',
  highlights: 'highlights',

  // Shadow-focused → Lift
  shadow: 'shadows',
  shadows: 'shadows',
  shadow_detail: 'shadows',
  crushed_shadows: 'shadows',

  // Midtone-focused → Gamma
  midtone: 'midtones',
  midtones: 'midtones',
  middle_gray: 'midtones',
  gray: 'midtones',

  // Balanced/Natural → Lift/Gamma/Gain combo
  natural: 'balanced',
  natural_light: 'balanced',
  balanced: 'balanced',
  even: 'even',

  // Film terms → Balanced/Filmic approach
  stop: 'overall',      // "one stop brighter"
  stops: 'overall',
  ev: 'overall',        // Exposure value
  iso: 'overall',
};

// ═══════════════════════════════════════════════════════════════════════════════
// TEMPERATURE INTENT MAPPINGS
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Terms that indicate specific temperature tool preferences
 */
const TEMPERATURE_INTENTS = {
  // Global temperature → Temperature Slider
  warm: 'global',
  warmer: 'global',
  warmth: 'global',
  cool: 'global',
  cooler: 'global',
  cold: 'global',
  colder: 'global',
  neutral: 'global',
  daylight: 'global',
  tungsten: 'global',
  white_balance: 'correction',
  wb: 'correction',

  // Split looks → Lift/Gain Split
  teal: 'split',
  teal_orange: 'split',
  teal_and_orange: 'split',
  blockbuster: 'split',
  complementary: 'split',
  split_tone: 'split',
  split_toning: 'split',
  cross_processed: 'split',
  cross_process: 'split',

  // Cinematic → Log Wheels or Split
  cinematic: 'cinematic',
  cinematic_warmth: 'cinematic',
  film_warmth: 'filmic',
  filmic: 'filmic',

  // Highlight-only temperature
  warm_highlights: 'highlightOnly',
  golden_highlights: 'highlightOnly',
  sunset_highlights: 'highlightOnly',
  cool_highlights: 'highlightOnly',

  // Shadow-only temperature
  cool_shadows: 'shadowOnly',
  teal_shadows: 'shadowOnly',
  blue_shadows: 'shadowOnly',
  warm_shadows: 'shadowOnly',

  // Light source references often need global
  candlelight: 'global',
  candlelit: 'global',
  firelight: 'global',
  moonlight: 'global',
  moonlit: 'global',
  golden: 'global',
  golden_hour: 'global',
  blue_hour: 'global',
  magic_hour: 'global',
  amber: 'global',
  honey: 'global',
  sepia: 'global',
};

// ═══════════════════════════════════════════════════════════════════════════════
// SATURATION INTENT MAPPINGS
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Terms that indicate specific saturation tool preferences
 */
const SATURATION_INTENTS = {
  // Global saturation → Saturation Slider
  saturated: 'global',
  saturation: 'global',
  desaturated: 'global',
  desaturation: 'global',
  desat: 'global',
  oversaturated: 'global',
  undersaturated: 'global',

  // Protected/Smart → Color Boost
  vibrant: 'smart',
  vibrance: 'smart',
  vibrancy: 'smart',
  vivid: 'smart',
  vividness: 'smart',
  rich: 'smart',
  richer: 'smart',
  richness: 'smart',
  lush: 'smart',
  lusher: 'smart',
  juicy: 'smart',
  natural: 'natural',
  natural_color: 'natural',
  true_color: 'natural',
  accurate_color: 'natural',
  boosted: 'smart',
  boosted_color: 'smart',
  enhanced: 'smart',
  enhanced_color: 'smart',

  // Skin-safe → Color Boost
  skin_safe: 'skinSafe',
  protect_skin: 'skinSafe',
  skin_tone: 'skinSafe',

  // Muted/Subtle → Simple slider (or smart for pull-back)
  muted: 'global',
  muted_colors: 'global',
  subdued: 'global',
  restrained: 'global',
  subtle_color: 'global',
  pastel: 'global',
  pastels: 'global',

  // Extreme → Simple slider
  monochrome: 'global',
  monochromatic: 'global',
  black_and_white: 'global',
  bw: 'global',
  grayscale: 'global',
  colorless: 'global',

  // Zone-based
  hdr_saturation: 'zone',
  zone_saturation: 'zone',
};

// ═══════════════════════════════════════════════════════════════════════════════
// LOOK/STYLE INTENT MAPPINGS
// These terms imply multiple tool choices
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Complex look terms that imply multiple intent choices
 */
const LOOK_INTENTS = {
  // Film stock looks
  kodak: {
    contrast: 'filmic',
    temperature: 'global',
    saturation: 'smart',
  },
  fuji: {
    contrast: 'filmic',
    temperature: 'global',
    saturation: 'smart',
  },
  portra: {
    contrast: 'soft',
    temperature: 'global',
    saturation: 'natural',
  },
  velvia: {
    contrast: 'punchy',
    saturation: 'global',
  },
  kodachrome: {
    contrast: 'punchy',
    saturation: 'smart',
  },
  cinestill: {
    contrast: 'filmic',
    temperature: 'global',
    saturation: 'smart',
  },
  eterna: {
    contrast: 'filmic',
    temperature: 'global',
    saturation: 'natural',
  },

  // Process looks
  bleach_bypass: {
    contrast: 'punchy',
    saturation: 'global',
  },
  skip_bleach: {
    contrast: 'punchy',
    saturation: 'global',
  },
  cross_processed: {
    contrast: 'filmic',
    temperature: 'split',
    saturation: 'smart',
  },
  technicolor: {
    contrast: 'punchy',
    saturation: 'global',
    temperature: 'global',
  },

  // Style looks
  cinematic: {
    contrast: 'filmic',
    temperature: 'cinematic',
    saturation: 'smart',
  },
  blockbuster: {
    contrast: 'punchy',
    temperature: 'split',
    saturation: 'smart',
  },
  documentary: {
    contrast: 'soft',
    temperature: 'correction',
    saturation: 'natural',
  },
  commercial: {
    contrast: 'punchy',
    saturation: 'smart',
  },
  broadcast: {
    contrast: 'broadcast',
    saturation: 'global',
  },
  noir: {
    contrast: 'punchy',
    saturation: 'global',
  },
  vintage: {
    contrast: 'soft',
    temperature: 'global',
    saturation: 'natural',
  },
  retro: {
    contrast: 'soft',
    temperature: 'global',
    saturation: 'natural',
  },
  moody: {
    contrast: 'filmic',
    saturation: 'natural',
  },
  dreamy: {
    contrast: 'soft',
    saturation: 'natural',
  },
};

// ═══════════════════════════════════════════════════════════════════════════════
// INTENT EXTRACTION FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Extract intents from a vocabulary term or list of terms
 * @param {string|string[]} terms - Vocabulary term(s)
 * @returns {Object} Intent object { contrast, exposure, temperature, saturation }
 */
function extractIntents(terms) {
  const termList = Array.isArray(terms) ? terms : [terms];
  const intents = {};

  for (const term of termList) {
    const normalized = term.toLowerCase().replace(/[\s-]+/g, '_');

    // Check each intent category
    if (CONTRAST_INTENTS[normalized] && !intents.contrast) {
      intents.contrast = CONTRAST_INTENTS[normalized];
    }
    if (EXPOSURE_INTENTS[normalized] && !intents.exposure) {
      intents.exposure = EXPOSURE_INTENTS[normalized];
    }
    if (TEMPERATURE_INTENTS[normalized] && !intents.temperature) {
      intents.temperature = TEMPERATURE_INTENTS[normalized];
    }
    if (SATURATION_INTENTS[normalized] && !intents.saturation) {
      intents.saturation = SATURATION_INTENTS[normalized];
    }

    // Check look intents (these can set multiple)
    if (LOOK_INTENTS[normalized]) {
      const lookIntent = LOOK_INTENTS[normalized];
      for (const [key, value] of Object.entries(lookIntent)) {
        if (!intents[key]) {
          intents[key] = value;
        }
      }
    }
  }

  return intents;
}

/**
 * Extract intents from a user request string
 * Parses the request for known vocabulary terms and extracts their intents
 * @param {string} request - User request string
 * @returns {Object} Intent object
 */
function extractIntentsFromRequest(request) {
  if (!request) return {};

  // Normalize and tokenize
  const normalized = request.toLowerCase();
  const words = normalized.split(/[\s,;.!?]+/).filter(w => w.length > 2);

  // Also check multi-word phrases
  const phrases = [];
  for (let i = 0; i < words.length - 1; i++) {
    phrases.push(words[i] + '_' + words[i + 1]);
    if (i < words.length - 2) {
      phrases.push(words[i] + '_' + words[i + 1] + '_' + words[i + 2]);
    }
  }

  const allTerms = [...words, ...phrases];
  return extractIntents(allTerms);
}

/**
 * Get the intent for a specific adjustment type from a term
 * @param {string} term - Vocabulary term
 * @param {string} adjustmentType - 'contrast', 'exposure', 'temperature', 'saturation'
 * @returns {string|null} Intent or null
 */
function getIntentForAdjustment(term, adjustmentType) {
  const normalized = term.toLowerCase().replace(/[\s-]+/g, '_');

  switch (adjustmentType) {
    case 'contrast':
      return CONTRAST_INTENTS[normalized] || null;
    case 'exposure':
      return EXPOSURE_INTENTS[normalized] || null;
    case 'temperature':
      return TEMPERATURE_INTENTS[normalized] || null;
    case 'saturation':
      return SATURATION_INTENTS[normalized] || null;
    default:
      return null;
  }
}

/**
 * Check if a term has any associated intents
 * @param {string} term - Vocabulary term
 * @returns {boolean}
 */
function hasIntent(term) {
  const normalized = term.toLowerCase().replace(/[\s-]+/g, '_');
  return !!(
    CONTRAST_INTENTS[normalized] ||
    EXPOSURE_INTENTS[normalized] ||
    TEMPERATURE_INTENTS[normalized] ||
    SATURATION_INTENTS[normalized] ||
    LOOK_INTENTS[normalized]
  );
}

/**
 * Get all intents for debugging/inspection
 * @returns {Object} All intent mappings
 */
function getAllIntents() {
  return {
    contrast: CONTRAST_INTENTS,
    exposure: EXPOSURE_INTENTS,
    temperature: TEMPERATURE_INTENTS,
    saturation: SATURATION_INTENTS,
    looks: LOOK_INTENTS,
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// EXPORTS
// ═══════════════════════════════════════════════════════════════════════════════

module.exports = {
  // Intent maps
  CONTRAST_INTENTS,
  EXPOSURE_INTENTS,
  TEMPERATURE_INTENTS,
  SATURATION_INTENTS,
  LOOK_INTENTS,

  // Functions
  extractIntents,
  extractIntentsFromRequest,
  getIntentForAdjustment,
  hasIntent,
  getAllIntents,
};
