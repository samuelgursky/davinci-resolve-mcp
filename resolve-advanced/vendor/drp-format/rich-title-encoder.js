/**
 * DaVinci Resolve Rich Title (PrettyType=Rich) Encoder
 *
 * Encodes styled title cards for video tracks (Sm2TiTrack Type=0).
 * Rich titles use zstd-compressed protobuf with an inner text document
 * format containing font, size, color, and style metadata.
 *
 * Binary format reverse-engineered from V49A.drp Rich title clips.
 *
 * @module drp-generator/rich-title-encoder
 */
'use strict';

const { ZstdCodec } = require('zstd-codec');
const {
  encodeVarint,
  encodeTag,
  buildNestedField,
  buildVarintField,
  WIRE_TYPES,
} = require('./effect-encoder');

// =============================================================================
// ZSTD SINGLETON (same pattern as drx-generator.js)
// =============================================================================

let zstdCompressor = null;

async function getZstdCompressor() {
  if (zstdCompressor) return zstdCompressor;

  return new Promise((resolve, reject) => {
    ZstdCodec.run((zstd) => {
      zstdCompressor = new zstd.Simple();
      resolve(zstdCompressor);
    });
  });
}

// =============================================================================
// CONSTANTS — verified from all 5 V49A Rich title clips
// =============================================================================

/**
 * Default Rich title parameters
 */
const RICH_DEFAULTS = {
  fontFamily: 'Open Sans',
  fontSize: 48.0,
  styleName: 'Semibold',
  colorHex: '#ffffff',
  templateFontSize: 96.0,
  templateColorHex: '#FFFFFF',
  templateText: 'Basic Title',
};

/**
 * Magic header: [0x0bb1] magic + 10-byte doc header
 * Constant across all observed Rich title documents.
 * 29 bytes total: u16LE magic (0x0bb1) + fixed header bytes
 */
const MAGIC_HEADER = Buffer.from(
  '0bb100000a0000006200610060000f0000000800000001000000380400',
  'hex'
);

/**
 * Style suffix bytes after style name (Semibold variant)
 * [0x04, 0x3f, 0x00, 0x12]
 */
const STYLE_SUFFIX = Buffer.from([0x04, 0x3f, 0x00, 0x12]);

/**
 * 3-byte flags after style section: all zeros
 */
const FLAGS_BYTES = Buffer.from([0x00, 0x00, 0x00]);

/**
 * 2-byte trail after color hex in each run
 */
const TRAIL_LOW = Buffer.from([0xe8, 0xf7]);

/**
 * 2-byte doc trail at end of document
 */
const DOC_TRAIL = Buffer.from([0x1e, 0x03]);

/**
 * Default transform data (24 bytes) — position/scale for centered title
 * Protobuf: field 1=0x11, nested field 3 containing field 8 with position/scale doubles
 */
const DEFAULT_TRANSFORM = Buffer.from(
  '08111a140a123a103fe00000000000003fbbf86a314dbf80',
  'hex'
);

/**
 * Primary run type (main text document)
 */
const RUN_TYPE_PRIMARY = 0x0001;

/**
 * Template run type (template/placeholder document)
 */
const RUN_TYPE_TEMPLATE = 0x0104;

/**
 * Generator type ID for Rich title in protobuf field 1
 */
const GENERATOR_TYPE_ID = 0x30; // 48

// =============================================================================
// TEXT DOCUMENT BUILDER
// =============================================================================

/**
 * Build a Rich text document (inner binary structure).
 *
 * Structure:
 *   [u32LE docSize] [MAGIC_HEADER 29b]
 *   [u32LE sec33] [u32LE sec37]
 *   [UTF-16LE text] [u32LE runCount=2]
 *   [run: type, size, fontName, fontSize, styleName, flags, color, trail]
 *   [DOC_TRAIL 2b]
 *
 * @param {string} text - Title text content
 * @param {string} fontName - Font family name (e.g. 'Open Sans')
 * @param {number} fontSize - Font size in points (e.g. 48.0)
 * @param {string} styleName - Font style name (e.g. 'Semibold')
 * @param {string} colorHex - Color as hex string with # prefix (e.g. '#ffffff')
 * @param {number} runType - Run type identifier (PRIMARY=0x0001, TEMPLATE=0x0104)
 * @returns {Buffer} Complete text document binary
 */
function buildRichTextDocument(text, fontName, fontSize, styleName, colorHex, runType) {
  // Encode text as UTF-16LE
  const textBytes = Buffer.from(text, 'utf16le');
  const textByteLen = textBytes.length;

  // Build font name section: UTF-16LE fontName + null terminator + f32LE high bytes
  const fontNameUtf16 = Buffer.from(fontName, 'utf16le');
  const fontSizeBuf = Buffer.allocUnsafe(4);
  fontSizeBuf.writeFloatLE(fontSize, 0);
  // Font name section: fontNameUtf16 + 0x0000 (null term) + high 2 bytes of f32LE
  const fontNameSection = Buffer.concat([
    fontNameUtf16,
    Buffer.from([0x00, 0x00]),          // null terminator
    fontSizeBuf.subarray(2, 4),         // high 2 bytes of f32LE fontSize
  ]);
  const fnTotal = fontNameSection.length; // fontName.length * 2 + 4

  // Build style name section: UTF-16LE styleName + STYLE_SUFFIX
  const styleNameUtf16 = Buffer.from(styleName, 'utf16le');
  const styleNameSection = Buffer.concat([styleNameUtf16, STYLE_SUFFIX]);
  const stTotal = styleNameSection.length; // styleName.length * 2 + 4

  // Build color hex as UTF-16LE (keep # prefix — Resolve expects it)
  const colorStr = colorHex.startsWith('#') ? colorHex : `#${colorHex}`;
  const colorUtf16 = Buffer.from(colorStr, 'utf16le');

  // Assemble run body (after type and size fields)
  const runBody = Buffer.concat([
    // u32LE fontName section length
    u32LE(fnTotal),
    fontNameSection,
    // u32LE styleName section length
    u32LE(stTotal),
    styleNameSection,
    // Flags (3 bytes)
    FLAGS_BYTES,
    // Color hex as UTF-16LE
    colorUtf16,
    // Trail
    TRAIL_LOW,
  ]);

  // Run: [u16LE runType] [u32LE runSize] [runBody]
  // runSize includes the 6-byte header (2 type + 4 size) — matches Resolve's convention
  const runSize = runBody.length + 6;
  const run = Buffer.concat([
    u16LE(runType),
    u32LE(runSize),
    runBody,
  ]);

  // Section offsets
  // sec33 = textByteLen + 14 (observed constant offset)
  // sec37 = textByteLen + 4
  const sec33 = textByteLen + 14;
  const sec37 = textByteLen + 4;

  // runCount = 2 (observed: always 2 runs encoded but we write 1 run — the count
  // field says "2" in V49A but only 1 run structure follows, with the doc trail
  // immediately after. This matches the observed binary exactly.)
  const runCount = 2;

  // Assemble document body (everything after docSize field)
  const docBody = Buffer.concat([
    MAGIC_HEADER,         // 29 bytes
    u32LE(sec33),         // 4 bytes
    u32LE(sec37),         // 4 bytes
    textBytes,            // textByteLen bytes
    u32LE(runCount),      // 4 bytes
    run,                  // variable
    DOC_TRAIL,            // 2 bytes
  ]);

  // docSize includes the 4-byte docSize field itself — matches Resolve's convention
  const docSize = docBody.length + 4;

  return Buffer.concat([u32LE(docSize), docBody]);
}

// =============================================================================
// PROTOBUF PAYLOAD BUILDER
// =============================================================================

/**
 * Build the decompressed protobuf payload for a Rich title.
 *
 * Structure:
 *   Field 1 (varint) = 0x30 (generator type)
 *   Field 3 (varint) = 0x00
 *   Field 7 (varint) = 0x00
 *   Field 9 (length-delimited, repeated):
 *     [0] empty
 *     [1] content: Field 3 → primary doc, Field 4 → template doc
 *     [2] empty
 *     [3] transform data
 *     [4-7] empty
 *
 * @param {string} primaryText - Main title text
 * @param {Object} [options] - Encoding options
 * @param {string} [options.fontFamily='Open Sans'] - Font family
 * @param {number} [options.fontSize=48.0] - Font size
 * @param {string} [options.styleName='Semibold'] - Style name
 * @param {string} [options.colorHex='#ffffff'] - Text color
 * @returns {Buffer} Decompressed protobuf payload
 */
function buildRichTitlePayload(primaryText, options = {}) {
  const {
    fontFamily = RICH_DEFAULTS.fontFamily,
    fontSize = RICH_DEFAULTS.fontSize,
    styleName = RICH_DEFAULTS.styleName,
    colorHex = RICH_DEFAULTS.colorHex,
  } = options;

  // Build primary text document
  const primaryDoc = buildRichTextDocument(
    primaryText, fontFamily, fontSize, styleName, colorHex, RUN_TYPE_PRIMARY
  );

  // Build template text document
  const templateDoc = buildRichTextDocument(
    RICH_DEFAULTS.templateText,
    fontFamily,
    RICH_DEFAULTS.templateFontSize,
    styleName,
    RICH_DEFAULTS.templateColorHex,
    RUN_TYPE_TEMPLATE
  );

  // Build inner content message for field 9[1]:
  //   Field 1 (varint) = 0x0f (15) — content type flag
  //   Field 3 (nested) = { field 1 (nested) = { field 8 = primary doc bytes } }
  //   Field 4 (nested) = { field 1 (nested) = { field 8 = template doc bytes } }
  const wrappedPrimary = buildNestedField(1, buildLengthDelimitedRaw(8, primaryDoc));
  const wrappedTemplate = buildNestedField(1, buildLengthDelimitedRaw(8, templateDoc));
  const innerContent = Buffer.concat([
    buildVarintField(1, 0x0f),
    buildNestedField(3, wrappedPrimary),
    buildNestedField(4, wrappedTemplate),
  ]);

  // Build repeated field 9 instances
  // [0] empty, [1] content, [2] empty, [3] transform, [4-7] empty
  const field9Entries = [];

  // [0] empty
  field9Entries.push(buildNestedField(9, Buffer.alloc(0)));

  // [1] content wrapper
  field9Entries.push(buildNestedField(9, innerContent));

  // [2] empty
  field9Entries.push(buildNestedField(9, Buffer.alloc(0)));

  // [3] transform data
  field9Entries.push(buildNestedField(9, DEFAULT_TRANSFORM));

  // [4-7] empty
  for (let i = 4; i <= 7; i++) {
    field9Entries.push(buildNestedField(9, Buffer.alloc(0)));
  }

  // Assemble inner protobuf message
  const innerMessage = Buffer.concat([
    buildVarintField(1, GENERATOR_TYPE_ID),  // Field 1 = 0x30 (48)
    buildVarintField(3, 0),                   // Field 3 = 0
    buildVarintField(7, 0),                   // Field 7 = 0
    ...field9Entries,                          // Repeated field 9
  ]);

  // Wrap in outer field 1 (nested) — Resolve expects this wrapper
  return buildNestedField(1, innerMessage);
}

// =============================================================================
// HIGH-LEVEL API
// =============================================================================

/**
 * Encode a Rich title EffectFiltersBA blob.
 *
 * Pipeline:
 *   1. Build primary + template text documents
 *   2. Wrap in protobuf payload
 *   3. Zstd-compress
 *   4. Wrap in EffectFiltersBA header [version=2 BE] [size BE] [0x81] [compressed]
 *
 * @param {string} text - Title text content
 * @param {Object} [options] - Encoding options
 * @param {string} [options.fontFamily='Open Sans'] - Font family
 * @param {number} [options.fontSize=48.0] - Font size
 * @param {string} [options.styleName='Semibold'] - Style name
 * @param {string} [options.colorHex='#ffffff'] - Text color
 * @returns {Promise<string>} Hex-encoded EffectFiltersBA blob
 */
async function encodeRichEffectFiltersBA(text, options = {}) {
  const zstd = await getZstdCompressor();

  // Build decompressed protobuf payload
  const payload = buildRichTitlePayload(text, options);

  // Zstd-compress
  const compressed = Buffer.from(zstd.compress(new Uint8Array(payload)));

  // Build EffectFiltersBA wrapper
  // [u32BE version=2] [u32BE payloadSize] [0x81] [compressed data]
  const marker = Buffer.from([0x81]);
  const payloadWithMarker = Buffer.concat([marker, compressed]);

  const version = Buffer.alloc(4);
  version.writeUInt32BE(2, 0);

  const size = Buffer.alloc(4);
  size.writeUInt32BE(payloadWithMarker.length, 0);

  const complete = Buffer.concat([version, size, payloadWithMarker]);
  return complete.toString('hex');
}

/**
 * Build a Rich title FieldsBlob (per-clip metadata).
 *
 * Structure:
 *   [u32BE version=2] [u32BE payloadSize] [0x80]
 *   [protobuf: Field 1 → Field 3 → {Field 1 varint=4, Field 2 varint=timestamp}]
 *
 * @returns {string} Hex-encoded FieldsBlob
 */
function buildRichFieldsBlob() {
  // Inner message: Field 1 = 4, Field 2 = timestamp (microseconds)
  const timestamp = Date.now() * 1000;
  const innerMsg = Buffer.concat([
    buildVarintField(1, 4),
    buildVarintField(2, timestamp),
  ]);

  // Wrap in Field 3, then Field 1
  const field3 = buildNestedField(3, innerMsg);
  const field1 = buildNestedField(1, field3);

  // EffectFiltersBA-style header with 0x80 (uncompressed)
  const marker = Buffer.from([0x80]);
  const payloadWithMarker = Buffer.concat([marker, field1]);

  const version = Buffer.alloc(4);
  version.writeUInt32BE(2, 0);

  const size = Buffer.alloc(4);
  size.writeUInt32BE(payloadWithMarker.length, 0);

  const complete = Buffer.concat([version, size, payloadWithMarker]);
  return complete.toString('hex');
}

// =============================================================================
// HELPERS
// =============================================================================

/**
 * Write a u32 little-endian value to a 4-byte buffer.
 * @param {number} value
 * @returns {Buffer}
 */
function u32LE(value) {
  const buf = Buffer.allocUnsafe(4);
  buf.writeUInt32LE(value, 0);
  return buf;
}

/**
 * Write a u16 little-endian value to a 2-byte buffer.
 * @param {number} value
 * @returns {Buffer}
 */
function u16LE(value) {
  const buf = Buffer.allocUnsafe(2);
  buf.writeUInt16LE(value, 0);
  return buf;
}

/**
 * Build a raw length-delimited protobuf field (field tag + varint length + raw bytes).
 * Unlike buildNestedField from effect-encoder which is for nested messages,
 * this wraps raw binary data (text documents) without interpretation.
 *
 * @param {number} fieldNumber - Protobuf field number
 * @param {Buffer} data - Raw bytes to wrap
 * @returns {Buffer} Encoded field
 */
function buildLengthDelimitedRaw(fieldNumber, data) {
  const tag = encodeTag(fieldNumber, WIRE_TYPES.LENGTH_DELIMITED);
  const length = encodeVarint(data.length);
  return Buffer.concat([tag, length, data]);
}

// =============================================================================
// EXPORTS
// =============================================================================

module.exports = {
  // High-level API
  encodeRichEffectFiltersBA,
  buildRichFieldsBlob,

  // Mid-level (for testing/customization)
  buildRichTextDocument,
  buildRichTitlePayload,

  // Constants
  RICH_DEFAULTS,
  MAGIC_HEADER,
  GENERATOR_TYPE_ID,
  RUN_TYPE_PRIMARY,
  RUN_TYPE_TEMPLATE,
};
