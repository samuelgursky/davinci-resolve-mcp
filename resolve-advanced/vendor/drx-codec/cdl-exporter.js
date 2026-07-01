/**
 * CDL Exporter - ASC Color Decision List Generation
 *
 * Generates CDL (ASC Color Decision List) files from grade parameters.
 * CDL is an industry-standard format for exchanging color correction data
 * between different color grading systems and software.
 *
 * CDL Format Reference:
 * - Slope: Multiplier applied to each color channel (equivalent to Gain in DaVinci Resolve)
 * - Offset: Value added to each color channel after slope
 * - Power: Exponent applied to each channel (inverse of Gamma: power = 1/gamma for non-zero gamma)
 * - Saturation: Global saturation multiplier
 *
 * Supports both CDL and CCC (Color Correction Collection) formats.
 *
 * @module drx/cdl-exporter
 */

/**
 * Default CDL values (neutral grade)
 */
const CDL_DEFAULTS = {
  slope: { r: 1.0, g: 1.0, b: 1.0 },
  offset: { r: 0.0, g: 0.0, b: 0.0 },
  power: { r: 1.0, g: 1.0, b: 1.0 },
  saturation: 1.0,
};

/**
 * Convert DRX/Resolve parameters to CDL SOP+Sat values
 *
 * Mapping from Resolve to CDL:
 * - Gain R/G/B/Master -> Slope R/G/B (multiplied by master)
 * - Offset R/G/B -> Offset R/G/B (may need scaling depending on application)
 * - Gamma R/G/B -> Power R/G/B (inverse relationship for gamma values around 1.0)
 * - Saturation -> Saturation
 *
 * Note: Lift in Resolve doesn't have a direct CDL equivalent. It affects
 * shadows and is partially captured by Offset, but the mapping is imperfect.
 *
 * @param {Object} params - DRX/Resolve grade parameters
 * @returns {Object} - CDL SOP+Sat values
 */
function drxToCDL(params) {
  if (!params) {
    return { ...CDL_DEFAULTS };
  }

  const cdl = {
    slope: { r: 1.0, g: 1.0, b: 1.0 },
    offset: { r: 0.0, g: 0.0, b: 0.0 },
    power: { r: 1.0, g: 1.0, b: 1.0 },
    saturation: 1.0,
  };

  // Gain -> Slope
  // Gain in Resolve is a multiplier, same as Slope in CDL
  if (params.gain) {
    const gainMaster = params.gain.master ?? 1.0;
    cdl.slope.r = (params.gain.r ?? 1.0) * gainMaster;
    cdl.slope.g = (params.gain.g ?? 1.0) * gainMaster;
    cdl.slope.b = (params.gain.b ?? 1.0) * gainMaster;
  }

  // Offset -> Offset
  // Resolve's offset is similar to CDL offset
  // Note: Resolve's lift also contributes to shadow adjustments but isn't directly mappable
  if (params.offset) {
    cdl.offset.r = params.offset.r ?? 0.0;
    cdl.offset.g = params.offset.g ?? 0.0;
    cdl.offset.b = params.offset.b ?? 0.0;
  }

  // Include lift contribution to offset (approximate mapping)
  // Lift primarily affects shadows but adds a baseline offset
  if (params.lift) {
    const liftMaster = params.lift.master ?? 0.0;
    cdl.offset.r += (params.lift.r ?? 0.0) + liftMaster;
    cdl.offset.g += (params.lift.g ?? 0.0) + liftMaster;
    cdl.offset.b += (params.lift.b ?? 0.0) + liftMaster;
  }

  // Gamma -> Power (inverse relationship)
  // In CDL: output = (input * slope + offset) ^ power
  // In Resolve: gamma adjusts midtones, where gamma > 0 lightens and gamma < 0 darkens
  // The relationship is: power = 1 / (1 + gamma) for small gamma values around 0
  // For gamma values in Resolve centered around 0, power = 1/(1+gamma)
  if (params.gamma) {
    const gammaMaster = params.gamma.master ?? 0.0;
    // Convert Resolve gamma (centered at 0) to CDL power (centered at 1)
    // gamma > 0 -> power < 1 (lightens midtones)
    // gamma < 0 -> power > 1 (darkens midtones)
    cdl.power.r = gammaToPower((params.gamma.r ?? 0.0) + gammaMaster);
    cdl.power.g = gammaToPower((params.gamma.g ?? 0.0) + gammaMaster);
    cdl.power.b = gammaToPower((params.gamma.b ?? 0.0) + gammaMaster);
  }

  // Saturation -> Saturation
  // Resolve Primaries: 0-100, unity=50. CDL: multiplier, unity=1.0.
  // Convert: CDL = Resolve / 50
  if (params.saturation !== undefined) {
    cdl.saturation = params.saturation / 50;
  }

  return cdl;
}

/**
 * Convert Resolve gamma value to CDL power
 *
 * Resolve gamma is centered at 0 (neutral), positive values lighten midtones
 * CDL power is centered at 1 (neutral), values < 1 lighten, values > 1 darken
 *
 * @param {number} gamma - Resolve gamma value (typically -1 to 1)
 * @returns {number} - CDL power value
 */
function gammaToPower(gamma) {
  // Clamp gamma to avoid division by zero or negative power
  const clampedGamma = Math.max(-0.99, Math.min(0.99, gamma));
  // power = 1 / (1 + gamma)
  return 1.0 / (1.0 + clampedGamma);
}

/**
 * Convert CDL power to Resolve gamma value
 *
 * @param {number} power - CDL power value
 * @returns {number} - Resolve gamma value
 */
function powerToGamma(power) {
  // gamma = (1 / power) - 1
  if (power <= 0) return 0;
  return (1.0 / power) - 1.0;
}

/**
 * Generate a single CDL XML ColorCorrection element
 *
 * @param {Object} cdlValues - CDL SOP+Sat values from drxToCDL()
 * @param {Object} options - Generation options
 * @param {string} options.id - Correction ID (e.g., "shot_001")
 * @param {string} options.description - Optional description
 * @returns {string} - CDL XML ColorCorrection element
 */
function generateColorCorrection(cdlValues, options = {}) {
  const {
    id = 'correction_001',
    description = '',
  } = options;

  const cdl = cdlValues || CDL_DEFAULTS;

  // Format numbers to 6 decimal places for precision
  const fmt = (n) => n.toFixed(6);

  const slopeStr = `${fmt(cdl.slope.r)} ${fmt(cdl.slope.g)} ${fmt(cdl.slope.b)}`;
  const offsetStr = `${fmt(cdl.offset.r)} ${fmt(cdl.offset.g)} ${fmt(cdl.offset.b)}`;
  const powerStr = `${fmt(cdl.power.r)} ${fmt(cdl.power.g)} ${fmt(cdl.power.b)}`;
  const satStr = fmt(cdl.saturation);

  let xml = `    <ColorCorrection id="${escapeXml(id)}">`;

  if (description) {
    xml += `\n      <Description>${escapeXml(description)}</Description>`;
  }

  xml += `
      <SOPNode>
        <Slope>${slopeStr}</Slope>
        <Offset>${offsetStr}</Offset>
        <Power>${powerStr}</Power>
      </SOPNode>
      <SatNode>
        <Saturation>${satStr}</Saturation>
      </SatNode>
    </ColorCorrection>`;

  return xml;
}

/**
 * Generate a complete CDL file from grade parameters
 *
 * @param {Object} params - DRX/Resolve grade parameters
 * @param {Object} options - Generation options
 * @param {string} options.id - Correction ID
 * @param {string} options.description - Description
 * @param {string} options.inputDescription - Input color space description
 * @param {string} options.viewingDescription - Viewing color space description
 * @returns {string} - Complete CDL XML file content
 */
function generateCDL(params, options = {}) {
  const {
    id = 'grade_001',
    description = '',
    inputDescription = '',
    viewingDescription = '',
  } = options;

  const cdlValues = drxToCDL(params);
  const colorCorrection = generateColorCorrection(cdlValues, { id, description });

  let xml = `<?xml version="1.0" encoding="UTF-8"?>
<ColorDecisionList xmlns="urn:ASC:CDL:v1.2">`;

  if (inputDescription) {
    xml += `\n  <InputDescription>${escapeXml(inputDescription)}</InputDescription>`;
  }

  if (viewingDescription) {
    xml += `\n  <ViewingDescription>${escapeXml(viewingDescription)}</ViewingDescription>`;
  }

  xml += `
  <ColorDecision>
${colorCorrection}
  </ColorDecision>
</ColorDecisionList>
`;

  return xml;
}

/**
 * Generate a CCC (Color Correction Collection) file with multiple corrections
 *
 * @param {Array} corrections - Array of { params, id, description } objects
 * @param {Object} options - Generation options
 * @param {string} options.inputDescription - Input color space description
 * @param {string} options.viewingDescription - Viewing color space description
 * @returns {string} - Complete CCC XML file content
 */
function generateCCC(corrections, options = {}) {
  const {
    inputDescription = '',
    viewingDescription = '',
  } = options;

  const colorCorrectionElements = corrections.map((corr, index) => {
    const cdlValues = drxToCDL(corr.params);
    return generateColorCorrection(cdlValues, {
      id: corr.id || `correction_${String(index + 1).padStart(3, '0')}`,
      description: corr.description || '',
    });
  });

  let xml = `<?xml version="1.0" encoding="UTF-8"?>
<ColorCorrectionCollection xmlns="urn:ASC:CDL:v1.2">`;

  if (inputDescription) {
    xml += `\n  <InputDescription>${escapeXml(inputDescription)}</InputDescription>`;
  }

  if (viewingDescription) {
    xml += `\n  <ViewingDescription>${escapeXml(viewingDescription)}</ViewingDescription>`;
  }

  for (const cc of colorCorrectionElements) {
    xml += `\n${cc}`;
  }

  xml += `
</ColorCorrectionCollection>
`;

  return xml;
}

/**
 * Generate CDL from a version in the VersionStore
 *
 * @param {Object} version - Version object from VersionStore
 * @param {Object} options - Generation options
 * @param {string} options.clipName - Clip name for ID generation
 * @returns {string} - CDL XML content
 */
function generateCDLFromVersion(version, options = {}) {
  const {
    clipName = 'clip',
  } = options;

  // Generate ID from clip name and version number
  const id = `${sanitizeId(clipName)}_v${version.number.replace(/\./g, '_')}`;

  return generateCDL(version.params, {
    id,
    description: version.description || version.label || `Version ${version.number}`,
  });
}

/**
 * Generate a CCC collection from multiple versions
 *
 * @param {Array} versions - Array of version objects from VersionStore
 * @param {Object} options - Generation options
 * @param {string} options.clipName - Clip name for ID generation
 * @returns {string} - CCC XML content
 */
function generateCCCFromVersions(versions, options = {}) {
  const {
    clipName = 'clip',
  } = options;

  const corrections = versions.map(version => ({
    params: version.params,
    id: `${sanitizeId(clipName)}_v${version.number.replace(/\./g, '_')}`,
    description: version.description || version.label || `Version ${version.number}`,
  }));

  return generateCCC(corrections, options);
}

/**
 * Parse a CDL file and extract SOP+Sat values
 *
 * @param {string} cdlContent - CDL XML content
 * @returns {Array} - Array of { id, cdlValues } objects
 */
function parseCDL(cdlContent) {
  const results = [];

  // Simple XML parsing for CDL (avoid external dependencies)
  const correctionRegex = /<ColorCorrection\s+id="([^"]+)">([\s\S]*?)<\/ColorCorrection>/gi;
  let match;

  while ((match = correctionRegex.exec(cdlContent)) !== null) {
    const id = match[1];
    const content = match[2];

    const cdlValues = {
      slope: { r: 1.0, g: 1.0, b: 1.0 },
      offset: { r: 0.0, g: 0.0, b: 0.0 },
      power: { r: 1.0, g: 1.0, b: 1.0 },
      saturation: 1.0,
    };

    // Extract Slope
    const slopeMatch = content.match(/<Slope>([^<]+)<\/Slope>/i);
    if (slopeMatch) {
      const [r, g, b] = slopeMatch[1].trim().split(/\s+/).map(parseFloat);
      if (!isNaN(r)) cdlValues.slope.r = r;
      if (!isNaN(g)) cdlValues.slope.g = g;
      if (!isNaN(b)) cdlValues.slope.b = b;
    }

    // Extract Offset
    const offsetMatch = content.match(/<Offset>([^<]+)<\/Offset>/i);
    if (offsetMatch) {
      const [r, g, b] = offsetMatch[1].trim().split(/\s+/).map(parseFloat);
      if (!isNaN(r)) cdlValues.offset.r = r;
      if (!isNaN(g)) cdlValues.offset.g = g;
      if (!isNaN(b)) cdlValues.offset.b = b;
    }

    // Extract Power
    const powerMatch = content.match(/<Power>([^<]+)<\/Power>/i);
    if (powerMatch) {
      const [r, g, b] = powerMatch[1].trim().split(/\s+/).map(parseFloat);
      if (!isNaN(r)) cdlValues.power.r = r;
      if (!isNaN(g)) cdlValues.power.g = g;
      if (!isNaN(b)) cdlValues.power.b = b;
    }

    // Extract Saturation
    const satMatch = content.match(/<Saturation>([^<]+)<\/Saturation>/i);
    if (satMatch) {
      const sat = parseFloat(satMatch[1].trim());
      if (!isNaN(sat)) cdlValues.saturation = sat;
    }

    results.push({ id, cdlValues });
  }

  return results;
}

/**
 * Convert CDL values back to DRX/Resolve parameters
 *
 * @param {Object} cdlValues - CDL SOP+Sat values
 * @returns {Object} - DRX/Resolve grade parameters
 */
function cdlToDRX(cdlValues) {
  if (!cdlValues) {
    return {
      gain: { r: 1, g: 1, b: 1, master: 1 },
      offset: { r: 0, g: 0, b: 0 },
      gamma: { r: 0, g: 0, b: 0, master: 0 },
      saturation: 50,  // Resolve Primaries unity
    };
  }

  // CDL saturation: 0-2 range, 1.0 unity
  // Resolve Primaries saturation: 0-100, 50 unity
  const cdlSat = cdlValues.saturation ?? 1.0;
  const resolveSat = cdlSat * 50;  // CDL 1.0 -> Resolve 50

  const params = {
    gain: {
      r: cdlValues.slope?.r ?? 1.0,
      g: cdlValues.slope?.g ?? 1.0,
      b: cdlValues.slope?.b ?? 1.0,
      master: 1.0,
    },
    offset: {
      r: cdlValues.offset?.r ?? 0.0,
      g: cdlValues.offset?.g ?? 0.0,
      b: cdlValues.offset?.b ?? 0.0,
    },
    gamma: {
      r: powerToGamma(cdlValues.power?.r ?? 1.0),
      g: powerToGamma(cdlValues.power?.g ?? 1.0),
      b: powerToGamma(cdlValues.power?.b ?? 1.0),
      master: 0.0,
    },
    saturation: resolveSat,
    lift: { r: 0, g: 0, b: 0, master: 0 },
  };

  return params;
}

/**
 * Escape XML special characters
 * @private
 */
function escapeXml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

/**
 * Sanitize a string to be used as an XML ID
 * @private
 */
function sanitizeId(str) {
  if (!str) return 'unknown';
  return String(str)
    .replace(/[^a-zA-Z0-9_-]/g, '_')
    .replace(/^[^a-zA-Z_]/, '_')
    .substring(0, 64);
}

module.exports = {
  // Main generation functions
  generateCDL,
  generateCCC,
  generateColorCorrection,

  // Version-aware generation
  generateCDLFromVersion,
  generateCCCFromVersions,

  // Conversion utilities
  drxToCDL,
  cdlToDRX,
  gammaToPower,
  powerToGamma,

  // Parsing
  parseCDL,

  // Constants
  CDL_DEFAULTS,
};
