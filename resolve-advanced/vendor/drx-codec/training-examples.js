/**
 * Training Examples Library (renamed from look-recipes.js)
 *
 * Named look presets with concrete adjustment values, multi-node configurations,
 * and colorist reasoning for AI-driven grading decisions. Each recipe includes
 * a `reasoning` field explaining the creative intent and technique behind the
 * parameter choices — enabling AI agents to understand the "why" behind each look,
 * not just the "what".
 *
 * Each recipe provides:
 * - adjustments: parameter values in the -1 to +1 space used by resolveGrade
 * - reasoning: colorist note explaining creative intent and technique
 * - intent: tool selection hints for the ToolResolver
 * - nodeLabel: descriptive label for the grade node
 * - multiNode: optional multi-node configuration for more sophisticated looks
 *
 * Recipes are derived from real-world colorist techniques documented in
 * the @colorist skill and verified via round-trip DRX generation → Resolve application.
 *
 * @module drx/training-examples
 */

// ═══════════════════════════════════════════════════════════════════════════════
// LOOK RECIPES
// ═══════════════════════════════════════════════════════════════════════════════

const LOOK_RECIPES = {
  // ───────────────────────────────────────────────────────────────────────────
  // Cinematic Looks
  // ───────────────────────────────────────────────────────────────────────────

  cinematic_warm: {
    name: 'Cinematic Warm',
    description: 'Warm, slightly desaturated look with lifted blacks. Classic narrative cinema.',
    category: 'cinematic',
    reasoning: 'Warm highlights push emotional intimacy while desaturated midtones keep the image grounded. The lifted blacks prevent the shadows from going fully crushed, maintaining detail in dark areas — a hallmark of modern narrative cinema from colorists like Jill Bogdanowicz.',
    adjustments: {
      temperature: 0.25,
      contrast: 0.15,
      saturation: -0.15,
      gainR: 0.12,
      gainB: -0.08,
      liftR: 0.02,
      liftG: 0.01,
      liftB: -0.01,
    },
    intent: { contrast: 'filmic', temperature: 'cinematic', saturation: 'smart' },
    nodeLabel: 'Cinematic Warm',
    multiNode: {
      nodes: [
        {
          label: 'Balance',
          adjustments: { exposure: 0.05, contrast: 0.08 },
          intent: { contrast: 'soft' },
        },
        {
          label: 'Warm Creative',
          adjustments: {
            temperature: 0.25,
            saturation: -0.15,
            gainR: 0.12,
            gainB: -0.08,
            liftR: 0.02,
            liftG: 0.01,
            liftB: -0.01,
            contrast: 0.08,
          },
          intent: { contrast: 'filmic', temperature: 'cinematic', saturation: 'smart' },
        },
      ],
    },
  },

  bleach_bypass: {
    name: 'Bleach Bypass',
    description: 'Heavy desaturation, high contrast, milky lifted blacks. Silver retention look.',
    category: 'cinematic',
    reasoning: 'Simulates the photochemical process of skipping the bleach bath, retaining silver in the print. Heavy desaturation with high contrast creates a gritty, unsettling quality. The milky lifted blacks are the signature — pure black doesn\'t exist in a true bleach bypass.',
    adjustments: {
      saturation: -0.65,
      contrast: 0.45,
      exposure: -0.05,
      liftR: 0.03,
      liftG: 0.03,
      liftB: 0.03,
      gainR: -0.05,
      gainG: -0.05,
      gainB: -0.05,
    },
    intent: { contrast: 'punchy', saturation: 'global' },
    nodeLabel: 'Bleach Bypass',
    multiNode: {
      nodes: [
        {
          label: 'Base Contrast',
          adjustments: { contrast: 0.45, exposure: -0.05 },
          intent: { contrast: 'punchy' },
        },
        {
          label: 'Silver Retention',
          adjustments: {
            saturation: -0.65,
            liftR: 0.03, liftG: 0.03, liftB: 0.03,
          },
          intent: { saturation: 'global' },
        },
        {
          label: 'Output Trim',
          adjustments: {
            gainR: -0.05, gainG: -0.05, gainB: -0.05,
          },
          intent: {},
        },
      ],
    },
  },

  teal_and_orange: {
    name: 'Teal and Orange',
    description: 'Complementary color split: teal shadows, orange highlights. Modern blockbuster.',
    category: 'cinematic',
    reasoning: 'Complementary color theory applied to skin tones vs backgrounds. Orange in the highlights flatters skin while teal in the shadows creates depth and separation. Pioneered in modern blockbusters — the contrast between warm foreground and cool environment guides the eye.',
    adjustments: {
      saturation: 0.1,
      liftR: -0.03,
      liftB: 0.04,
      gainR: 0.12,
      gainB: -0.09,
    },
    intent: { contrast: 'filmic', temperature: 'split', saturation: 'smart' },
    nodeLabel: 'Teal & Orange',
    multiNode: {
      nodes: [
        {
          label: 'Primary Balance',
          adjustments: { contrast: 0.1 },
          intent: { contrast: 'filmic' },
        },
        {
          label: 'Teal Shadows',
          adjustments: { liftR: -0.03, liftB: 0.04 },
          intent: { temperature: 'shadowOnly' },
        },
        {
          label: 'Orange Highlights',
          adjustments: { gainR: 0.12, gainB: -0.09, saturation: 0.1 },
          intent: { temperature: 'highlightOnly', saturation: 'smart' },
        },
      ],
    },
  },

  noir: {
    name: 'Film Noir',
    description: 'High contrast, deep blacks, near-monochrome. Classic noir atmosphere.',
    category: 'cinematic',
    reasoning: 'Deep blacks and near-monochrome evoke the hard shadows of 1940s crime cinema. High contrast with minimal saturation — the story is told through light and shadow, not color.',
    adjustments: {
      contrast: 0.5,
      saturation: -0.7,
      liftR: -0.02, liftG: -0.02, liftB: -0.02,
      gainR: -0.03, gainG: -0.03, gainB: -0.03,
    },
    intent: { contrast: 'punchy', saturation: 'global' },
    nodeLabel: 'Film Noir',
  },

  // ───────────────────────────────────────────────────────────────────────────
  // Film Stock Emulations
  // ───────────────────────────────────────────────────────────────────────────

  kodachrome: {
    name: 'Kodachrome',
    description: 'Rich, saturated with warm midtones and slightly lifted blacks. Iconic reversal film.',
    category: 'film_stock',
    reasoning: 'Emulates Kodak\'s legendary reversal film: rich, punchy color with warm midtones. The slight lift in blacks prevents harsh shadows — Kodachrome never had true black, just deep warm tones.',
    adjustments: {
      saturation: 0.15,
      contrast: 0.2,
      temperature: 0.15,
      liftR: 0.01, liftG: 0.005, liftB: -0.005,
      gammaR: 0.02, gammaG: 0.01, gammaB: -0.01,
    },
    intent: { contrast: 'punchy', saturation: 'smart' },
    nodeLabel: 'Kodachrome',
  },

  portra: {
    name: 'Portra 400',
    description: 'Soft, pastel tones with beautiful skin rendition. Low contrast negative film.',
    category: 'film_stock',
    reasoning: 'Negative film known for gorgeous skin rendition. Low contrast preserves highlight detail, soft pastels keep color relationships natural. The slight warmth is the film base — Portra always had that quality.',
    adjustments: {
      saturation: -0.1,
      contrast: -0.15,
      temperature: 0.08,
      liftR: 0.02, liftG: 0.015, liftB: 0.01,
    },
    intent: { contrast: 'soft', temperature: 'global', saturation: 'natural' },
    nodeLabel: 'Portra 400',
  },

  fuji_eterna: {
    name: 'Fuji Eterna',
    description: 'Cool, slightly desaturated with gentle highlight rolloff. Japanese cinema stock.',
    category: 'film_stock',
    reasoning: 'Japanese cinema stock known for cool, restrained color. Slight desaturation with gentle highlight rolloff — Eterna renders skin delicately without the warmth of Western stocks.',
    adjustments: {
      saturation: -0.12,
      contrast: 0.05,
      temperature: -0.1,
      gainR: -0.02, gainB: 0.02,
    },
    intent: { contrast: 'filmic', temperature: 'global', saturation: 'natural' },
    nodeLabel: 'Fuji Eterna',
  },

  ektachrome: {
    name: 'Ektachrome',
    description: 'Vivid blues, punchy contrast. Cross-process reversal feel.',
    category: 'film_stock',
    reasoning: 'Vivid blues and punchy contrast — Ektachrome\'s reversal character. The slight blue push in shadows and highlights creates that distinctive transparency look of projected slides.',
    adjustments: {
      saturation: 0.1,
      contrast: 0.25,
      temperature: -0.08,
      gainB: 0.05,
      liftR: -0.01, liftB: 0.02,
    },
    intent: { contrast: 'punchy', saturation: 'smart' },
    nodeLabel: 'Ektachrome',
  },

  // ───────────────────────────────────────────────────────────────────────────
  // Documentary / Natural
  // ───────────────────────────────────────────────────────────────────────────

  documentary_clean: {
    name: 'Documentary Clean',
    description: 'Neutral, balanced grade. Minimal stylization, honest representation.',
    category: 'documentary',
    reasoning: 'Minimal intervention. Slight contrast boost to combat flat Log/RAW footage, tiny desaturation to avoid hyperreal digital color. The goal is honest representation — the image should feel unmanipulated.',
    adjustments: {
      contrast: 0.08,
      saturation: -0.05,
    },
    intent: { contrast: 'soft', saturation: 'natural' },
    nodeLabel: 'Documentary Clean',
  },

  verite: {
    name: 'Vérité',
    description: 'Raw, natural feel with slight lift. Observational documentary aesthetic.',
    category: 'documentary',
    reasoning: 'Observational documentary aesthetic. Slightly lifted blacks and reduced contrast mimic the look of naturally-lit observational footage. The desaturation suggests unprocessed, authentic capture.',
    adjustments: {
      contrast: -0.05,
      saturation: -0.1,
      liftR: 0.015, liftG: 0.015, liftB: 0.015,
    },
    intent: { contrast: 'soft', saturation: 'natural' },
    nodeLabel: 'Vérité',
  },

  // ───────────────────────────────────────────────────────────────────────────
  // Mood / Atmosphere
  // ───────────────────────────────────────────────────────────────────────────

  golden_hour: {
    name: 'Golden Hour',
    description: 'Warm, amber-toned with soft contrast. Late afternoon sunlight.',
    category: 'mood',
    reasoning: 'Replicates the warm amber light of late afternoon sun. Strong temperature shift with a gamma push in red/green creates depth in the warmth. Soft contrast prevents the image from feeling harsh.',
    adjustments: {
      temperature: 0.35,
      saturation: 0.08,
      contrast: -0.05,
      gainR: 0.08,
      gammaR: 0.03, gammaG: 0.01,
    },
    intent: { temperature: 'global', saturation: 'smart', contrast: 'soft' },
    nodeLabel: 'Golden Hour',
  },

  moonlight: {
    name: 'Moonlight',
    description: 'Cool blue shadows, desaturated. Night exterior mood.',
    category: 'mood',
    reasoning: 'Cool blue shadows, heavy desaturation, dropped exposure. The blue comes from the Purkinje effect — human vision shifts toward blue sensitivity in low light. Multiple nodes separate the temperature shift from the tonal work.',
    adjustments: {
      temperature: -0.3,
      saturation: -0.25,
      contrast: 0.15,
      exposure: -0.15,
      liftB: 0.03,
      gainB: 0.04,
    },
    intent: { temperature: 'global', saturation: 'global', contrast: 'filmic' },
    nodeLabel: 'Moonlight',
    multiNode: {
      nodes: [
        {
          label: 'Cool Temp Base',
          adjustments: { temperature: -0.3 },
          intent: { temperature: 'global' },
        },
        {
          label: 'Teal Shadows',
          adjustments: { liftB: 0.03, liftR: -0.02 },
          intent: { temperature: 'shadowOnly' },
        },
        {
          label: 'Highlight Rolloff',
          adjustments: { gainB: 0.04, exposure: -0.15 },
          intent: {},
        },
        {
          label: 'Desat + Contrast',
          adjustments: { saturation: -0.25, contrast: 0.15 },
          intent: { saturation: 'global', contrast: 'filmic' },
        },
      ],
    },
  },

  dreamy: {
    name: 'Dreamy',
    description: 'Soft, low-contrast with lifted blacks and gentle warmth. Ethereal mood.',
    category: 'mood',
    reasoning: 'Ultra-low contrast with lifted blacks creates a hazy, ethereal quality. The slight warmth prevents the image from feeling clinical. This is the look of memory and nostalgia.',
    adjustments: {
      contrast: -0.25,
      saturation: -0.15,
      temperature: 0.1,
      liftR: 0.04, liftG: 0.035, liftB: 0.03,
    },
    intent: { contrast: 'soft', saturation: 'natural' },
    nodeLabel: 'Dreamy',
  },

  // ───────────────────────────────────────────────────────────────────────────
  // Commercial / Broadcast
  // ───────────────────────────────────────────────────────────────────────────

  commercial_pop: {
    name: 'Commercial Pop',
    description: 'Clean, contrasty, vivid. Product-forward commercial look.',
    category: 'commercial',
    reasoning: 'Clean and vivid for product-forward work. Contrast and saturation boost together make images jump off the screen. No color shifts — the product\'s color must be accurate.',
    adjustments: {
      contrast: 0.25,
      saturation: 0.15,
    },
    intent: { contrast: 'punchy', saturation: 'smart' },
    nodeLabel: 'Commercial Pop',
  },

  broadcast_safe: {
    name: 'Broadcast Safe',
    description: 'Neutral, legal-level-safe grade. Broadcast delivery baseline.',
    category: 'commercial',
    reasoning: 'Conservative grade to ensure legal levels for broadcast. Minimal contrast avoidance of clipping, slight desaturation to stay within gamut. The most important thing is what you don\'t do.',
    adjustments: {
      contrast: 0.05,
      saturation: -0.03,
    },
    intent: { contrast: 'broadcast', saturation: 'global' },
    nodeLabel: 'Broadcast Safe',
  },

  // ───────────────────────────────────────────────────────────────────────────
  // Vintage / Retro
  // ───────────────────────────────────────────────────────────────────────────

  vintage_70s: {
    name: '70s Vintage',
    description: 'Faded, warm with green-shifted midtones. 1970s film aesthetic.',
    category: 'vintage',
    reasoning: 'Faded, warm with green-shifted midtones. The gamma green push is the key — 1970s film stocks and processing had this characteristic green drift in the mids. Low contrast and lifted blacks simulate aged print stock.',
    adjustments: {
      contrast: -0.1,
      saturation: -0.2,
      temperature: 0.15,
      liftR: 0.02, liftG: 0.025, liftB: 0.015,
      gammaG: 0.02,
    },
    intent: { contrast: 'soft', temperature: 'global', saturation: 'natural' },
    nodeLabel: '70s Vintage',
  },

  cross_process: {
    name: 'Cross Process',
    description: 'Shifted color channels, high contrast. Deliberate chemical mismatch.',
    category: 'vintage',
    reasoning: 'Deliberately processing film in the wrong chemistry creates unpredictable, vivid color shifts. The blue lift + green gamma + warm gain creates the characteristic cross-process color inversions.',
    adjustments: {
      contrast: 0.35,
      saturation: 0.1,
      liftB: 0.06,
      gammaG: 0.06,
      gainR: 0.15, gainB: -0.1,
    },
    intent: { contrast: 'filmic', temperature: 'split', saturation: 'smart' },
    nodeLabel: 'Cross Process',
  },
};

// ═══════════════════════════════════════════════════════════════════════════════
// LOOKUP FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Name aliases — maps natural language variants to recipe keys
 */
const NAME_ALIASES = {
  // Direct names
  'cinematic warm': 'cinematic_warm',
  'cinematic': 'cinematic_warm',
  'warm cinematic': 'cinematic_warm',
  'bleach bypass': 'bleach_bypass',
  'bleach': 'bleach_bypass',
  'skip bleach': 'bleach_bypass',
  'teal and orange': 'teal_and_orange',
  'teal orange': 'teal_and_orange',
  'teal & orange': 'teal_and_orange',
  'blockbuster': 'teal_and_orange',
  'noir': 'noir',
  'film noir': 'noir',
  'kodachrome': 'kodachrome',
  'portra': 'portra',
  'portra 400': 'portra',
  'eterna': 'fuji_eterna',
  'fuji eterna': 'fuji_eterna',
  'fuji': 'fuji_eterna',
  'ektachrome': 'ektachrome',
  'documentary': 'documentary_clean',
  'documentary clean': 'documentary_clean',
  'clean': 'documentary_clean',
  'verite': 'verite',
  'vérité': 'verite',
  'observational': 'verite',
  'golden hour': 'golden_hour',
  'golden': 'golden_hour',
  'sunset': 'golden_hour',
  'moonlight': 'moonlight',
  'night': 'moonlight',
  'blue night': 'moonlight',
  'dreamy': 'dreamy',
  'ethereal': 'dreamy',
  'commercial': 'commercial_pop',
  'commercial pop': 'commercial_pop',
  'pop': 'commercial_pop',
  'broadcast': 'broadcast_safe',
  'broadcast safe': 'broadcast_safe',
  '70s': 'vintage_70s',
  '70s vintage': 'vintage_70s',
  'vintage': 'vintage_70s',
  'retro': 'vintage_70s',
  'cross process': 'cross_process',
  'cross processed': 'cross_process',
  'xpro': 'cross_process',
};

/**
 * Find a look recipe by name (fuzzy matching via aliases)
 * @param {string} name - Look name (natural language)
 * @returns {Object|null} Recipe object or null
 */
function findRecipe(name) {
  if (!name) return null;
  const normalized = name.toLowerCase().trim().replace(/[-_]+/g, ' ');

  // Direct key match
  if (LOOK_RECIPES[normalized.replace(/\s+/g, '_')]) {
    return LOOK_RECIPES[normalized.replace(/\s+/g, '_')];
  }

  // Alias match
  if (NAME_ALIASES[normalized]) {
    return LOOK_RECIPES[NAME_ALIASES[normalized]];
  }

  // Partial match — find first recipe whose name contains the search term
  for (const [key, recipe] of Object.entries(LOOK_RECIPES)) {
    if (recipe.name.toLowerCase().includes(normalized) ||
        key.includes(normalized.replace(/\s+/g, '_'))) {
      return recipe;
    }
  }

  return null;
}

/**
 * List all available recipes
 * @param {string} [category] - Filter by category
 * @returns {Array<{key: string, name: string, description: string, category: string}>}
 */
function listRecipes(category = null) {
  return Object.entries(LOOK_RECIPES)
    .filter(([, recipe]) => !category || recipe.category === category)
    .map(([key, recipe]) => ({
      key,
      name: recipe.name,
      description: recipe.description,
      category: recipe.category,
      hasMultiNode: !!recipe.multiNode,
    }));
}

/**
 * Get all category names
 * @returns {string[]}
 */
function getCategories() {
  const cats = new Set();
  for (const recipe of Object.values(LOOK_RECIPES)) {
    cats.add(recipe.category);
  }
  return [...cats].sort();
}

/**
 * Get all recipes as training examples with reasoning for AI-driven grading.
 * @returns {Array<{key: string, name: string, description: string, category: string, reasoning: string, adjustments: Object, intent: Object, nodeLabel: string, hasMultiNode: boolean}>}
 */
function getTrainingExamples() {
  return Object.entries(LOOK_RECIPES).map(([key, recipe]) => ({
    key,
    name: recipe.name,
    description: recipe.description,
    category: recipe.category,
    reasoning: recipe.reasoning,
    adjustments: recipe.adjustments,
    intent: recipe.intent,
    nodeLabel: recipe.nodeLabel,
    hasMultiNode: !!recipe.multiNode,
  }));
}

module.exports = {
  LOOK_RECIPES,
  NAME_ALIASES,
  findRecipe,
  listRecipes,
  getCategories,
  getTrainingExamples,
};
