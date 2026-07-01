/**
 * Color Grading NLP Parser
 *
 * Natural language parser for color grading instructions.
 * Uses comprehensive glossary and action mappings to interpret
 * cinematographer/colorist directions into DaVinci Resolve parameters.
 *
 * @module drx/color-nlp-parser
 */

const fs = require('fs');
const path = require('path');

// Load action mappings
let ACTION_MAPPINGS = null;
let _customDataPath = null;

/**
 * Set a custom data path for loading action mappings.
 * Call before first parse to point at your app's knowledge directory.
 * @param {string} dataPath - Absolute path to the directory containing color-nlp-action-mappings.json
 */
function setDataPath(dataPath) {
  _customDataPath = dataPath;
  ACTION_MAPPINGS = null; // force reload on next access
}

function loadActionMappings() {
  if (ACTION_MAPPINGS) return ACTION_MAPPINGS;

  // Method 1: require() — works in Vercel serverless bundles and Node.js
  // require() is resolved by bundlers (ncc, webpack) at build time,
  // unlike fs.readFileSync which needs runtime path resolution.
  try {
    ACTION_MAPPINGS = require('./data/color-nlp-action-mappings.json');
    return ACTION_MAPPINGS;
  } catch {
    // Not available as a require-able module
  }

  // Method 2: fs.readFileSync with path search (works in dev/Electron)
  const searchPaths = [
    _customDataPath ? path.join(_customDataPath, 'color-nlp-action-mappings.json') : null,
    path.join(__dirname, 'data', 'color-nlp-action-mappings.json'),
  ].filter(Boolean);

  for (const mappingsPath of searchPaths) {
    try {
      const content = fs.readFileSync(mappingsPath, 'utf8');
      ACTION_MAPPINGS = JSON.parse(content);
      return ACTION_MAPPINGS;
    } catch {
      // try next path
    }
  }

  console.error('[NLP Parser] Failed to load action mappings from any known path');
  return {
    intent_classification: {},
    phrase_to_action: {},
    modifiers: { intensity: {}, scope: {} },
    parameters: {},
    synonyms: {},
    problem_patterns: {},
  };
}

/**
 * Normalize input text for matching
 */
function normalizeText(text) {
  return text
    .toLowerCase()
    .trim()
    .replace(/['']/g, "'")
    .replace(/[""]/g, '"')
    .replace(/\s+/g, ' ')
    .replace(/[.,!?;:]+$/, ''); // Remove trailing punctuation
}

/**
 * Expand synonyms in input text
 */
function expandSynonyms(text, synonyms) {
  let expanded = text;
  for (const [canonical, alternatives] of Object.entries(synonyms)) {
    for (const alt of alternatives) {
      const regex = new RegExp(`\\b${alt}\\b`, 'gi');
      if (regex.test(expanded)) {
        // Don't replace, just note the canonical form
        expanded = expanded.replace(regex, canonical);
      }
    }
  }
  return expanded;
}

/**
 * Classify the intent of the input
 */
function classifyIntent(text, mappings) {
  const normalized = normalizeText(text);
  const intents = mappings.intent_classification;

  const scores = {};

  for (const [intentName, intentData] of Object.entries(intents)) {
    let score = 0;

    // Check keywords
    if (intentData.keywords) {
      for (const keyword of intentData.keywords) {
        if (normalized.includes(keyword.toLowerCase())) {
          score += 2;
        }
      }
    }

    // Check regex patterns
    if (intentData.regex_patterns) {
      for (const pattern of intentData.regex_patterns) {
        try {
          const regex = new RegExp(pattern, 'i');
          if (regex.test(normalized)) {
            score += 5;
          }
        } catch (e) {
          // Invalid regex, skip
        }
      }
    }

    if (score > 0) {
      scores[intentName] = {
        score,
        requires_secondary: intentData.requires_secondary || false,
        is_compound: intentData.is_compound || false,
        primary_tools: intentData.primary_tools || [],
      };
    }
  }

  // Sort by score and return top intent(s)
  const sorted = Object.entries(scores)
    .sort((a, b) => b[1].score - a[1].score);

  if (sorted.length === 0) {
    return { primary: null, all: [] };
  }

  return {
    primary: sorted[0][0],
    primaryData: sorted[0][1],
    all: sorted.map(([name, data]) => ({ name, ...data })),
  };
}

/**
 * Extract intensity modifier from input with emphatic language detection
 */
function extractIntensityModifier(text, mappings) {
  const normalized = normalizeText(text);
  const original = text; // Keep original for caps detection
  const intensityMods = mappings.modifiers?.intensity || {};

  let baseMultiplier = 1.0; // Default to significant (1.0)
  let emphasisBoost = 0;
  let matchedLevel = 'significant';

  // === EMPHATIC LANGUAGE DETECTION ===

  // 1. Check for ALL CAPS words (emphasis indicator)
  const capsWords = original.match(/\b[A-Z]{2,}\b/g) || [];
  const significantCapsWords = capsWords.filter(w =>
    !['A', 'I', 'TV', 'OK', 'HD', 'SDR', 'HDR', 'RGB', 'LOG', 'LUT', 'DCI', 'REC'].includes(w)
  );
  if (significantCapsWords.length > 0) {
    emphasisBoost += 0.2 * significantCapsWords.length;
  }

  // 2. Check for exclamation marks (! = +0.15, !! = +0.3, !!! = +0.5)
  const exclamationCount = (original.match(/!/g) || []).length;
  if (exclamationCount === 1) emphasisBoost += 0.15;
  else if (exclamationCount === 2) emphasisBoost += 0.3;
  else if (exclamationCount >= 3) emphasisBoost += 0.5;

  // 3. Check for repetition patterns ("really really", "way way", "much much", "very very")
  const repetitionPatterns = [
    /\b(really|very|much|way|super|so|extra)\s+\1\b/gi,
    /\b(really|very|much|way|super|so|extra)\s+(really|very|much|way|super|so|extra)\b/gi,
  ];
  for (const pattern of repetitionPatterns) {
    const matches = normalized.match(pattern) || [];
    emphasisBoost += 0.25 * matches.length;
  }

  // 4. Check for stacked intensifiers ("really very", "super extremely", "way too much")
  const stackedPatterns = [
    /\b(really|very|super|extremely|incredibly|insanely)\s+(really|very|super|extremely|incredibly|insanely|much|more)\b/gi,
    /\bway\s+too\s+(much|more|far)\b/gi,
    /\bso\s+(much|very|incredibly)\b/gi,
  ];
  for (const pattern of stackedPatterns) {
    if (pattern.test(normalized)) {
      emphasisBoost += 0.3;
    }
  }

  // 5. Check for intensity amplifier words (cumulative!)
  const intensityAmplifiers = {
    // Tier 1: Mild amplifiers (+0.1 each)
    mild: {
      boost: 0.1,
      words: ['pretty', 'quite', 'fairly', 'rather', 'somewhat', 'kinda', 'sorta', 'more']
    },
    // Tier 2: Moderate amplifiers (+0.15 each)
    moderate: {
      boost: 0.15,
      words: ['very', 'really', 'definitely', 'certainly', 'clearly', 'noticeably', 'visibly', 'obviously', 'actually', 'truly', 'genuinely']
    },
    // Tier 3: Strong amplifiers (+0.2 each)
    strong: {
      boost: 0.2,
      words: ['super', 'extra', 'hella', 'mad', 'wicked', 'damn', 'dang', 'bloody', 'friggin', 'freaking', 'frickin', 'heckin', 'real', 'proper', 'straight up', 'legit', 'lowkey', 'highkey', 'deadass']
    },
    // Tier 4: Very strong amplifiers (+0.25 each)
    very_strong: {
      boost: 0.25,
      words: ['extremely', 'incredibly', 'seriously', 'majorly', 'heavily', 'intensely', 'severely', 'deeply', 'profoundly', 'remarkably', 'exceptionally', 'particularly', 'especially', 'significantly', 'substantially', 'considerably', 'dramatically']
    },
    // Tier 5: Extreme amplifiers (+0.35 each)
    extreme: {
      boost: 0.35,
      words: ['ultra', 'mega', 'hyper', 'uber', 'turbo', 'giga', 'tera', 'maximum', 'max', 'peak', 'ultimate', 'supreme', 'paramount', 'radical', 'drastic', 'severe', 'massive', 'enormous', 'tremendous', 'immense', 'colossal', 'monumental', 'epic']
    },
    // Tier 6: Insane/absurd amplifiers (+0.45 each)
    insane: {
      boost: 0.45,
      words: ['insanely', 'ridiculously', 'absurdly', 'outrageously', 'obscenely', 'ludicrously', 'preposterously', 'stupidly', 'crazy', 'bonkers', 'mental', 'nuts', 'bananas', 'wild', 'savage', 'brutal', 'beastly', 'godly', 'ungodly', 'otherworldly', 'astronomical']
    },
    // Tier 7: Nuclear/max amplifiers (+0.55 each)
    nuclear: {
      boost: 0.55,
      words: ['nuclear', 'atomic', 'thermonuclear', 'apocalyptic', 'cataclysmic', 'earth-shattering', 'mind-blowing', 'face-melting', 'brain-melting', 'soul-crushing', 'maxed', 'cranked', 'slammed', 'pegged', 'pinned', 'redlined', 'balls to the wall', 'full send', 'all out', 'gonzo', 'off the charts', 'through the roof', 'to eleven', 'to the max', 'to the moon']
    }
  };

  // Count all amplifier words (they stack!)
  for (const [tier, data] of Object.entries(intensityAmplifiers)) {
    for (const word of data.words) {
      // Use word boundary matching for accuracy
      const regex = new RegExp(`\\b${word.replace(/\s+/g, '\\s+')}\\b`, 'gi');
      const matches = normalized.match(regex) || [];
      emphasisBoost += data.boost * matches.length;
    }
  }

  // 5b. Check for action/verb intensifiers (+0.3 each)
  const actionIntensifiers = [
    'crank', 'cranked', 'slam', 'slammed', 'blast', 'blasted', 'nuke', 'nuked',
    'crush', 'crushed', 'smash', 'smashed', 'kill', 'killed', 'destroy', 'destroyed',
    'hammer', 'hammered', 'pound', 'pounded', 'pump', 'pumped', 'jack', 'jacked',
    'boost', 'boosted', 'amp', 'amped', 'juice', 'juiced', 'goose', 'goosed',
    'ramp', 'ramped', 'dial', 'dialed', 'push', 'pushed', 'shove', 'shoved',
    'yank', 'yanked', 'rip', 'ripped', 'tear', 'send', 'sent', 'launch', 'launched'
  ];
  for (const word of actionIntensifiers) {
    if (normalized.includes(word)) {
      emphasisBoost += 0.3;
      break; // Only count action verbs once
    }
  }

  // 5c. Check for "all the way" / "as X as possible" patterns
  const maxPatterns = [
    /\ball\s+the\s+way\b/gi,
    /\bas\s+\w+\s+as\s+(?:possible|it\s+(?:can|will)\s+go|you\s+can)\b/gi,
    /\bto\s+the\s+(?:max|limit|extreme|moon|stars)\b/gi,
    /\b(?:full|max|complete|total)\s+(?:blast|power|throttle|strength|force|effect)\b/gi,
    /\b(?:100|hundred)\s*(?:percent|%)\b/gi,
    /\bgive\s+(?:it|me)\s+(?:everything|all\s+(?:of\s+it|you(?:'ve)?\s+got))\b/gi,
    /\bdon'?t\s+hold\s+back\b/gi,
    /\bgo\s+(?:hard|ham|crazy|nuts|wild|all\s+in|all\s+out|big)\b/gi,
    /\blet\s+(?:it|her|'?er)\s+rip\b/gi,
  ];
  for (const pattern of maxPatterns) {
    if (pattern.test(normalized)) {
      emphasisBoost += 0.4;
    }
  }

  // 6. Check for diminutive patterns (reduce intensity)
  const diminutivePatterns = [
    /\bjust\s+a\s+(bit|touch|tad|hair|smidge|little)\b/gi,
    /\bonly\s+(slightly|a\s+bit|a\s+touch)\b/gi,
    /\bhardly\s+any\b/gi,
    /\bbarely\s+(any|noticeable)\b/gi,
  ];
  for (const pattern of diminutivePatterns) {
    if (pattern.test(normalized)) {
      emphasisBoost -= 0.4; // Reduce intensity
    }
  }

  // === FIND BASE INTENSITY FROM MAPPINGS ===

  // Sort by multiplier descending so we match strongest first
  const sortedIntensities = Object.entries(intensityMods)
    .sort((a, b) => (b[1].multiplier || 0) - (a[1].multiplier || 0));

  for (const [level, data] of sortedIntensities) {
    // Check the level name itself
    if (normalized.includes(level)) {
      baseMultiplier = data.multiplier;
      matchedLevel = level;
      break;
    }
    // Check synonyms
    if (data.synonyms) {
      let found = false;
      for (const syn of data.synonyms) {
        if (normalized.includes(syn.toLowerCase())) {
          baseMultiplier = data.multiplier;
          matchedLevel = level;
          found = true;
          break;
        }
      }
      if (found) break;
    }
  }

  // === COMBINE BASE + EMPHASIS ===

  let finalMultiplier = baseMultiplier + emphasisBoost;

  // Clamp to reasonable range (0.1 to 2.5)
  finalMultiplier = Math.max(0.1, Math.min(2.5, finalMultiplier));

  // Determine effective level based on final multiplier
  let effectiveLevel = matchedLevel;
  if (emphasisBoost > 0) {
    if (finalMultiplier >= 2.0) effectiveLevel = 'nuclear';
    else if (finalMultiplier >= 1.75) effectiveLevel = 'massive';
    else if (finalMultiplier >= 1.5) effectiveLevel = 'extreme';
    else if (finalMultiplier >= 1.35) effectiveLevel = 'heavy';
    else if (finalMultiplier >= 1.2) effectiveLevel = 'bold';
  } else if (emphasisBoost < 0) {
    if (finalMultiplier <= 0.3) effectiveLevel = 'very_subtle';
    else if (finalMultiplier <= 0.5) effectiveLevel = 'subtle';
  }

  return {
    level: effectiveLevel,
    baseLevel: matchedLevel,
    multiplier: finalMultiplier,
    emphasisBoost,
    emphasisDetected: emphasisBoost !== 0,
  };
}

/**
 * Extract scope modifier from input
 */
function extractScopeModifier(text, mappings) {
  const normalized = normalizeText(text);
  const scopeMods = mappings.modifiers?.scope || {};

  for (const [scopeName, data] of Object.entries(scopeMods)) {
    // Check synonyms
    if (data.synonyms) {
      for (const syn of data.synonyms) {
        if (normalized.includes(syn.toLowerCase())) {
          return {
            scope: scopeName,
            target_range: data.target_range || null,
            requires_secondary: data.requires_secondary || false,
          };
        }
      }
    }
  }

  // Default to global
  return { scope: 'global', target_range: null, requires_secondary: false };
}

/**
 * Find best matching phrase action
 * Checks both phrase_to_action and compound_adjustments
 */
function findPhraseMatch(text, mappings) {
  const normalized = normalizeText(text);

  // Combine phrase_to_action and compound_adjustments into one lookup
  const phrases = mappings.phrase_to_action || {};
  const compounds = mappings.compound_adjustments || {};

  // Convert compound_adjustments to same format as phrase_to_action
  const allPhrases = { ...phrases };
  for (const [phrase, data] of Object.entries(compounds)) {
    if (!allPhrases[phrase]) {
      allPhrases[phrase] = {
        intent: data.intent || 'style',
        is_compound: true,
        actions: data.actions || [],
      };
    }
  }

  let bestMatch = null;
  let bestScore = 0;

  for (const [phrase, actionData] of Object.entries(allPhrases)) {
    const normalizedPhrase = normalizeText(phrase);

    // Exact match
    if (normalized === normalizedPhrase) {
      return { phrase, score: 100, exact: true, ...actionData };
    }

    // Contains match (phrase is in input)
    if (normalized.includes(normalizedPhrase)) {
      const score = (normalizedPhrase.length / normalized.length) * 80;
      if (score > bestScore) {
        bestScore = score;
        bestMatch = { phrase, score, exact: false, ...actionData };
      }
    }

    // Input contains phrase (for "make it look like X" patterns)
    if (normalizedPhrase.length >= 3 && normalized.includes(normalizedPhrase)) {
      const score = Math.min(90, normalizedPhrase.length * 5);
      if (score > bestScore) {
        bestScore = score;
        bestMatch = { phrase, score, exact: false, ...actionData };
      }
    }

    // Word overlap match
    const phraseWords = normalizedPhrase.split(' ');
    const inputWords = normalized.split(' ');
    const overlap = phraseWords.filter(w => inputWords.includes(w)).length;
    const overlapScore = (overlap / phraseWords.length) * 60;

    if (overlapScore > bestScore && overlap >= 2) {
      bestScore = overlapScore;
      bestMatch = { phrase, score: overlapScore, exact: false, ...actionData };
    }
  }

  return bestMatch;
}

/**
 * Detect problem patterns in input
 */
function detectProblemPattern(text, mappings) {
  const normalized = normalizeText(text);
  const patterns = mappings.problem_patterns || {};

  for (const [problemName, data] of Object.entries(patterns)) {
    if (data.indicators) {
      for (const indicator of data.indicators) {
        if (normalized.includes(indicator.toLowerCase())) {
          return {
            problem: problemName,
            fix: data.fix,
          };
        }
      }
    }
  }

  return null;
}

/**
 * Parse color terms from input
 */
function parseColorTerms(text, mappings) {
  const normalized = normalizeText(text);
  const colorTerms = mappings.color_terms || {};
  const found = [];

  for (const [category, terms] of Object.entries(colorTerms)) {
    for (const term of terms) {
      if (normalized.includes(term.toLowerCase())) {
        found.push({ term, category });
      }
    }
  }

  return found;
}

/**
 * Convert parsed result to interpreter-compatible format
 */
function toInterpreterFormat(parseResult) {
  const params = {
    temperature: 0,
    tint: 0,
    contrast: 0,
    saturation: 0,
    exposure: 0,
    shadowLift: 0,
    highlightCompression: 0,
    midtoneDetail: 0,
    pivot: 0.435,
    explanation: '',
  };

  if (!parseResult.actions || parseResult.actions.length === 0) {
    params.explanation = 'No actions matched';
    return params;
  }

  const multiplier = parseResult.intensity?.multiplier || 1.0;
  const explanations = [];

  for (const action of parseResult.actions) {
    const param = action.parameter;
    const amount = (action.default_amount || 0) * multiplier;

    // Map Resolve parameters to our simplified format
    if (param.includes('temp')) {
      // Temperature is in Kelvin-like units, convert to our -1 to 1 range
      params.temperature = (amount / 1000) * (action.operation === 'decrease' ? -1 : 1);
      explanations.push(`temperature ${action.operation}`);
    } else if (param.includes('tint')) {
      params.tint = (amount / 50) * (action.operation === 'decrease' ? -1 : 1);
      explanations.push(`tint ${action.operation}`);
    } else if (param.includes('contrast')) {
      // TUNED: Production contrast multipliers average 1.18 (delta 0.18)
      // Changed from /50 to /60 for more subtle, production-like adjustments
      params.contrast = (amount / 60) * (action.operation === 'decrease' ? -1 : 1);
      explanations.push(`contrast ${action.operation}`);
    } else if (param.includes('saturation')) {
      if (action.operation === 'set') {
        params.saturation = (action.value - 50) / 50; // Convert 0-100 to -1 to 1
      } else {
        // TUNED: Production analysis shows 95th percentile saturation boost is 0.48 (1.48x)
        // Changed from /25 to /35 for more natural, production-like adjustments
        params.saturation = (amount / 35) * (action.operation === 'decrease' ? -1 : 1);
      }
      explanations.push(`saturation ${action.operation}`);
    } else if (param.includes('offset.y') || param.includes('gamma.y') ||
               (param.includes('offset') && !param.includes('.r') && !param.includes('.g') && !param.includes('.b'))) {
      params.exposure += amount * (action.operation === 'decrease' ? -1 : 1);
      explanations.push(`exposure ${action.operation}`);
    } else if (param.includes('lift.y')) {
      params.shadowLift = amount * (action.operation === 'decrease' ? -1 : 1);
      explanations.push(`shadows ${action.operation}`);
    } else if (param.includes('gain.y')) {
      // Highlight adjustment via gain
      if (action.operation === 'decrease') {
        params.highlightCompression = Math.abs(amount);
      }
      explanations.push(`highlights ${action.operation}`);
    } else if (param.includes('md')) {
      params.midtoneDetail = (amount / 50) * (action.operation === 'decrease' ? -1 : 1);
      explanations.push(`detail ${action.operation}`);
    } else if (param.includes('color_boost')) {
      // Color boost acts like saturation but preserves skin tones
      // TUNED: Reduced from /50 to /70 to stay within production 95th percentile
      params.saturation = (amount / 70) * (action.operation === 'decrease' ? -1 : 1);
      explanations.push(`color boost ${action.operation}`);
    } else if (param.includes('lift.r') || param.includes('lift.b') ||
               param.includes('gain.r') || param.includes('gain.b')) {
      // Color balance via wheels - convert to temperature/tint approximation
      if (param.includes('.r') && param.includes('gain')) {
        params.temperature += amount * 0.5 * (action.operation === 'decrease' ? -1 : 1);
      }
      if (param.includes('.b') && param.includes('lift')) {
        params.temperature -= amount * 0.5 * (action.operation === 'decrease' ? -1 : 1);
      }
      explanations.push(`color balance adjusted`);
    }
  }

  params.explanation = `NLP: ${parseResult.phrase || parseResult.intent} (${explanations.join(', ')})`;

  // Clamp all values to valid ranges
  params.temperature = Math.max(-1, Math.min(1, params.temperature));
  params.tint = Math.max(-1, Math.min(1, params.tint));
  params.contrast = Math.max(-1, Math.min(1, params.contrast));
  params.saturation = Math.max(-1, Math.min(1, params.saturation));
  params.exposure = Math.max(-1, Math.min(1, params.exposure));
  params.shadowLift = Math.max(-1, Math.min(1, params.shadowLift));
  params.highlightCompression = Math.max(0, Math.min(1, params.highlightCompression));
  params.midtoneDetail = Math.max(-1, Math.min(1, params.midtoneDetail));

  return params;
}

/**
 * Main parse function
 *
 * @param {string} input - Natural language color grading instruction
 * @returns {Object} - Parsed result with intent, actions, modifiers
 */
/**
 * Build fallback actions from intent when no phrase matches.
 * Uses the intent's primary_tools and keyword direction to generate
 * reasonable default adjustments for single-word inputs.
 */
function buildFallbackActions(normalized, intentName, intentData, mappings) {
  const actions = [];

  // Determine direction from common keywords
  const decreaseWords = /\b(less|reduce|remove|lower|cooler|colder|desaturate|flatten|softer|darker|dimmer|muted|dull|subtract)\b/;
  const increaseWords = /\b(more|add|boost|increase|warmer|hotter|saturate|punch|brighter|lighter|vivid|rich|crispy|sharper)\b/;
  const isDecrease = decreaseWords.test(normalized);
  const isIncrease = increaseWords.test(normalized) || !isDecrease; // default to increase

  const operation = isDecrease ? 'decrease' : 'increase';

  // Default amounts per tool type (moderate adjustments)
  const defaultAmounts = {
    temp: 600,
    tint: 15,
    contrast: 12,
    saturation: 15,
    color_boost: 15,
    md: 20,
    shadows: 10,
    highlights: 10,
    exposure: 0.15,
    lift: 0.03,
    gamma: 0.02,
    gain: 0.05,
    offset: 0.02,
  };

  // Map intent primary_tools to parameter names and generate actions
  for (const tool of intentData.primary_tools) {
    // Only use the most relevant tool for single-word inputs
    // For "warmer" → temp, for "contrast" → contrast, etc.
    const toolLower = tool.toLowerCase();

    // Check if the normalized input relates to this specific tool
    const toolRelevant =
      (toolLower.includes('temp') && /\b(warm|cool|cold|hot|golden|amber|orange|blue|ice|icy|tungsten|daylight|kelvin|temperature)\b/.test(normalized)) ||
      (toolLower.includes('tint') && /\b(tint|green|magenta|pink)\b/.test(normalized)) ||
      (toolLower.includes('contrast') && /\b(contrast|punch|punchy|flat|flatten|crispy|pop)\b/.test(normalized)) ||
      (toolLower.includes('saturation') && /\b(saturat|desat|vivid|muted|dull|rich|vibran|color)\b/.test(normalized)) ||
      (toolLower.includes('color_boost') && /\b(vibran|boost|color)\b/.test(normalized)) ||
      (toolLower.includes('md') && /\b(detail|sharp|soft|clarity|texture)\b/.test(normalized)) ||
      (toolLower.includes('exposure') || toolLower.includes('offset') || toolLower.includes('gamma')) &&
        /\b(bright|dark|light|dim|expose|level)\b/.test(normalized);

    if (toolRelevant) {
      // Find the best matching default amount
      let amount = 10; // generic fallback
      for (const [key, val] of Object.entries(defaultAmounts)) {
        if (toolLower.includes(key)) {
          amount = val;
          break;
        }
      }

      actions.push({
        parameter: `primaries.${tool}`,
        operation,
        default_amount: amount,
      });
      break; // Only one primary action for single-word inputs
    }
  }

  // If no specific tool matched but we have an intent, use the first primary tool
  if (actions.length === 0 && intentData.primary_tools.length > 0) {
    const firstTool = intentData.primary_tools[0];
    let amount = 10;
    for (const [key, val] of Object.entries(defaultAmounts)) {
      if (firstTool.toLowerCase().includes(key)) {
        amount = val;
        break;
      }
    }
    actions.push({
      parameter: `primaries.${firstTool}`,
      operation,
      default_amount: amount,
    });
  }

  return actions;
}

function parse(input) {
  const mappings = loadActionMappings();
  const normalized = normalizeText(input);

  // 1. Classify intent
  const intent = classifyIntent(normalized, mappings);

  // 2. Find phrase match
  const phraseMatch = findPhraseMatch(normalized, mappings);

  // 3. Extract modifiers
  const intensity = extractIntensityModifier(normalized, mappings);
  const scope = extractScopeModifier(normalized, mappings);

  // 4. Detect problem patterns
  const problem = detectProblemPattern(normalized, mappings);

  // 5. Parse color terms
  const colorTerms = parseColorTerms(normalized, mappings);

  // 6. Build result
  const result = {
    input,
    normalized,
    intent: intent.primary,
    intentData: intent.primaryData,
    allIntents: intent.all,
    phrase: phraseMatch?.phrase || null,
    phraseScore: phraseMatch?.score || 0,
    actions: phraseMatch?.actions || [],
    workflow: phraseMatch?.workflow || null,
    intensity,
    scope,
    problem,
    colorTerms,
    requires_secondary: phraseMatch?.requires_secondary || scope.requires_secondary || false,
    is_compound: phraseMatch?.is_compound || false,
    side_effects: phraseMatch?.side_effects || [],
    alternatives: phraseMatch?.alternatives || [],
  };

  // If we have a problem pattern but no phrase match, use the problem fix
  if (problem && !phraseMatch) {
    result.actions = [problem.fix];
    result.phrase = `fix: ${problem.problem}`;
  }

  // Intent-based fallback: when intent is detected but no phrase matched,
  // generate default actions from the intent's primary tools and keywords.
  // This handles single-word inputs like "warmer", "contrast", "desaturate"
  // that don't match any full phrase in the phrase_to_action dictionary.
  if (result.intent && result.actions.length === 0 && !problem) {
    const intentData = mappings.intent_classification?.[result.intent];
    if (intentData?.primary_tools) {
      const fallbackActions = buildFallbackActions(normalized, result.intent, intentData, mappings);
      if (fallbackActions.length > 0) {
        result.actions = fallbackActions;
        result.phrase = `intent-fallback: ${result.intent}`;
      }
    }
  }

  return result;
}

/**
 * Parse and convert to interpreter format
 *
 * @param {string} input - Natural language input
 * @returns {Object} - Parameters compatible with cinematographer-interpreter
 */
function parseToParams(input) {
  const parseResult = parse(input);
  return toInterpreterFormat(parseResult);
}

/**
 * Get available actions for an intent
 */
function getActionsForIntent(intentName) {
  const mappings = loadActionMappings();
  const phrases = mappings.phrase_to_action || {};

  return Object.entries(phrases)
    .filter(([_, data]) => data.intent === intentName)
    .map(([phrase, data]) => ({ phrase, ...data }));
}

/**
 * Get all available intents
 */
function getAvailableIntents() {
  const mappings = loadActionMappings();
  return Object.keys(mappings.intent_classification || {});
}

/**
 * Get parameter info
 */
function getParameterInfo(paramPath) {
  const mappings = loadActionMappings();
  return mappings.parameters?.[paramPath] || null;
}

/**
 * Suggest completions for partial input
 */
function suggestCompletions(partialInput, limit = 5) {
  const mappings = loadActionMappings();
  const normalized = normalizeText(partialInput);
  const phrases = Object.keys(mappings.phrase_to_action || {});

  const suggestions = phrases
    .filter(phrase => {
      const normPhrase = normalizeText(phrase);
      return normPhrase.includes(normalized) ||
             normalized.split(' ').some(word => normPhrase.includes(word));
    })
    .slice(0, limit);

  return suggestions;
}

module.exports = {
  parse,
  parseToParams,
  classifyIntent,
  findPhraseMatch,
  extractIntensityModifier,
  extractScopeModifier,
  detectProblemPattern,
  parseColorTerms,
  toInterpreterFormat,
  getActionsForIntent,
  getAvailableIntents,
  getParameterInfo,
  suggestCompletions,
  normalizeText,
  expandSynonyms,
  loadActionMappings,
  setDataPath,
};
