#!/usr/bin/env node
/**
 * DRX Analyzer Tool
 *
 * Analyzes DaVinci Resolve DRX files to extract:
 * - All parameter IDs and their values
 * - Corrector types used
 * - Node structure
 * - Unknown/undocumented parameters
 *
 * Usage: node drx-analyzer.js <path-to-drx-file>
 *
 * @module drx-parameters/tools/drx-analyzer
 */

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

// Import known parameters
let KNOWN_PARAMS;
try {
  const paramIds = require('../parameter-ids');
  KNOWN_PARAMS = {};

  // Build reverse lookup from all parameter groups
  for (const [groupName, group] of Object.entries({
    LIFT: paramIds.LIFT,
    GAIN: paramIds.GAIN,
    GAMMA: paramIds.GAMMA,
    OFFSET: paramIds.OFFSET,
    SATURATION: paramIds.SATURATION,
    TEMP_TINT: paramIds.TEMP_TINT,
    CONTRAST: paramIds.CONTRAST,
    LOG_WHEELS: paramIds.LOG_WHEELS,
    HUE: paramIds.HUE,
    LUM_MIX: paramIds.LUM_MIX,
    SAT_VS_SAT: paramIds.SAT_VS_SAT,
    HDR_ZONE: paramIds.HDR_ZONE,
    CURVES: paramIds.CURVES,
  })) {
    for (const [key, id] of Object.entries(group)) {
      KNOWN_PARAMS[id] = `${groupName}.${key}`;
    }
  }
} catch (e) {
  // Fallback if module not found
  KNOWN_PARAMS = {
    100663320: 'LIFT.R',
    100663321: 'LIFT.G',
    100663322: 'LIFT.B',
    100663323: 'LIFT.MASTER',
    100663325: 'GAIN.R',
    100663326: 'GAIN.G',
    100663327: 'GAIN.B',
    100663328: 'GAIN.MASTER',
    100663330: 'GAMMA.R',
    100663331: 'GAMMA.G',
    100663332: 'GAMMA.B',
    100663333: 'GAMMA.MASTER',
    100663421: 'OFFSET.R',
    100663422: 'OFFSET.G',
    100663423: 'OFFSET.B',
    100663301: 'SATURATION.PRIMARY',
    137363470: 'QUALIFIER.HUE_CENTER',
    137363471: 'QUALIFIER.HUE_WIDTH',
    137363472: 'QUALIFIER.HUE_SYM',
    137363473: 'QUALIFIER.HUE_SOFT',
    137363474: 'QUALIFIER.SAT_HIGH',
    137363475: 'QUALIFIER.SAT_LOW',
    137363476: 'QUALIFIER.SAT_HIGH_SOFT',
    137363477: 'QUALIFIER.SAT_LOW_SOFT',
    137363478: 'QUALIFIER.LUM_HIGH',
    137363479: 'QUALIFIER.LUM_LOW',
    137363480: 'QUALIFIER.LUM_HIGH_SOFT',
    137363481: 'QUALIFIER.LUM_LOW_SOFT',
    2248147137: 'CONTRAST',
    2248147136: 'PIVOT',
    2248147221: 'TEMP_TINT.TEMPERATURE',
    2248147222: 'TEMP_TINT.TINT',
    2248147219: 'TEMP_TINT.MIDTONE_DETAIL',
  };
}

// Corrector type names
const CORRECTOR_NAMES = {
  1: 'Primary',
  2: 'Qualifier',           // Was 'Contrast' — corrected 2026-03-22
  3: 'WindowSoftness',      // Was 'SatVsSat' — softness mask shape (0x0870xxxx)
  4: 'PowerWindow',         // Was 'Hue' — corrected 2026-03-22
  5: 'LumMix',
  6: 'Offset',
  9: 'MatteFinesse/HDRZone', // Shared — Matte Finesse (0x0C30xxxx) + HDR zone legacy (0x0C30001B)
  18: 'Curves',
};

// Presence marker IDs
const PRESENCE_MARKERS = {
  0x88300001: 'CONTRAST',
  0x8870001e: 'SATURATION',
  0x88500010: 'HUE',
  0x88b00012: 'LUM_MIX',
  0x88d00014: 'OFFSET',
  0x88f0000d: 'CURVES',
};

// Parse varint
function parseVarint(buf, offset) {
  let val = 0n;
  let shift = 0n;
  while (offset < buf.length) {
    const b = BigInt(buf[offset++]);
    val |= (b & 0x7fn) << shift;
    if (!(b & 0x80n)) break;
    shift += 7n;
  }
  return { value: Number(val), offset };
}

// Decompress ZSTD data
function decompressZstd(compressedData) {
  const tmpIn = `/tmp/drx_analyze_${Date.now()}.zst`;
  const tmpOut = `/tmp/drx_analyze_${Date.now()}.bin`;

  try {
    fs.writeFileSync(tmpIn, compressedData);
    execFileSync('zstd', ['-d', tmpIn, '-o', tmpOut, '-f'], { stdio: 'ignore' });
    const result = fs.readFileSync(tmpOut);
    fs.unlinkSync(tmpIn);
    fs.unlinkSync(tmpOut);
    return result;
  } catch (e) {
    try { fs.unlinkSync(tmpIn); } catch {}
    try { fs.unlinkSync(tmpOut); } catch {}
    return null;
  }
}

// Extract parameters from binary data
function extractParameters(buf) {
  const params = [];
  const correctors = [];
  const unknownIds = new Set();

  // Search for parameter patterns
  for (let i = 0; i < buf.length - 2; i++) {
    // Look for corrector type markers (0x0a followed by length, then 0x08 type)
    if (buf[i] === 0x0a && buf[i + 2] === 0x08) {
      const len = buf[i + 1];
      if (len > 5 && len < 150) {
        const typeResult = parseVarint(buf, i + 3);
        if (typeResult.value >= 1 && typeResult.value <= 20) {
          correctors.push({
            type: typeResult.value,
            name: CORRECTOR_NAMES[typeResult.value] || `Unknown(${typeResult.value})`,
            offset: i,
          });
        }
      }
    }

    // Look for parameter blocks (0x1a length 0x08 paramId)
    if (buf[i] === 0x1a) {
      const len = buf[i + 1];
      if (len > 5 && len < 25 && buf[i + 2] === 0x08) {
        const paramResult = parseVarint(buf, i + 3);
        const paramId = paramResult.value;

        // Check if this looks like a valid parameter ID
        const isValidRange =
          (paramId >= 100663296 && paramId < 100664000) || // Primary
          (paramId >= 137363456 && paramId < 137364000) || // Contrast
          (paramId >= 139460608 && paramId < 139461000) || // Hue
          (paramId >= 147849216 && paramId < 147850000) || // LumMix
          (paramId >= 149946368 && paramId < 149947000) || // SatVsSat
          (paramId >= 204472320 && paramId < 205521000) || // Curves/HDR
          (paramId >= 2248147000 && paramId < 2248148000); // Temp/Tint (negative)

        if (isValidRange) {
          // Try to find float value
          let value = null;
          const searchEnd = Math.min(i + 2 + len, buf.length - 4);
          for (let j = paramResult.offset; j < searchEnd; j++) {
            if (buf[j] === 0x0d) { // fixed32 marker
              value = buf.readFloatLE(j + 1);
              break;
            }
          }

          const name = KNOWN_PARAMS[paramId];
          if (!name) {
            unknownIds.add(paramId);
          }

          params.push({
            id: paramId,
            hex: '0x' + paramId.toString(16),
            name: name || 'UNKNOWN',
            value,
            offset: i,
          });
        }
      }
    }

    // Look for presence markers
    if (buf[i] === 0x08) {
      const result = parseVarint(buf, i + 1);
      const markerId = result.value;
      if (PRESENCE_MARKERS[markerId]) {
        params.push({
          id: markerId,
          hex: '0x' + markerId.toString(16),
          name: `PRESENCE_${PRESENCE_MARKERS[markerId]}`,
          value: null,
          offset: i,
          isPresenceMarker: true,
        });
      }
    }
  }

  return { params, correctors, unknownIds };
}

// Parse DRX file
function analyzeDRX(filePath) {
  console.log('='.repeat(60));
  console.log('DRX ANALYZER');
  console.log('='.repeat(60));
  console.log('');
  console.log('File:', filePath);
  console.log('');

  const content = fs.readFileSync(filePath, 'utf8');

  // Check if it's XML format
  if (content.startsWith('<?xml')) {
    console.log('Format: XML (Resolve 18+)');

    // Extract metadata
    const labelMatch = content.match(/<Label>([^<]+)<\/Label>/);
    const widthMatch = content.match(/<Width>(\d+)<\/Width>/);
    const heightMatch = content.match(/<Height>(\d+)<\/Height>/);
    const tcMatch = content.match(/<RecTC>([^<]+)<\/RecTC>/);

    if (labelMatch) console.log('Label:', labelMatch[1]);
    if (widthMatch && heightMatch) console.log('Resolution:', widthMatch[1] + 'x' + heightMatch[1]);
    if (tcMatch) console.log('Timecode:', tcMatch[1]);
    console.log('');

    // Extract Body elements
    const bodyMatches = content.matchAll(/<Body>([^<]+)<\/Body>/g);
    let versionNum = 0;

    for (const match of bodyMatches) {
      versionNum++;
      console.log('-'.repeat(40));
      console.log(`VERSION ${versionNum}`);
      console.log('-'.repeat(40));

      const hexData = match[1];
      const buf = Buffer.from(hexData, 'hex');

      // Check for ZSTD compression (magic: 28 B5 2F FD)
      const isZstd = buf.length > 5 && buf.slice(1, 5).toString('hex') === '28b52ffd';

      let bodyData;
      if (isZstd) {
        console.log('Compression: ZSTD');
        bodyData = decompressZstd(buf.slice(1));
        if (!bodyData) {
          console.log('ERROR: Failed to decompress ZSTD data');
          continue;
        }
        console.log('Decompressed size:', bodyData.length, 'bytes');
      } else {
        bodyData = buf;
        console.log('Compression: None');
        console.log('Size:', buf.length, 'bytes');
      }

      console.log('');

      // Extract parameters
      const { params, correctors, unknownIds } = extractParameters(bodyData);

      // Show correctors
      if (correctors.length > 0) {
        console.log('CORRECTOR TYPES:');
        const uniqueCorrectors = [...new Map(correctors.map(c => [c.type, c])).values()];
        for (const c of uniqueCorrectors) {
          console.log(`  - Type ${c.type}: ${c.name}`);
        }
        console.log('');
      }

      // Show parameters
      if (params.length > 0) {
        console.log('PARAMETERS:');
        console.log('');
        console.log('| ID | Hex | Name | Value |');
        console.log('|----|-----|------|-------|');

        for (const p of params) {
          const valueStr = p.value !== null ? p.value.toFixed(6) : 'N/A';
          const marker = p.isPresenceMarker ? ' [marker]' : '';
          console.log(`| ${p.id} | ${p.hex} | ${p.name}${marker} | ${valueStr} |`);
        }
        console.log('');
      }

      // Show unknown IDs
      if (unknownIds.size > 0) {
        console.log('UNKNOWN PARAMETER IDS (need documentation):');
        for (const id of unknownIds) {
          console.log(`  - ${id} (0x${id.toString(16)})`);
        }
        console.log('');
      }
    }
  } else {
    console.log('Format: Binary (older format)');
    const buf = fs.readFileSync(filePath);

    // Try ZSTD decompression
    let bodyData = buf;
    if (buf.slice(0, 4).toString('hex') === '28b52ffd') {
      bodyData = decompressZstd(buf);
      if (!bodyData) {
        console.log('ERROR: Failed to decompress');
        return;
      }
    }

    const { params, correctors, unknownIds } = extractParameters(bodyData);

    // Output results
    if (correctors.length > 0) {
      console.log('CORRECTOR TYPES:');
      for (const c of correctors) {
        console.log(`  - Type ${c.type}: ${c.name}`);
      }
      console.log('');
    }

    if (params.length > 0) {
      console.log('PARAMETERS:');
      for (const p of params) {
        const valueStr = p.value !== null ? p.value.toFixed(6) : 'N/A';
        console.log(`  ${p.name} (${p.hex}): ${valueStr}`);
      }
    }

    if (unknownIds.size > 0) {
      console.log('');
      console.log('UNKNOWN IDS:', [...unknownIds].map(id => `0x${id.toString(16)}`).join(', '));
    }
  }

  console.log('');
  console.log('='.repeat(60));
}

// Main
if (process.argv.length < 3) {
  console.log('Usage: node drx-analyzer.js <path-to-drx-file>');
  process.exit(1);
}

analyzeDRX(process.argv[2]);
