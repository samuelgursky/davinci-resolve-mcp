/**
 * Grade Encoder Usage Examples
 *
 * Demonstrates how to use the grade-encoder module to create
 * DaVinci Resolve grade body data.
 */

const {
  encodeGradeBody,
  encodeNeutralGrade,
  encodeVarint,
  encodeFloat
} = require('./grade-encoder');

console.log('=== DaVinci Resolve Grade Body Encoder Examples ===\n');

// Example 1: Create a neutral grade (no color correction)
console.log('Example 1: Neutral Grade (1920x1080)');
console.log('-------------------------------------');
const neutralGrade = encodeNeutralGrade({ width: 1920, height: 1080 });
console.log('Body hex:', neutralGrade);
console.log('Length:', neutralGrade.length / 2, 'bytes');
console.log('');

// Example 2: Create a grade with primary adjustment
console.log('Example 2: Grade with -10% Primary Adjustment');
console.log('----------------------------------------------');
const adjustedGrade = encodeGradeBody({
  hasCorrection: true,
  primaryAdjustment: 0.9, // 0.9 = -10% adjustment
  width: 1920,
  height: 1080
});
console.log('Body hex:', adjustedGrade.substr(0, 80) + '...');
console.log('Length:', adjustedGrade.length / 2, 'bytes');
console.log('');

// Example 3: 4K UHD resolution
console.log('Example 3: Neutral Grade (3840x2160 UHD 4K)');
console.log('--------------------------------------------');
const uhd4k = encodeNeutralGrade({ width: 3840, height: 2160 });
console.log('Body hex:', uhd4k.substr(0, 80) + '...');
console.log('Length:', uhd4k.length / 2, 'bytes');
console.log('');

// Example 4: Custom source resolution (different from timeline)
console.log('Example 4: Custom Source Resolution');
console.log('------------------------------------');
const customSource = encodeGradeBody({
  hasCorrection: true,
  width: 1920,           // Timeline resolution
  height: 1080,
  sourceWidth: 3840,     // Original source is 4K
  sourceHeight: 2160,
  primaryAdjustment: 1.0 // Neutral adjustment
});
console.log('Body hex:', customSource.substr(0, 80) + '...');
console.log('Length:', customSource.length / 2, 'bytes');
console.log('');

// Example 5: Using specific timestamp
console.log('Example 5: Grade with Specific Timestamp');
console.log('-----------------------------------------');
const timestamp = Date.parse('2025-01-01T00:00:00Z') * 1000; // Microseconds
const timestampedGrade = encodeGradeBody({
  hasCorrection: true,
  primaryAdjustment: 1.0,
  width: 1920,
  height: 1080,
  timestamp: timestamp
});
console.log('Body hex:', timestampedGrade.substr(0, 80) + '...');
console.log('Timestamp (microseconds):', timestamp);
console.log('Date:', new Date(timestamp / 1000).toISOString());
console.log('');

// Example 6: Building XML structure for use in DRP file
console.log('Example 6: XML Structure for DRP File');
console.log('--------------------------------------');
const gradeBodyHex = encodeNeutralGrade({ width: 1920, height: 1080 });
const xmlStructure = `
<pLmVerTable>
  <ListMgt::LmVersionTable>
    <Locals>
      <ListMgt::LmVersion>
        <HasCorrection>1</HasCorrection>
        <Body>${gradeBodyHex}</Body>
      </ListMgt::LmVersion>
    </Locals>
  </ListMgt::LmVersionTable>
</pLmVerTable>
`.trim();
console.log(xmlStructure);
console.log('');

// Example 7: Common adjustment values
console.log('Example 7: Common Primary Adjustment Values');
console.log('-------------------------------------------');
const adjustments = [
  { value: 0.8, desc: '-20% (darker)' },
  { value: 0.9, desc: '-10% (slightly darker)' },
  { value: 1.0, desc: 'Neutral (no change)' },
  { value: 1.1, desc: '+10% (slightly brighter)' },
  { value: 1.2, desc: '+20% (brighter)' }
];

adjustments.forEach(adj => {
  const hex = encodeFloat(adj.value);
  console.log(`${adj.value.toFixed(1)} ${adj.desc.padEnd(25)} -> 0x${hex}`);
});
console.log('');

// Example 8: Understanding varint encoding
console.log('Example 8: Varint Encoding Examples');
console.log('------------------------------------');
const varintExamples = [
  { value: 1, desc: 'Version number' },
  { value: 34, desc: 'Typical nested length' },
  { value: 45, desc: 'Typical body length' },
  { value: 1080, desc: 'HD height' },
  { value: 1920, desc: 'HD width' },
  { value: 2160, desc: 'UHD height' },
  { value: 3840, desc: 'UHD width' }
];

varintExamples.forEach(ex => {
  const hex = encodeVarint(ex.value).toString('hex');
  const bytes = hex.length / 2;
  console.log(`${String(ex.value).padStart(4)} ${ex.desc.padEnd(25)} -> 0x${hex} (${bytes} byte${bytes > 1 ? 's' : ''})`);
});
console.log('');

console.log('=== End of Examples ===');
