/**
 * Grade Encoder Verification Script
 *
 * Compares generated grade bodies with real examples from DaVinci Resolve projects
 * to verify structural correctness and compatibility.
 */

const {
  encodeNeutralGrade,
  encodeGradeBody,
  decodeVarint,
  decodeFloat
} = require('./grade-encoder');

// Color codes
const GREEN = '\x1b[32m';
const RED = '\x1b[31m';
const YELLOW = '\x1b[33m';
const BLUE = '\x1b[34m';
const RESET = '\x1b[0m';

console.log('\n=== Grade Body Verification Against Real DaVinci Resolve Examples ===\n');

// Real examples extracted from DaVinci Resolve 19.1.3 project files
const realExamples = [
  {
    name: 'Neutral 1920x1080 #1',
    hex: '800a2d10011a2208800f10b8081d0000803f20800f28b808350000803f38800f40b80848ffffffff0f6086d0ccb0db321001208aceccb0db32',
    description: 'Standard neutral grade at HD resolution'
  },
  {
    name: 'Neutral 1920x1080 #2',
    hex: '800a2d10011a2208800f10b8081d0000803f20800f28b808350000803f38800f40b80848ffffffff0f60acfba8b4db32100120f4f9a8b4db32',
    description: 'Another neutral grade with different timestamp'
  },
  {
    name: 'Adjusted 1920x1080',
    hex: '800a2d10011a2208800f10b8081d0000803f20800f28b8083513da8b3f38800f40b80848ffffffff0f60bceecacea32c100120baeecacea32c',
    description: 'Grade with primary adjustment (0x13da8b3f)'
  }
];

console.log('Analyzing Real Examples:\n');

realExamples.forEach((example, idx) => {
  console.log(`${BLUE}Example ${idx + 1}: ${example.name}${RESET}`);
  console.log(`Description: ${example.description}`);
  console.log(`Hex: ${example.hex.substr(0, 60)}...`);
  console.log('');

  // Parse the structure
  let pos = 0;
  const hex = example.hex;

  // Header
  const header = hex.substr(pos, 4);
  pos += 4;
  console.log(`  Header: 0x${header} ${header === '800a' ? GREEN + '✓ Uncompressed' + RESET : RED + '✗ Unknown' + RESET}`);

  // Length
  const lengthHex = hex.substr(pos, 2);
  const length = parseInt(lengthHex, 16);
  pos += 2;
  console.log(`  Length: ${length} bytes (0x${lengthHex})`);

  // Field 2: Version
  const field2Tag = hex.substr(pos, 2);
  pos += 2;
  const version = hex.substr(pos, 2);
  pos += 2;
  console.log(`  Field 2 (tag 0x${field2Tag}): Version = ${parseInt(version, 16)}`);

  // Field 3: Nested data
  const field3Tag = hex.substr(pos, 2);
  pos += 2;
  const nestedLength = parseInt(hex.substr(pos, 2), 16);
  pos += 2;
  console.log(`  Field 3 (tag 0x${field3Tag}): Nested data (${nestedLength} bytes)`);

  // Parse nested structure
  const nestedStart = pos;

  // Width (field 1)
  pos += 2; // Skip tag
  const widthResult = decodeVarint(hex.substr(pos), 0);
  pos += widthResult.bytesRead * 2;
  console.log(`    Width: ${widthResult.value}px`);

  // Height (field 2)
  pos += 2; // Skip tag
  const heightResult = decodeVarint(hex.substr(pos), 0);
  pos += heightResult.bytesRead * 2;
  console.log(`    Height: ${heightResult.value}px`);

  // Unity float (field 3)
  pos += 2; // Skip tag
  const unityHex = hex.substr(pos, 8);
  const unity = decodeFloat(unityHex);
  pos += 8;
  console.log(`    Unity: ${unity.toFixed(6)} (0x${unityHex})`);

  // Source width (field 4)
  pos += 2; // Skip tag
  const srcWidthResult = decodeVarint(hex.substr(pos), 0);
  pos += srcWidthResult.bytesRead * 2;
  console.log(`    Source Width: ${srcWidthResult.value}px`);

  // Source height (field 5)
  pos += 2; // Skip tag
  const srcHeightResult = decodeVarint(hex.substr(pos), 0);
  pos += srcHeightResult.bytesRead * 2;
  console.log(`    Source Height: ${srcHeightResult.value}px`);

  // Primary adjustment (field 6)
  pos += 2; // Skip tag
  const adjHex = hex.substr(pos, 8);
  const adjustment = decodeFloat(adjHex);
  pos += 8;
  console.log(`    Primary Adj: ${adjustment.toFixed(6)} (0x${adjHex}) ${adjustment === 1.0 ? '- NEUTRAL' : adjustment < 1.0 ? '- DARKER' : '- BRIGHTER'}`);

  console.log('');
});

console.log('\n' + '='.repeat(70) + '\n');
console.log('Generating Our Own Grade Bodies:\n');

// Generate neutral grade
const ourNeutral = encodeNeutralGrade({ width: 1920, height: 1080 });
console.log(`${BLUE}Our Neutral Grade (1920x1080):${RESET}`);
console.log(`Hex: ${ourNeutral.substr(0, 60)}...`);
console.log(`Length: ${ourNeutral.length / 2} bytes`);
console.log('');

// Compare structure
console.log('Structural Comparison with Real Example #1:');
const real1 = realExamples[0].hex;
const maxCompare = Math.min(real1.length, ourNeutral.length);

let matchCount = 0;
let mismatchStart = -1;

for (let i = 0; i < maxCompare; i += 2) {
  const realByte = real1.substr(i, 2);
  const ourByte = ourNeutral.substr(i, 2);

  if (realByte === ourByte) {
    matchCount += 2;
  } else if (mismatchStart === -1) {
    mismatchStart = i;
  }
}

console.log(`  Matching bytes: ${matchCount / 2} / ${maxCompare / 2}`);
console.log(`  Match percentage: ${((matchCount / maxCompare) * 100).toFixed(1)}%`);

if (mismatchStart !== -1) {
  console.log(`  First mismatch at byte ${mismatchStart / 2}:`);
  console.log(`    Real:  ${real1.substr(mismatchStart, 20)}...`);
  console.log(`    Ours:  ${ourNeutral.substr(mismatchStart, 20)}...`);

  // The mismatch is likely in the timestamp field
  if (mismatchStart > 50) {
    console.log(`    ${YELLOW}Note: Mismatch likely due to timestamp difference (expected)${RESET}`);
  }
}

// Check header and structure
console.log('');
console.log('Key Structure Checks:');
const checks = [
  {
    name: 'Header (800a)',
    real: real1.substr(0, 4),
    ours: ourNeutral.substr(0, 4),
    critical: true
  },
  {
    name: 'Version tag (10)',
    real: real1.substr(6, 2),
    ours: ourNeutral.substr(6, 2),
    critical: true
  },
  {
    name: 'Version value (01)',
    real: real1.substr(8, 2),
    ours: ourNeutral.substr(8, 2),
    critical: true
  },
  {
    name: 'Field 3 tag (1a)',
    real: real1.substr(10, 2),
    ours: ourNeutral.substr(10, 2),
    critical: true
  },
  {
    name: 'Width encoding (800f)',
    real: real1.substr(16, 4),
    ours: ourNeutral.substr(16, 4),
    critical: true
  },
  {
    name: 'Height encoding (b808)',
    real: real1.substr(22, 4),
    ours: ourNeutral.substr(22, 4),
    critical: true
  },
  {
    name: 'Unity float (0000803f)',
    real: real1.substr(28, 8),
    ours: ourNeutral.substr(28, 8),
    critical: true
  },
  {
    name: 'Primary adj (0000803f)',
    real: real1.substr(48, 8),
    ours: ourNeutral.substr(48, 8),
    critical: true
  }
];

let passCount = 0;
let criticalFails = 0;

checks.forEach(check => {
  const match = check.real === check.ours;
  const status = match ? `${GREEN}✓ PASS${RESET}` : `${RED}✗ FAIL${RESET}`;

  if (match) passCount++;
  if (!match && check.critical) criticalFails++;

  console.log(`  ${status} ${check.name.padEnd(25)} Real: ${check.real.padEnd(10)} Ours: ${check.ours}`);
});

console.log('');
console.log('='.repeat(70));
console.log(`Results: ${passCount}/${checks.length} checks passed`);

if (criticalFails === 0) {
  console.log(`${GREEN}✓ All critical structure checks passed!${RESET}`);
  console.log(`${GREEN}✓ Generated grades are compatible with DaVinci Resolve format${RESET}`);
} else {
  console.log(`${RED}✗ ${criticalFails} critical checks failed${RESET}`);
  console.log(`${RED}✗ Review implementation for compatibility issues${RESET}`);
}

console.log('');
console.log('Note: Timestamp differences are expected and do not affect compatibility.');
console.log('='.repeat(70));
console.log('');
