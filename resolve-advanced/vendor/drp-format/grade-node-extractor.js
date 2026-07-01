/**
 * DaVinci Resolve Grade Node Extractor
 *
 * Extracts color correction nodes from DRP Body data.
 *
 * @module grade-node-extractor
 */

const AdmZip = require('adm-zip');
const { XMLParser } = require('fast-xml-parser');
const { ZstdCodec } = require('zstd-codec');

/**
 * Known node type identifiers based on Field 9.Field 1.Field 6 patterns
 */
const NODE_TYPES = {
  // Common patterns found in Field 1 of node params
  1: 'Primary Corrector',
  2: 'Contrast',
  3: 'Saturation',
  4: 'Hue',
  5: 'Lum Mix',
  6: 'Offset',
  18: 'Custom Curves',
};

/**
 * Initialize ZSTD codec
 */
let zstdCodec = null;
async function initZstd() {
  if (zstdCodec) return zstdCodec;
  zstdCodec = await new Promise((resolve) => {
    ZstdCodec.run(zstd => resolve(new zstd.Streaming()));
  });
  return zstdCodec;
}

/**
 * Decode a protobuf varint
 */
function decodeVarint(buf, offset) {
  let value = 0;
  let shift = 0;
  let pos = offset;

  while (pos < buf.length) {
    const byte = buf[pos];
    value |= (byte & 0x7f) << shift;
    pos++;
    if ((byte & 0x80) === 0) break;
    shift += 7;
  }

  return { value, bytesRead: pos - offset };
}

/**
 * Parse protobuf message
 */
function parseProtobuf(buf, start, end, depth = 0) {
  const fields = [];
  let offset = start;

  while (offset < end && depth < 10) {
    if (offset >= buf.length) break;

    const tagResult = decodeVarint(buf, offset);
    const tag = tagResult.value;
    offset += tagResult.bytesRead;

    const fieldNum = tag >> 3;
    const wireType = tag & 0x7;

    if (fieldNum === 0 || fieldNum > 1000) break;

    let value;
    let rawBytes;

    switch (wireType) {
      case 0: // Varint
        const varintResult = decodeVarint(buf, offset);
        value = varintResult.value;
        offset += varintResult.bytesRead;
        fields.push({ fieldNum, type: 'varint', value });
        break;

      case 1: // 64-bit
        if (offset + 8 > end) return fields;
        value = buf.readDoubleLE(offset);
        offset += 8;
        fields.push({ fieldNum, type: 'double', value });
        break;

      case 2: // Length-delimited
        const lenResult = decodeVarint(buf, offset);
        const len = lenResult.value;
        offset += lenResult.bytesRead;

        if (len > 50000 || offset + len > end) return fields;

        rawBytes = buf.slice(offset, offset + len);

        // Try to parse as nested protobuf
        let nested = null;
        if (len > 2 && len < 10000) {
          try {
            nested = parseProtobuf(buf, offset, offset + len, depth + 1);
            if (nested.length === 0) nested = null;
          } catch (e) {}
        }

        offset += len;
        fields.push({
          fieldNum,
          type: 'bytes',
          length: len,
          nested,
          raw: rawBytes
        });
        break;

      case 5: // 32-bit
        if (offset + 4 > end) return fields;
        value = buf.readFloatLE(offset);
        offset += 4;
        fields.push({ fieldNum, type: 'float', value });
        break;

      default:
        return fields;
    }
  }

  return fields;
}

/**
 * Extract node data from parsed protobuf
 */
function extractNodes(fields) {
  const nodes = [];
  const connections = [];

  // Find all Field 7 entries (nodes) and Field 8 entries (connections)
  for (const field of fields) {
    if (field.fieldNum === 7 && field.nested) {
      const node = parseNode(field.nested);
      if (node) nodes.push(node);
    } else if (field.fieldNum === 8 && field.nested) {
      const conn = parseConnection(field.nested);
      if (conn) connections.push(conn);
    }
  }

  return { nodes, connections };
}

/**
 * Parse a single node from protobuf fields
 */
function parseNode(fields) {
  const node = {
    id: null,
    index: null,
    posX: null,
    posY: null,
    label: null,
    enabled: true,
    parameters: [],
    timestamp: null
  };

  for (const field of fields) {
    switch (field.fieldNum) {
      case 1:
        node.id = field.value;
        break;
      case 2:
        node.index = field.value;
        break;
      case 4:
        node.posX = field.value;
        break;
      case 5:
        node.posY = field.value;
        break;
      case 6:
        // Label (string bytes)
        if (field.raw) {
          node.label = field.raw.toString('utf-8').replace(/\x00/g, '');
        }
        break;
      case 7:
        node.enabled = field.value === 1;
        break;
      case 9:
        // Node parameters (nested message with corrector settings)
        if (field.nested) {
          node.parameters = extractNodeParameters(field.nested);
        }
        break;
      case 12:
        node.timestamp = field.value;
        break;
    }
  }

  return node.id !== null ? node : null;
}

/**
 * Extract parameters from node's Field 9
 */
function extractNodeParameters(fields) {
  const params = [];

  for (const field of fields) {
    if (field.fieldNum === 1 && field.nested) {
      // Each Field 1 is a corrector type
      const corrector = parseCorrectorParams(field.nested);
      if (corrector) params.push(corrector);
    }
  }

  return params;
}

/**
 * Parse corrector parameters
 */
function parseCorrectorParams(fields) {
  const corrector = {
    type: null,
    typeId: null,
    enabled: true,
    values: []
  };

  for (const field of fields) {
    switch (field.fieldNum) {
      case 1:
        corrector.typeId = field.value;
        corrector.type = NODE_TYPES[field.value] || `Type ${field.value}`;
        break;
      case 3:
        corrector.enabled = field.value === 1;
        break;
      case 6:
        // Nested parameter values
        if (field.nested) {
          corrector.values = extractParameterValues(field.nested);
        } else if (field.raw) {
          // Try to extract floats from raw bytes
          corrector.rawSize = field.length;
        }
        break;
    }
  }

  return corrector.typeId !== null ? corrector : null;
}

/**
 * Extract parameter values (floats/doubles from nested data)
 */
function extractParameterValues(fields) {
  const values = [];

  for (const field of fields) {
    if (field.type === 'float') {
      values.push({ param: field.fieldNum, value: field.value });
    } else if (field.type === 'double') {
      values.push({ param: field.fieldNum, value: field.value });
    } else if (field.nested) {
      // Recurse into nested
      const nested = extractParameterValues(field.nested);
      values.push(...nested);
    }
  }

  return values;
}

/**
 * Parse connection from protobuf fields
 */
function parseConnection(fields) {
  const conn = {
    sourceNode: null,
    targetNode: null,
    sourcePort: null,
    targetPort: null,
    linkIndex: null
  };

  for (const field of fields) {
    switch (field.fieldNum) {
      case 1:
        conn.sourceNode = field.value;
        break;
      case 3:
        conn.targetNode = field.value;
        break;
      case 5:
        conn.sourcePort = field.value;
        break;
      case 6:
        conn.targetPort = field.value;
        break;
      case 7:
        conn.linkIndex = field.value;
        break;
    }
  }

  return conn.sourceNode !== null ? conn : null;
}

/**
 * Decompress and parse grade body data
 */
async function parseGradeBody(hexData) {
  const codec = await initZstd();
  const buf = Buffer.from(hexData, 'hex');

  let data;
  if (buf[0] === 0x81) {
    // ZSTD compressed
    const compressed = new Uint8Array(buf.slice(1));
    data = Buffer.from(codec.decompress(compressed));
  } else if (buf[0] === 0x80) {
    // Uncompressed
    data = buf.slice(1);
  } else {
    throw new Error(`Unknown Body format marker: 0x${buf[0].toString(16)}`);
  }

  // Parse protobuf
  const fields = parseProtobuf(data, 0, data.length, 0);

  // Find the main container (Field 1)
  const mainContainer = fields.find(f => f.fieldNum === 1 && f.nested);
  if (!mainContainer) {
    return { nodes: [], connections: [], raw: fields };
  }

  return extractNodes(mainContainer.nested);
}

/**
 * Extract all grades from a DRP file
 */
async function extractGradesFromDRP(drpPath) {
  const zip = new AdmZip(drpPath);
  const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '@_' });

  const results = [];

  // Find all sequence files
  const entries = zip.getEntries();
  const seqFiles = entries.filter(e =>
    e.entryName.startsWith('SeqContainer/') && e.entryName.endsWith('.xml')
  );

  for (const seqFile of seqFiles) {
    const seqXml = zip.readFile(seqFile).toString('utf-8');
    const parsed = parser.parse(seqXml);

    // Find all clips with Body
    const clips = findClipsWithBody(parsed);

    for (const clip of clips) {
      try {
        const gradeData = await parseGradeBody(clip.body);
        results.push({
          sequence: seqFile.entryName,
          clipPath: clip.path,
          clipId: clip.dbId,
          nodeCount: gradeData.nodes.length,
          connectionCount: gradeData.connections.length,
          nodes: gradeData.nodes,
          connections: gradeData.connections
        });
      } catch (e) {
        results.push({
          sequence: seqFile.entryName,
          clipPath: clip.path,
          clipId: clip.dbId,
          error: e.message
        });
      }
    }
  }

  return results;
}

/**
 * Find all clips with Body data in parsed XML
 */
function findClipsWithBody(obj, path = '', results = []) {
  if (!obj || typeof obj !== 'object') return results;

  // Check for Sm2VideoClip or similar with Body
  if (obj['@_DbId'] && obj.Body && typeof obj.Body === 'string' && obj.Body.length > 10) {
    results.push({
      path,
      dbId: obj['@_DbId'],
      body: obj.Body
    });
  }

  for (const key of Object.keys(obj)) {
    if (!key.startsWith('@_')) {
      findClipsWithBody(obj[key], path ? `${path}.${key}` : key, results);
    }
  }

  return results;
}

/**
 * Format nodes for display
 */
function formatNodesForDisplay(gradeData) {
  const lines = [];

  lines.push(`Nodes (${gradeData.nodes.length}):`);
  for (const node of gradeData.nodes) {
    lines.push(`  Node ${node.id} (index: ${node.index})`);
    if (node.label) lines.push(`    Label: "${node.label}"`);
    lines.push(`    Position: (${node.posX}, ${node.posY})`);
    lines.push(`    Enabled: ${node.enabled}`);

    if (node.parameters.length > 0) {
      lines.push(`    Parameters:`);
      for (const param of node.parameters) {
        lines.push(`      - ${param.type} (enabled: ${param.enabled})`);
        if (param.values.length > 0) {
          const valStr = param.values.slice(0, 5).map(v =>
            `${v.param}=${typeof v.value === 'number' ? v.value.toFixed(4) : v.value}`
          ).join(', ');
          lines.push(`        Values: ${valStr}${param.values.length > 5 ? '...' : ''}`);
        }
      }
    }
  }

  lines.push(`\nConnections (${gradeData.connections.length}):`);
  for (const conn of gradeData.connections) {
    lines.push(`  Node ${conn.sourceNode} -> Node ${conn.targetNode}`);
  }

  return lines.join('\n');
}

// CLI support
if (require.main === module) {
  const drpPath = process.argv[2];
  if (!drpPath) {
    console.log('Usage: node grade-node-extractor.js <file.drp>');
    process.exit(1);
  }

  extractGradesFromDRP(drpPath).then(results => {
    console.log(`\nExtracted grades from ${results.length} clips:\n`);

    for (const result of results.slice(0, 5)) {
      console.log('='.repeat(60));
      console.log(`Clip: ${result.clipId}`);
      console.log(`Sequence: ${result.sequence}`);

      if (result.error) {
        console.log(`Error: ${result.error}`);
      } else {
        console.log(formatNodesForDisplay(result));
      }
      console.log();
    }

    if (results.length > 5) {
      console.log(`... and ${results.length - 5} more clips`);
    }
  }).catch(console.error);
}

module.exports = {
  parseGradeBody,
  extractGradesFromDRP,
  extractNodes,
  parseProtobuf,
  formatNodesForDisplay,
  initZstd
};
