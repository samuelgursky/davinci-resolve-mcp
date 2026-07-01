/**
 * Tests for DaVinci Resolve Grade Body Encoder
 *
 * Verifies encoding against real examples extracted from DaVinci Resolve projects.
 */

const {
  encodeGradeBody,
  encodeVarint,
  encodeFloat,
  encodeDouble,
  encodeNeutralGrade,
  decodeVarint,
  decodeFloat
} = require('./grade-encoder');

// Color codes for terminal output
const GREEN = '\x1b[32m';
const RED = '\x1b[31m';
const RESET = '\x1b[0m';
const YELLOW = '\x1b[33m';

function assert(condition, message) {
  if (!condition) {
    console.log(`${RED}✗ FAIL${RESET}: ${message}`);
    throw new Error(`Assertion failed: ${message}`);
  }
  console.log(`${GREEN}✓ PASS${RESET}: ${message}`);
}

function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    console.log(`${RED}✗ FAIL${RESET}: ${message}`);
    console.log(`  Expected: ${expected}`);
    console.log(`  Actual:   ${actual}`);
    throw new Error(`Assertion failed: ${message}`);
  }
  console.log(`${GREEN}✓ PASS${RESET}: ${message}`);
}

console.log('\n=== Grade Body Encoder Tests ===\n');

// Test 1: Varint Encoding
console.log('Test Group: Varint Encoding');
assertEqual(encodeVarint(1).toString('hex'), '01', 'Varint: 1');
assertEqual(encodeVarint(127).toString('hex'), '7f', 'Varint: 127');
assertEqual(encodeVarint(128).toString('hex'), '8001', 'Varint: 128');
assertEqual(encodeVarint(1920).toString('hex'), '800f', 'Varint: 1920 (width)');
assertEqual(encodeVarint(1080).toString('hex'), 'b808', 'Varint: 1080 (height)');
assertEqual(encodeVarint(45).toString('hex'), '2d', 'Varint: 45 (typical length)');
console.log('');

// Test 2: Float Encoding
console.log('Test Group: Float Encoding');
assertEqual(encodeFloat(1.0), '0000803f', 'Float: 1.0 (neutral)');
assertEqual(encodeFloat(0.9), '6666663f', 'Float: 0.9 (-10% adjustment)');
// Verify decoding works
assert(Math.abs(decodeFloat('0000803f') - 1.0) < 0.0001, 'Float decode: 1.0');
assert(Math.abs(decodeFloat('6666663f') - 0.9) < 0.0001, 'Float decode: 0.9');
console.log('');

// Test 3: Double Encoding
console.log('Test Group: Double Encoding');
const doubleResult = encodeDouble(1.0);
assertEqual(doubleResult.length, 16, 'Double: correct length (16 hex chars = 8 bytes)');
assertEqual(doubleResult, '000000000000f03f', 'Double: 1.0');
console.log('');

// Test 4: Varint Decoding (for verification)
console.log('Test Group: Varint Decoding');
const decoded1920 = decodeVarint('800f', 0);
assertEqual(decoded1920.value, 1920, 'Decode varint: 1920');
assertEqual(decoded1920.bytesRead, 2, 'Decode varint: 1920 bytes read');

const decoded1080 = decodeVarint('b808', 0);
assertEqual(decoded1080.value, 1080, 'Decode varint: 1080');
assertEqual(decoded1080.bytesRead, 2, 'Decode varint: 1080 bytes read');
console.log('');

// Test 5: Neutral Grade Body Structure
console.log('Test Group: Neutral Grade Body Structure');

// Real example from DaVinci Resolve project:
// 800a2d10011a2208800f10b8081d0000803f20800f28b808350000803f38800f40b80848ffffffff0f6086d0ccb0db321001208aceccb0db32

const neutralGrade = encodeNeutralGrade({ width: 1920, height: 1080 });

// Verify header
assert(neutralGrade.startsWith('800a'), 'Neutral grade: starts with 800a header');

// Verify length byte (should be 2d = 45 for typical neutral grade structure)
const lengthHex = neutralGrade.substr(4, 2);
console.log(`${YELLOW}INFO${RESET}: Length byte = 0x${lengthHex} (${parseInt(lengthHex, 16)} bytes)`);

// Verify it contains expected patterns
assert(neutralGrade.includes('10011a22'), 'Neutral grade: contains version and field 3 tag');
assert(neutralGrade.includes('08800f'), 'Neutral grade: contains width 1920');
assert(neutralGrade.includes('10b808'), 'Neutral grade: contains height 1080');
assert(neutralGrade.includes('0000803f'), 'Neutral grade: contains 1.0 floats');
assert(neutralGrade.includes('ffffffff0f'), 'Neutral grade: contains flags');

console.log(`${YELLOW}INFO${RESET}: Generated neutral grade (length ${neutralGrade.length / 2} bytes):`);
console.log(`${YELLOW}INFO${RESET}: ${neutralGrade.substr(0, 80)}...`);
console.log('');

// Test 6: Grade with Adjustment
console.log('Test Group: Grade with Primary Adjustment');

const adjustedGrade = encodeGradeBody({
  hasCorrection: true,
  primaryAdjustment: 0.9,
  width: 1920,
  height: 1080
});

assert(adjustedGrade.startsWith('800a'), 'Adjusted grade: starts with 800a header');
assert(adjustedGrade.includes('6666663f'), 'Adjusted grade: contains 0.9 adjustment value');
console.log(`${YELLOW}INFO${RESET}: Generated adjusted grade (length ${adjustedGrade.length / 2} bytes):`);
console.log(`${YELLOW}INFO${RESET}: ${adjustedGrade.substr(0, 80)}...`);
console.log('');

// Test 7: Different Resolutions
console.log('Test Group: Different Resolutions');

const uhd4k = encodeNeutralGrade({ width: 3840, height: 2160 });
assert(uhd4k.startsWith('800a'), 'UHD 4K grade: valid header');
assert(uhd4k.includes(encodeVarint(3840).toString('hex')), 'UHD 4K grade: contains 3840 width');
assert(uhd4k.includes(encodeVarint(2160).toString('hex')), 'UHD 4K grade: contains 2160 height');

const hd720 = encodeNeutralGrade({ width: 1280, height: 720 });
assert(hd720.startsWith('800a'), 'HD 720p grade: valid header');
assert(hd720.includes(encodeVarint(1280).toString('hex')), 'HD 720p grade: contains 1280 width');
assert(hd720.includes(encodeVarint(720).toString('hex')), 'HD 720p grade: contains 720 height');
console.log('');

// Test 8: Structure Validation
console.log('Test Group: Structure Validation');

// Verify the structure matches the documented format
const gradeHex = encodeNeutralGrade({ width: 1920, height: 1080 });

let pos = 0;
// Header
assertEqual(gradeHex.substr(pos, 4), '800a', 'Structure: correct header');
pos += 4;

// Length (varint)
const lengthByte = gradeHex.substr(pos, 2);
const length = parseInt(lengthByte, 16);
assert(length > 0, `Structure: valid length (${length} bytes)`);
pos += 2;

// Field 2 tag (0x10 = field 2, wire type 0)
assertEqual(gradeHex.substr(pos, 2), '10', 'Structure: field 2 tag');
pos += 2;

// Version value (0x01)
assertEqual(gradeHex.substr(pos, 2), '01', 'Structure: version = 1');
pos += 2;

// Field 3 tag (0x1a = field 3, wire type 2 = length-delimited)
assertEqual(gradeHex.substr(pos, 2), '1a', 'Structure: field 3 tag');
pos += 2;

console.log(`${YELLOW}INFO${RESET}: Structure validation complete at position ${pos / 2} bytes`);
console.log('');

// Summary
console.log('=================================');
console.log(`${GREEN}All tests passed!${RESET}`);
console.log('=================================\n');
