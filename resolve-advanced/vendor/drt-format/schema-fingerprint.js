/**
 * Schema fingerprinting — the tool that POPULATES the capability map.
 *
 * A fingerprint is the SeqContainer "vocabulary": the set of distinct XML element
 * tags + the set of `PrettyType` values (which distinguish clip/transition subtypes
 * — "Cross Dissolve", "Fusion Title", "Smooth Cut", …). A new Resolve feature shows
 * up as a new element tag and/or a new PrettyType.
 *
 * Workflow for mapping compatibility changes:
 *   1. fingerprint the SAME content exported from two Resolve versions
 *      (content controlled → the diff isolates the *version* schema delta).
 *   2. diffFingerprints(older, newer).elements.added / prettyTypes.added are the
 *      candidate version-gated capabilities → add rows to ./capabilities.js gated at
 *      the newer version's DbPrjVer, with provenance.
 *
 * Only same-content cross-version diffs are meaningful — diffing different timelines
 * surfaces CONTENT differences, not version differences.
 *
 * @module drt-format/schema-fingerprint
 */

const JSZip = require('jszip');
const { listSeqContainerEntries } = require('./drt-parser');

/**
 * Fingerprint a SeqContainer XML string.
 * @returns {{ elements: string[], prettyTypes: string[] }} sorted, de-duplicated.
 */
function schemaFingerprint(seqXml) {
  // element names include Resolve's namespaced tags (Gallery::GyStill, ListMgt::LmVersion).
  const elements = [...new Set(
    (seqXml.match(/<([A-Za-z][\w.:]*)[\s/>]/g) || []).map((t) => t.slice(1).replace(/[\s/>]+$/, '')),
  )].sort();
  const prettyTypes = [...new Set(
    (seqXml.match(/<PrettyType>([^<]*)<\/PrettyType>/g) || []).map((m) => m.replace(/<\/?PrettyType>/g, '')),
  )].sort();
  return { elements, prettyTypes };
}

/** Fingerprint the first SeqContainer of a .drt/.drp buffer. */
async function fingerprintDrt(drtBuffer) {
  const zip = await JSZip.loadAsync(drtBuffer);
  const entries = listSeqContainerEntries(zip);
  if (entries.length === 0) throw new Error('fingerprintDrt: no SeqContainer found');
  return schemaFingerprint(await zip.file(entries[0]).async('string'));
}

/**
 * Fingerprint any Resolve file, auto-detecting format: a zip (DRT/DRP → its
 * SeqContainer) or a single XML (DRX → its grade/gallery vocabulary directly).
 * @param {Buffer|string} input
 */
async function fingerprintFile(input) {
  const buf = Buffer.isBuffer(input) ? input : Buffer.from(String(input));
  const isZip = buf.length > 1 && buf[0] === 0x50 && buf[1] === 0x4b; // 'PK'
  return isZip ? fingerprintDrt(buf) : schemaFingerprint(buf.toString('utf8'));
}

/**
 * Diff two fingerprints (older → newer). `added` = present in `b` not `a`
 * (candidate version-gated capabilities); `removed` = present in `a` not `b`.
 */
function diffFingerprints(a, b) {
  const d = (xa, xb) => ({
    added: xb.filter((v) => !xa.includes(v)),
    removed: xa.filter((v) => !xb.includes(v)),
  });
  return {
    elements: d(a.elements, b.elements),
    prettyTypes: d(a.prettyTypes, b.prettyTypes),
  };
}

module.exports = { schemaFingerprint, fingerprintDrt, fingerprintFile, diffFingerprints };
