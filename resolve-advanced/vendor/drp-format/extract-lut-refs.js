/**
 * DRP project-level LUT reference extraction (P5.2).
 *
 * Surfaces LUT paths the project.xml carries. Resolve stores LUTs in
 * named slots (InputLUT, OutputLUT, TimelineLUT, MonitorLUT, etc).
 * Each slot is a single path string pointing to a .cube/.clf/.dctl/etc.
 *
 * Schema-agnostic: walks a whitelisted set of recognized slot tags and
 * surfaces whatever paths it finds. If a real Resolve fixture surfaces a
 * different slot tag, add it to RECOGNIZED_SLOTS.
 *
 * Does NOT depend on drp-validator (which has a known broken
 * `../utils/safe-archive` require). This module reads project.xml
 * directly via JSZip, mirroring the pattern used by diff.js and
 * inject-grades.js.
 *
 * @module drp-format/extract-lut-refs
 */

const fs = require('node:fs/promises');
const JSZip = require('jszip');

// Project-XML tags that historically hold a LUT path. Update as fixtures
// surface new names. Documented mapping:
//   InputLUT         — applied before the timeline pipeline (IDT-like)
//   OutputLUT        — applied at the end of the timeline pipeline
//   TimelineLUT      — applied at timeline scope (look LUT, often a CDL)
//   MonitorLUT       — preview-only, not baked into renders
const RECOGNIZED_SLOTS = [
  'InputLUT',
  'OutputLUT',
  'TimelineLUT',
  'MonitorLUT',
  // Newer Resolve releases use DRT (Display Rendering Transform) — keep
  // alongside the LUT names so both surface in the same call.
  'InputDRT',
  'OutputDRT',
];

// Color-space tags that callers may want as "claimed spaces" alongside
// the LUT path. The pipeline implies the LUT maps input→timeline or
// timeline→output, so these are useful provenance.
const COLOR_SPACE_TAGS = [
  'InputColorSpace',
  'TimelineColorSpace',
  'OutputColorSpace',
  'InputGamma',
  'OutputGamma',
];

function extractScalar(xml, tag) {
  const re = new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`);
  const m = xml.match(re);
  return m ? m[1].trim() : null;
}

function findProjectXmlEntry(zip) {
  let found = null;
  zip.forEach((p, e) => {
    if (!e.dir && /(^|\/)project\.xml$/.test(p)) found = p;
  });
  return found;
}

function extractClaimedSpaces(projectXml) {
  const spaces = {};
  for (const tag of COLOR_SPACE_TAGS) {
    const v = extractScalar(projectXml, tag);
    if (v !== null && v !== '') spaces[tag] = v;
  }
  return spaces;
}

/**
 * Extract project-level LUT references from a DRP.
 *
 * @param {string|Buffer} drpPathOrBuffer
 * @returns {Promise<Array<{slot, path, claimedSpaces}>>}
 *   One entry per LUT slot that has a non-empty value. Each entry
 *   includes the claimedSpaces lifted from the project.xml so callers
 *   (e.g. clf-lut-provenance-checks) have the full pipeline context.
 */
async function extractProjectLUTRefs(drpPathOrBuffer) {
  let buf;
  if (Buffer.isBuffer(drpPathOrBuffer)) {
    buf = drpPathOrBuffer;
  } else if (typeof drpPathOrBuffer === 'string') {
    buf = await fs.readFile(drpPathOrBuffer);
  } else {
    throw new TypeError(
      'extractProjectLUTRefs: first arg must be a string path or a Buffer',
    );
  }

  const zip = await JSZip.loadAsync(buf);
  const projEntry = findProjectXmlEntry(zip);
  if (!projEntry) {
    // DRT or other archive layouts — no project.xml, no LUTs to surface.
    return [];
  }

  const projectXml = await zip.file(projEntry).async('string');
  const claimedSpaces = extractClaimedSpaces(projectXml);

  const refs = [];
  for (const slot of RECOGNIZED_SLOTS) {
    const path = extractScalar(projectXml, slot);
    if (path !== null && path !== '') {
      refs.push({ slot, path, claimedSpaces });
    }
  }
  return refs;
}

module.exports = {
  extractProjectLUTRefs,
  RECOGNIZED_SLOTS,
  COLOR_SPACE_TAGS,
};
