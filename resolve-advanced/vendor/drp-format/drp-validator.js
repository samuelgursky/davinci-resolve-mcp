/**
 * DaVinci Resolve Project (.drp) Validator
 *
 * Validates DRP files to ensure they will load correctly in DaVinci Resolve.
 * Checks archive structure, XML validity, binary blob integrity, and cross-references.
 *
 * @module drp-validator
 */

const fs = require('fs');
const path = require('path');
const AdmZip = require('adm-zip');
const { isSafeArchiveEntryName } = require('./utils/safe-archive');
const { XMLParser } = require('fast-xml-parser');

/**
 * Validation result levels
 */
const SEVERITY = {
  ERROR: 'error',     // Will prevent loading
  WARNING: 'warning', // May cause issues
  INFO: 'info',       // Informational only
};

/**
 * Known valid frame rates
 */
const VALID_FRAME_RATES = [
  23.976, 23.98, 24, 25, 29.97, 30, 48, 50, 59.94, 60, 120
];

/**
 * Required files in a DRP archive
 */
const REQUIRED_FILES = ['project.xml'];

/**
 * Valid FieldsBlob type markers
 */
const VALID_FIELDSBLOB_TYPES = [0x00000001, 0x00000002];

/**
 * Main validation result class
 */
class ValidationResult {
  constructor() {
    this.valid = true;
    this.errors = [];
    this.warnings = [];
    this.info = [];
    this.stats = {
      filesChecked: 0,
      blobsValidated: 0,
      clipsFound: 0,
      groupsFound: 0,
      markersFound: 0,
    };
  }

  addIssue(severity, category, message, details = null) {
    const issue = { category, message, details };

    switch (severity) {
      case SEVERITY.ERROR:
        this.valid = false;
        this.errors.push(issue);
        break;
      case SEVERITY.WARNING:
        this.warnings.push(issue);
        break;
      case SEVERITY.INFO:
        this.info.push(issue);
        break;
    }
  }

  isValid() {
    return this.valid;
  }

  getSummary() {
    return {
      valid: this.valid,
      errorCount: this.errors.length,
      warningCount: this.warnings.length,
      infoCount: this.info.length,
      stats: this.stats,
    };
  }

  toJSON() {
    return {
      valid: this.valid,
      summary: this.getSummary(),
      errors: this.errors,
      warnings: this.warnings,
      info: this.info,
    };
  }
}

/**
 * Validate a DRP file
 * @param {string|Buffer} input - File path or buffer
 * @param {Object} options - Validation options
 * @returns {ValidationResult} Validation result
 */
function validateDRP(input, options = {}) {
  const result = new ValidationResult();
  const opts = {
    checkBlobs: true,
    checkReferences: true,
    checkTiming: true,
    verbose: false,
    ...options,
  };

  let zip;
  let files = {};

  // Step 1: Archive Integrity
  try {
    if (typeof input === 'string') {
      if (!fs.existsSync(input)) {
        result.addIssue(SEVERITY.ERROR, 'archive', `File not found: ${input}`);
        return result;
      }
      zip = new AdmZip(input);
    } else if (Buffer.isBuffer(input)) {
      zip = new AdmZip(input);
    } else {
      result.addIssue(SEVERITY.ERROR, 'archive', 'Invalid input: expected file path or buffer');
      return result;
    }

    // Check ZIP magic bytes
    const zipBuffer = typeof input === 'string' ? fs.readFileSync(input) : input;
    if (zipBuffer[0] !== 0x50 || zipBuffer[1] !== 0x4b ||
        zipBuffer[2] !== 0x03 || zipBuffer[3] !== 0x04) {
      result.addIssue(SEVERITY.ERROR, 'archive', 'Invalid ZIP magic bytes (expected PK..)');
      return result;
    }

    result.addIssue(SEVERITY.INFO, 'archive', 'ZIP archive structure valid');

  } catch (err) {
    result.addIssue(SEVERITY.ERROR, 'archive', `Failed to open archive: ${err.message}`);
    return result;
  }

  // Step 2: Extract and check required files
  try {
    const entries = zip.getEntries();
    result.stats.filesChecked = entries.length;

    for (const entry of entries) {
      if (!entry.isDirectory) {
        // SECURITY: reject path-traversal entries and entries that would land on
        // JS prototype keys (__proto__, constructor). Even though files[] is
        // memory-only here, these names propagate into downstream Map/Object lookups.
        const name = entry.entryName;
        if (!isSafeArchiveEntryName(name)) {
          result.addIssue(SEVERITY.ERROR, 'archive', `Unsafe archive entry rejected: ${name}`);
          continue;
        }
        try {
          files[name] = zip.readFile(entry);
        } catch (err) {
          result.addIssue(SEVERITY.ERROR, 'archive', `Failed to extract: ${name}`, err.message);
        }
      }
    }

    // Check required files
    for (const required of REQUIRED_FILES) {
      if (!files[required]) {
        result.addIssue(SEVERITY.ERROR, 'archive', `Missing required file: ${required}`);
      }
    }

    result.addIssue(SEVERITY.INFO, 'archive', `Extracted ${Object.keys(files).length} files`);

  } catch (err) {
    result.addIssue(SEVERITY.ERROR, 'archive', `Archive extraction failed: ${err.message}`);
    return result;
  }

  // Step 3: Parse and validate XML files
  const xmlParser = new XMLParser({
    ignoreAttributes: false,
    attributeNamePrefix: '@_',
    allowBooleanAttributes: true,
  });

  const parsedXml = {};
  const dbIds = new Set();
  const linkedGroups = new Set();
  const groupDbIds = new Set();
  const mediaPoolIds = new Set();
  const clipMediaRefs = new Set();

  for (const [filename, content] of Object.entries(files)) {
    if (filename.endsWith('.xml')) {
      try {
        const xmlString = content.toString('utf-8');
        const parsed = xmlParser.parse(xmlString);
        parsedXml[filename] = parsed;

        // Extract DbIds, groups, and references
        extractReferences(parsed, dbIds, linkedGroups, groupDbIds, mediaPoolIds, clipMediaRefs, result);

        result.addIssue(SEVERITY.INFO, 'xml', `Parsed: ${filename}`);

      } catch (err) {
        result.addIssue(SEVERITY.ERROR, 'xml', `Failed to parse ${filename}`, err.message);
      }
    }
  }

  // Step 4: Validate binary blobs
  if (opts.checkBlobs) {
    validateBlobs(parsedXml, result, opts.verbose);
  }

  // Step 5: Check reference integrity
  if (opts.checkReferences) {
    validateReferences(linkedGroups, groupDbIds, clipMediaRefs, mediaPoolIds, result);
  }

  // Step 6: Check timing values
  if (opts.checkTiming) {
    validateTiming(parsedXml, result);
  }

  return result;
}

/**
 * Extract references from parsed XML
 */
function extractReferences(obj, dbIds, linkedGroups, groupDbIds, mediaPoolIds, clipMediaRefs, result) {
  if (!obj || typeof obj !== 'object') return;

  // Handle DbId attributes
  if (obj['@_DbId']) {
    if (dbIds.has(obj['@_DbId'])) {
      result.addIssue(SEVERITY.WARNING, 'reference', `Duplicate DbId found`, obj['@_DbId']);
    }
    dbIds.add(obj['@_DbId']);
  }

  // Track Sm2Group DbIds
  if (obj['Sm2Group']) {
    const groups = Array.isArray(obj['Sm2Group']) ? obj['Sm2Group'] : [obj['Sm2Group']];
    for (const group of groups) {
      if (group['@_DbId']) {
        groupDbIds.add(group['@_DbId']);
        result.stats.groupsFound++;
      }
    }
  }

  // Track LinkedGroup references
  if (obj['LinkedGroup']) {
    const refs = Array.isArray(obj['LinkedGroup']) ? obj['LinkedGroup'] : [obj['LinkedGroup']];
    for (const ref of refs) {
      if (typeof ref === 'string') {
        linkedGroups.add(ref);
      }
    }
  }

  // Track media pool IDs
  if (obj['Sm2MpVideoClip'] || obj['Sm2SourceClip']) {
    const clips = obj['Sm2MpVideoClip'] || obj['Sm2SourceClip'];
    const clipArray = Array.isArray(clips) ? clips : [clips];
    for (const clip of clipArray) {
      if (clip['@_DbId']) {
        mediaPoolIds.add(clip['@_DbId']);
      }
    }
  }

  // Track clip references
  if (obj['Sm2VideoClip'] || obj['Sm2TiVideoClip']) {
    const clips = obj['Sm2VideoClip'] || obj['Sm2TiVideoClip'];
    const clipArray = Array.isArray(clips) ? clips : [clips];
    for (const clip of clipArray) {
      result.stats.clipsFound++;
      if (clip['MediaRef']) {
        clipMediaRefs.add(clip['MediaRef']);
      }
    }
  }

  // Recurse
  for (const key of Object.keys(obj)) {
    if (key.startsWith('@_')) continue;
    extractReferences(obj[key], dbIds, linkedGroups, groupDbIds, mediaPoolIds, clipMediaRefs, result);
  }
}

/**
 * Validate binary blob fields
 */
function validateBlobs(parsedXml, result, verbose) {
  const blobFields = [
    'FieldsBlob', 'EffectFiltersBA', 'MediaTimemapBA', 'Body',
    'MediaFrameRate', 'ImportExportMetadataBA', 'TracksBA',
    'VirtualAudioTrackBA', 'Clip', 'Radiometry', 'PreConformMediaExtents'
  ];

  function findBlobs(obj, path = '') {
    if (!obj || typeof obj !== 'object') return;

    for (const key of Object.keys(obj)) {
      if (key.startsWith('@_')) continue;

      const currentPath = path ? `${path}.${key}` : key;

      if (blobFields.includes(key)) {
        const value = obj[key];
        if (typeof value === 'string' && value.length > 0) {
          validateBlobHex(key, value, currentPath, result, verbose);
          result.stats.blobsValidated++;
        }
      }

      if (typeof obj[key] === 'object') {
        findBlobs(obj[key], currentPath);
      }
    }
  }

  for (const [filename, parsed] of Object.entries(parsedXml)) {
    findBlobs(parsed, filename);
  }
}

/**
 * Validate a hex-encoded blob
 */
function validateBlobHex(blobType, hexString, path, result, verbose) {
  // Check hex validity
  if (!/^[0-9a-fA-F]*$/.test(hexString)) {
    result.addIssue(SEVERITY.ERROR, 'blob', `Invalid hex characters in ${blobType}`, path);
    return;
  }

  if (hexString.length % 2 !== 0) {
    result.addIssue(SEVERITY.ERROR, 'blob', `Odd hex length in ${blobType}`, path);
    return;
  }

  const buffer = Buffer.from(hexString, 'hex');

  switch (blobType) {
    case 'FieldsBlob':
      validateFieldsBlob(buffer, path, result, verbose);
      break;

    case 'EffectFiltersBA':
      validateEffectFiltersBA(buffer, path, result, verbose);
      break;

    case 'MediaFrameRate':
      validateMediaFrameRate(buffer, path, result, verbose);
      break;

    case 'MediaTimemapBA':
      validateMediaTimemapBA(buffer, path, result, verbose);
      break;

    case 'Body':
      validateBody(buffer, path, result, verbose);
      break;

    case 'ImportExportMetadataBA':
      validateFieldsBlob(buffer, path, result, verbose); // Same format
      break;

    default:
      if (verbose) {
        result.addIssue(SEVERITY.INFO, 'blob', `${blobType}: ${buffer.length} bytes`, path);
      }
  }
}

/**
 * Validate FieldsBlob structure
 */
function validateFieldsBlob(buffer, path, result, verbose) {
  if (buffer.length < 8) {
    result.addIssue(SEVERITY.ERROR, 'blob', 'FieldsBlob too short (< 8 bytes)', path);
    return;
  }

  const type = buffer.readUInt32BE(0);

  if (!VALID_FIELDSBLOB_TYPES.includes(type)) {
    // Check for zlib compression
    if (buffer[0] === 0x78 && buffer[1] === 0x9c) {
      if (verbose) {
        result.addIssue(SEVERITY.INFO, 'blob', 'FieldsBlob: Zlib compressed', path);
      }
      return;
    }

    result.addIssue(SEVERITY.WARNING, 'blob', `FieldsBlob unknown type: 0x${type.toString(16)}`, path);
    return;
  }

  if (type === 0x00000001) {
    // Type 1: Key-value format
    // Note: FieldsBlob format can have internal complexity after first field
    // We validate the header and first field, but allow for format variations
    const fieldCount = buffer.readUInt32BE(4);
    let offset = 8;
    let validatedFields = 0;

    for (let i = 0; i < fieldCount && offset < buffer.length; i++) {
      if (offset + 4 > buffer.length) {
        // Ran out of data - if we validated at least one field, this is OK
        if (validatedFields === 0) {
          result.addIssue(SEVERITY.ERROR, 'blob', `FieldsBlob has no valid fields`, path);
        }
        return;
      }

      const nameLen = buffer.readUInt32BE(offset);

      // Sanity check: name length should be reasonable (< 1000 bytes for a field name)
      // If not, the format likely has internal structure we don't fully understand
      if (nameLen > 1000 || nameLen === 0) {
        // After first field, internal format may vary - this is OK
        if (validatedFields > 0) {
          if (verbose) {
            result.addIssue(SEVERITY.INFO, 'blob',
              `FieldsBlob Type 1: ${validatedFields}+ fields (internal structure)`, path);
          }
          return;
        }
        // First field has unreasonable name length
        result.addIssue(SEVERITY.WARNING, 'blob',
          `FieldsBlob unusual name length: ${nameLen}`, path);
        return;
      }
      offset += 4;

      if (offset + nameLen > buffer.length) {
        if (validatedFields > 0) return; // OK if we got some fields
        result.addIssue(SEVERITY.WARNING, 'blob', `FieldsBlob field ${i} name extends beyond buffer`, path);
        return;
      }
      offset += nameLen;

      if (offset + 4 > buffer.length) {
        if (validatedFields > 0) return;
        result.addIssue(SEVERITY.WARNING, 'blob', `FieldsBlob field ${i} missing value length`, path);
        return;
      }

      const valueLen = buffer.readUInt32BE(offset);
      offset += 4;

      if (offset + valueLen > buffer.length) {
        if (validatedFields > 0) return;
        result.addIssue(SEVERITY.WARNING, 'blob', `FieldsBlob field ${i} value extends beyond buffer`, path);
        return;
      }
      offset += valueLen;
      validatedFields++;
    }

    if (verbose) {
      result.addIssue(SEVERITY.INFO, 'blob', `FieldsBlob Type 1: ${validatedFields} fields validated`, path);
    }

  } else if (type === 0x00000002) {
    // Type 2: Protobuf-like
    const payloadSize = buffer.readUInt32BE(4);
    const actualSize = buffer.length - 8;

    // Allow some tolerance for size mismatch (internal compression/padding)
    if (Math.abs(payloadSize - actualSize) > 100 && payloadSize !== actualSize) {
      result.addIssue(SEVERITY.WARNING, 'blob',
        `FieldsBlob Type 2 size mismatch: header=${payloadSize}, actual=${actualSize}`, path);
    }

    if (verbose) {
      result.addIssue(SEVERITY.INFO, 'blob', `FieldsBlob Type 2: ${payloadSize} bytes payload`, path);
    }
  }
}

/**
 * Validate EffectFiltersBA structure
 */
function validateEffectFiltersBA(buffer, path, result, verbose) {
  if (buffer.length < 9) {
    result.addIssue(SEVERITY.ERROR, 'blob', 'EffectFiltersBA too short (< 9 bytes)', path);
    return;
  }

  const version = buffer.readUInt32BE(0);
  if (version !== 2) {
    result.addIssue(SEVERITY.WARNING, 'blob', `EffectFiltersBA unexpected version: ${version}`, path);
  }

  const payloadSize = buffer.readUInt32BE(4);
  const compressionMarker = buffer[8];

  if (compressionMarker !== 0x80 && compressionMarker !== 0x81) {
    result.addIssue(SEVERITY.WARNING, 'blob',
      `EffectFiltersBA unknown compression marker: 0x${compressionMarker.toString(16)}`, path);
  }

  // Check for ZSTD if compressed
  if (compressionMarker === 0x81) {
    if (buffer.length < 13 ||
        buffer[9] !== 0x28 || buffer[10] !== 0xb5 ||
        buffer[11] !== 0x2f || buffer[12] !== 0xfd) {
      result.addIssue(SEVERITY.WARNING, 'blob', 'EffectFiltersBA marked compressed but no ZSTD magic', path);
    }
  }

  if (verbose) {
    result.addIssue(SEVERITY.INFO, 'blob',
      `EffectFiltersBA: v${version}, ${compressionMarker === 0x81 ? 'compressed' : 'raw'}, ${payloadSize} bytes`, path);
  }
}

/**
 * Validate MediaFrameRate structure
 */
function validateMediaFrameRate(buffer, path, result, verbose) {
  if (buffer.length !== 16) {
    result.addIssue(SEVERITY.ERROR, 'blob', `MediaFrameRate wrong size: ${buffer.length} (expected 16)`, path);
    return;
  }

  const fps = buffer.readDoubleLE(0);
  const reserved = buffer.readDoubleLE(8);

  if (reserved !== 0) {
    result.addIssue(SEVERITY.WARNING, 'blob', `MediaFrameRate reserved bytes non-zero`, path);
  }

  // Check for valid frame rate (within tolerance)
  const isValidFps = VALID_FRAME_RATES.some(valid => Math.abs(fps - valid) < 0.01);
  if (!isValidFps && fps > 0) {
    result.addIssue(SEVERITY.WARNING, 'blob', `MediaFrameRate unusual value: ${fps.toFixed(6)} fps`, path);
  }

  if (fps <= 0 || fps > 240) {
    result.addIssue(SEVERITY.ERROR, 'blob', `MediaFrameRate invalid: ${fps}`, path);
  }

  if (verbose) {
    result.addIssue(SEVERITY.INFO, 'blob', `MediaFrameRate: ${fps.toFixed(6)} fps`, path);
  }
}

/**
 * Validate MediaTimemapBA structure
 */
function validateMediaTimemapBA(buffer, path, result, verbose) {
  // Empty timemap (no retime effects) - valid
  if (buffer.length === 0) {
    if (verbose) {
      result.addIssue(SEVERITY.INFO, 'blob', 'MediaTimemapBA: empty (no retime)', path);
    }
    return;
  }

  // Very short blobs with 0x00 marker indicate no retime - valid
  if (buffer.length < 9) {
    if (buffer[0] === 0x00) {
      if (verbose) {
        result.addIssue(SEVERITY.INFO, 'blob', 'MediaTimemapBA: none/default', path);
      }
      return;
    }
    result.addIssue(SEVERITY.WARNING, 'blob', `MediaTimemapBA unusual size: ${buffer.length} bytes`, path);
    return;
  }

  const typeMarker = buffer[0];

  if (typeMarker === 0x00) {
    // No retime effect applied - this is valid
    if (verbose) {
      result.addIssue(SEVERITY.INFO, 'blob', 'MediaTimemapBA: no retime effect', path);
    }
  } else if (typeMarker === 0x02) {
    // Standard timing format
    if (buffer.length === 9) {
      // Simple format
      if (verbose) {
        const duration = buffer.readDoubleBE(1);
        result.addIssue(SEVERITY.INFO, 'blob', `MediaTimemapBA simple: ${duration.toFixed(4)}s`, path);
      }
    } else if (buffer.length === 41) {
      // Standard format
      if (verbose) {
        result.addIssue(SEVERITY.INFO, 'blob', 'MediaTimemapBA standard (41 bytes)', path);
      }
    } else if (buffer.length > 100) {
      // Complex format with keyframes
      if (verbose) {
        result.addIssue(SEVERITY.INFO, 'blob', `MediaTimemapBA complex (${buffer.length} bytes)`, path);
      }
    } else {
      if (verbose) {
        result.addIssue(SEVERITY.INFO, 'blob', `MediaTimemapBA: ${buffer.length} bytes`, path);
      }
    }
  } else {
    // Other type markers may be valid variants
    if (verbose) {
      result.addIssue(SEVERITY.INFO, 'blob',
        `MediaTimemapBA type 0x${typeMarker.toString(16)}: ${buffer.length} bytes`, path);
    }
  }
}

/**
 * Validate Body (grade) structure
 */
function validateBody(buffer, path, result, verbose) {
  if (buffer.length < 2) {
    result.addIssue(SEVERITY.ERROR, 'blob', 'Body too short', path);
    return;
  }

  const header = buffer[0];

  if (header === 0x80 && buffer[1] === 0x0a) {
    // Uncompressed format
    if (verbose) {
      result.addIssue(SEVERITY.INFO, 'blob', `Body uncompressed (${buffer.length} bytes)`, path);
    }
  } else if (header === 0x81) {
    // Check for ZSTD
    if (buffer.length >= 5 &&
        buffer[1] === 0x28 && buffer[2] === 0xb5 &&
        buffer[3] === 0x2f && buffer[4] === 0xfd) {
      if (verbose) {
        result.addIssue(SEVERITY.INFO, 'blob', `Body ZSTD compressed (${buffer.length} bytes)`, path);
      }
    } else {
      result.addIssue(SEVERITY.WARNING, 'blob', 'Body marked compressed but no ZSTD magic', path);
    }
  } else {
    result.addIssue(SEVERITY.WARNING, 'blob',
      `Body unknown header: 0x${header.toString(16)}`, path);
  }
}

/**
 * Validate cross-references
 */
function validateReferences(linkedGroups, groupDbIds, clipMediaRefs, mediaPoolIds, result) {
  // Check LinkedGroup references
  for (const linkedGroup of linkedGroups) {
    if (!groupDbIds.has(linkedGroup)) {
      result.addIssue(SEVERITY.ERROR, 'reference',
        `LinkedGroup references non-existent group`, linkedGroup);
    }
  }

  // Check clip media references (if we have any)
  // Note: This is a simplified check; full validation would need more context
  if (clipMediaRefs.size > 0 && mediaPoolIds.size > 0) {
    let orphanedRefs = 0;
    for (const ref of clipMediaRefs) {
      if (!mediaPoolIds.has(ref)) {
        orphanedRefs++;
      }
    }
    if (orphanedRefs > 0) {
      result.addIssue(SEVERITY.WARNING, 'reference',
        `${orphanedRefs} clip(s) reference missing media pool entries`);
    }
  }

  result.addIssue(SEVERITY.INFO, 'reference',
    `Checked: ${linkedGroups.size} LinkedGroup refs, ${groupDbIds.size} groups, ${mediaPoolIds.size} media pool items`);
}

/**
 * Validate timing values in XML
 */
function validateTiming(parsedXml, result) {
  function checkTiming(obj, path = '') {
    if (!obj || typeof obj !== 'object') return;

    // Check StartFrame/EndFrame
    if (obj['StartFrame'] !== undefined && obj['EndFrame'] !== undefined) {
      const start = parseInt(obj['StartFrame'], 10);
      const end = parseInt(obj['EndFrame'], 10);

      if (isNaN(start) || isNaN(end)) {
        result.addIssue(SEVERITY.ERROR, 'timing', `Invalid frame values at ${path}`);
      } else if (start > end) {
        result.addIssue(SEVERITY.ERROR, 'timing', `StartFrame > EndFrame at ${path}`, { start, end });
      } else if (end - start > 1000000) {
        result.addIssue(SEVERITY.WARNING, 'timing', `Unusually long clip (${end - start} frames) at ${path}`);
      }
    }

    // Check Duration
    if (obj['Duration'] !== undefined) {
      const duration = parseInt(obj['Duration'], 10);
      if (isNaN(duration) || duration < 0) {
        result.addIssue(SEVERITY.ERROR, 'timing', `Invalid Duration at ${path}`);
      }
    }

    // Recurse
    for (const key of Object.keys(obj)) {
      if (key.startsWith('@_')) continue;
      if (typeof obj[key] === 'object') {
        checkTiming(obj[key], path ? `${path}.${key}` : key);
      }
    }
  }

  for (const [filename, parsed] of Object.entries(parsedXml)) {
    checkTiming(parsed, filename);
  }
}

/**
 * Validate a DRP file and print results
 * @param {string} filePath - Path to DRP file
 * @param {Object} options - Validation options
 */
function validateAndPrint(filePath, options = {}) {
  console.log(`\nValidating: ${filePath}\n`);
  console.log('='.repeat(60));

  const result = validateDRP(filePath, options);
  const summary = result.getSummary();

  // Print summary
  console.log(`\nSUMMARY:`);
  console.log(`  Status: ${result.valid ? '✓ VALID' : '✗ INVALID'}`);
  console.log(`  Files checked: ${summary.stats.filesChecked}`);
  console.log(`  Blobs validated: ${summary.stats.blobsValidated}`);
  console.log(`  Clips found: ${summary.stats.clipsFound}`);
  console.log(`  Groups found: ${summary.stats.groupsFound}`);
  console.log(`  Errors: ${summary.errorCount}`);
  console.log(`  Warnings: ${summary.warningCount}`);

  // Print errors
  if (result.errors.length > 0) {
    console.log(`\nERRORS (${result.errors.length}):`);
    for (const err of result.errors) {
      console.log(`  ✗ [${err.category}] ${err.message}`);
      if (err.details) console.log(`    → ${err.details}`);
    }
  }

  // Print warnings
  if (result.warnings.length > 0) {
    console.log(`\nWARNINGS (${result.warnings.length}):`);
    for (const warn of result.warnings) {
      console.log(`  ⚠ [${warn.category}] ${warn.message}`);
      if (warn.details) console.log(`    → ${warn.details}`);
    }
  }

  // Print info if verbose
  if (options.verbose && result.info.length > 0) {
    console.log(`\nINFO (${result.info.length}):`);
    for (const info of result.info) {
      console.log(`  ℹ [${info.category}] ${info.message}`);
    }
  }

  console.log('\n' + '='.repeat(60));
  console.log(`Validation ${result.valid ? 'PASSED' : 'FAILED'}`);

  return result;
}

// CLI support
if (require.main === module) {
  const args = process.argv.slice(2);

  if (args.length === 0) {
    console.log('Usage: node drp-validator.js <file.drp> [--verbose]');
    process.exit(1);
  }

  const filePath = args[0];
  const verbose = args.includes('--verbose') || args.includes('-v');

  const result = validateAndPrint(filePath, { verbose });
  process.exit(result.valid ? 0 : 1);
}

module.exports = {
  validateDRP,
  validateAndPrint,
  ValidationResult,
  SEVERITY,
};
