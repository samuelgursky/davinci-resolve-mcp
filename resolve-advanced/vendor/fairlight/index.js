/**
 * Fairlight Bus Routing Patcher
 *
 * Modifies DaVinci Resolve's FLStudioModelBA binary blob to configure
 * Fairlight audio bus routing directly in the project database.
 *
 * This is the database-level companion to fairlight-automation.js (which uses
 * macOS Accessibility API). This module works when Resolve is NOT running,
 * by patching the SQLite database directly.
 *
 * Format Knowledge (reverse-engineered):
 *   - FLStudioModelBA lives in Sm2Sequence.FieldsBlob (KV type-12 blob)
 *   - Raw blob: 4-byte u32BE decompressed size + zlib body
 *   - Decompressed: ~400-550KB AdrDatabase format with 7 sections
 *   - Sections 0-5 are FIXED SIZE across all projects (281,839 bytes total)
 *   - Section 6 (offset 281,839+) contains all bus/track configuration
 *   - Bus definition table at offset 281,907: u32LE count + per-bus records
 *   - Bus names stored as id=0xBC records near end of Section 6
 *   - Per-bus property records follow bus names (0xBD, 0xBE, 0xDE, etc.)
 *
 * @module fairlight-bus-patcher
 */

const zlib = require('zlib');

// Fixed offsets (verified across 16+ projects, all Resolve versions)
const SECTION_6_OFFSET = 281839;
const BUS_TABLE_OFFSET = 281907; // sec6 + 68
const BUS_TYPE_AUDIO = 7;

// Bus format → channel count mapping
const FORMAT_CHANNELS = {
  mono: 1,
  stereo: 2,
  '5.1': 6,
  '5.1film': 6,
  '7.1': 8,
  '7.1.4': 16,
};
const CHANNELS_FORMAT = { 1: 'mono', 2: 'stereo', 6: '5.1', 8: '7.1', 16: '7.1.4' };

// ============================================================
// FieldsBlob KV Codec
// ============================================================

/**
 * Parse FieldsBlob KV binary format into entries array.
 * Each entry: { key, typeCode, rawValue (Buffer) }
 *
 * Format: u32BE(version=1) + u32BE(count) + entries
 * Entry: u32BE(keyLen) + utf16be(key) + u32BE(typeCode) + u8(pad=0) + value
 * Types: 1=bool(1B), 2=u32(4B), 3=f64(8B), 4=i64(8B), 10=string(4+N), 12=blob(4+N)
 */
function parseFieldsBlob(buf) {
  const version = buf.readUInt32BE(0);
  const count = buf.readUInt32BE(4);
  const entries = [];
  let offset = 8;

  for (let i = 0; i < count; i++) {
    const keyLen = buf.readUInt32BE(offset); offset += 4;
    let key = '';
    for (let j = 0; j < keyLen; j += 2) {
      key += String.fromCharCode(buf.readUInt16BE(offset + j));
    }
    offset += keyLen;

    const typeCode = buf.readUInt32BE(offset); offset += 4;
    offset += 1; // pad byte

    let valueSize;
    switch (typeCode) {
      case 1: valueSize = 1; break;
      case 2: valueSize = 4; break;
      case 3: case 4: valueSize = 8; break;
      case 10: case 12:
        valueSize = 4 + buf.readUInt32BE(offset);
        break;
      default:
        throw new Error(`Unknown FieldsBlob type code: ${typeCode} for key "${key}"`);
    }

    entries.push({ key, typeCode, rawValue: buf.slice(offset, offset + valueSize) });
    offset += valueSize;
  }

  return { version, entries };
}

/**
 * Encode entries array back to FieldsBlob KV binary format.
 */
function encodeFieldsBlob(entries) {
  const parts = [];
  const header = Buffer.alloc(8);
  header.writeUInt32BE(1, 0); // version
  header.writeUInt32BE(entries.length, 4);
  parts.push(header);

  for (const e of entries) {
    const keyBuf = Buffer.alloc(e.key.length * 2);
    for (let i = 0; i < e.key.length; i++) keyBuf.writeUInt16BE(e.key.charCodeAt(i), i * 2);
    const keyLenBuf = Buffer.alloc(4);
    keyLenBuf.writeUInt32BE(keyBuf.length, 0);
    parts.push(keyLenBuf, keyBuf);

    const typeBuf = Buffer.alloc(4);
    typeBuf.writeUInt32BE(e.typeCode, 0);
    parts.push(typeBuf, Buffer.from([0x00])); // type + pad

    parts.push(e.rawValue);
  }

  return Buffer.concat(parts);
}

// ============================================================
// FLStudioModelBA Codec
// ============================================================

/**
 * Decompress FLStudioModelBA raw blob.
 * @param {Buffer} rawBlob - The raw blob (4-byte header + zlib)
 * @returns {Buffer} Decompressed AdrDatabase data
 */
function decompressFLModel(rawBlob) {
  const expectedSize = rawBlob.readUInt32BE(0);
  const data = zlib.inflateSync(rawBlob.slice(4));
  if (data.length !== expectedSize) {
    throw new Error(`FLStudioModelBA size mismatch: header says ${expectedSize}, got ${data.length}`);
  }
  return data;
}

/**
 * Compress AdrDatabase data into FLStudioModelBA raw blob.
 * @param {Buffer} data - Decompressed AdrDatabase data
 * @returns {Buffer} Raw blob (4-byte header + zlib)
 */
function compressFLModel(data) {
  const header = Buffer.alloc(4);
  header.writeUInt32BE(data.length, 0);
  const compressed = zlib.deflateSync(data);
  return Buffer.concat([header, compressed]);
}

// ============================================================
// Bus Configuration Reader
// ============================================================

/**
 * Read bus configuration from decompressed FLStudioModelBA.
 * @param {Buffer} data - Decompressed AdrDatabase data
 * @returns {{ buses: Array<{id,type,channels,name}>, busNameOffset: number }}
 */
function readBusConfig(data) {
  // Verify Section 6 marker
  const marker = data.readUInt32LE(SECTION_6_OFFSET);
  if (marker !== 0x77668866) {
    throw new Error('Section 6 marker not found at expected offset ' + SECTION_6_OFFSET);
  }

  // Read bus definition table
  const busCount = data.readUInt32LE(BUS_TABLE_OFFSET);
  if (busCount < 0 || busCount > 32) {
    throw new Error('Invalid bus count: ' + busCount);
  }

  const buses = [];
  let off = BUS_TABLE_OFFSET + 4;
  for (let i = 0; i < busCount; i++) {
    buses.push({
      id: data.readUInt16LE(off),
      type: data.readUInt16LE(off + 2),
      channels: data.readUInt32LE(off + 4),
    });
    off += 8;
  }

  // Find bus name record (flag=1, id=0xBC with nameCount === busCount)
  const bcPattern = Buffer.from([0x01, 0x00, 0x00, 0x00, 0xbc, 0x00, 0x00, 0x00]);
  let busNameOffset = -1;
  let searchFrom = SECTION_6_OFFSET + 10000;

  while (searchFrom < data.length) {
    const idx = data.indexOf(bcPattern, searchFrom);
    if (idx === -1) break;
    const nameCount = data.readUInt32LE(idx + 8);
    if (nameCount === busCount) {
      const strLen = data.readUInt32LE(idx + 12);
      if (strLen > 0 && strLen < 200) {
        busNameOffset = idx;
        break;
      }
    }
    searchFrom = idx + 8;
  }

  // Read bus names
  if (busNameOffset >= 0) {
    let strOff = busNameOffset + 12;
    for (let i = 0; i < busCount; i++) {
      const len = data.readUInt32LE(strOff);
      if (len <= 0 || len > 200 || strOff + 4 + len > data.length) break;
      buses[i].name = data.slice(strOff + 4, strOff + 4 + len).toString('ascii').replace(/\0/g, '');
      strOff += 4 + len;
    }
  }

  return { buses, busNameOffset, busCount };
}

/**
 * Read complete Fairlight model info from a project database.
 * @param {Database} db - better-sqlite3 database instance
 * @returns {{ busFormat, buses, data, rawBlob, fieldsBlob, entries }}
 */
function readFromDatabase(db) {
  const row = db.prepare('SELECT FieldsBlob FROM Sm2Sequence WHERE FieldsBlob IS NOT NULL').get();
  if (!row) throw new Error('No Sm2Sequence with FieldsBlob found');

  const fieldsBlobBuf = Buffer.from(row.FieldsBlob);
  const { entries } = parseFieldsBlob(fieldsBlobBuf);

  let busFormat = null;
  let rawBlob = null;
  let data = null;

  for (const e of entries) {
    if (e.key === 'FirstMainBusFormat') {
      busFormat = e.rawValue.readUInt32BE(0);
    }
    if (e.key === 'FLStudioModelBA') {
      rawBlob = e.rawValue.slice(4); // skip size prefix
      data = decompressFLModel(rawBlob);
    }
  }

  if (!data) throw new Error('No FLStudioModelBA found in FieldsBlob');

  const busConfig = readBusConfig(data);

  return {
    busFormat,
    buses: busConfig.buses,
    data,
    rawBlob,
    fieldsBlobBuf,
    entries,
    busNameOffset: busConfig.busNameOffset,
  };
}

// ============================================================
// Bus Configuration Writer (Template Transplant)
// ============================================================

/**
 * Apply a routing template to a project database.
 *
 * Strategy: transplant the entire decompressed FLStudioModelBA from the
 * template, then patch bus names and track names to match the target config.
 *
 * @param {Database} db - better-sqlite3 database (writable)
 * @param {Buffer} templateData - Decompressed FLStudioModelBA from template project
 * @param {Object} [options]
 * @param {string[]} [options.busNames] - Bus names to set (replaces template names)
 * @param {number} [options.busFormat] - FirstMainBusFormat value to set
 * @returns {{ success: boolean, details: string }}
 */
function applyTemplate(db, templateData, options = {}) {
  // Read existing FieldsBlob
  const row = db.prepare('SELECT FieldsBlob FROM Sm2Sequence WHERE FieldsBlob IS NOT NULL').get();
  if (!row) throw new Error('No Sm2Sequence with FieldsBlob found');

  const fieldsBlobBuf = Buffer.from(row.FieldsBlob);
  const { entries } = parseFieldsBlob(fieldsBlobBuf);

  let patchedData = Buffer.from(templateData);

  // Patch bus names if provided
  if (options.busNames) {
    const config = readBusConfig(patchedData);
    if (config.busNameOffset >= 0) {
      patchedData = patchBusNames(patchedData, config, options.busNames);
    }
  }

  // Update AdrDatabase size field (offset 8, u32LE = total size - 12)
  patchedData.writeUInt32LE(patchedData.length - 12, 8);

  // Compress
  const newRawBlob = compressFLModel(patchedData);

  // Build new rawValue for the FLStudioModelBA entry (size prefix + blob)
  const newRawValue = Buffer.alloc(4 + newRawBlob.length);
  newRawValue.writeUInt32BE(newRawBlob.length, 0);
  newRawBlob.copy(newRawValue, 4);

  // Update entries
  const newEntries = entries.map(e => {
    if (e.key === 'FLStudioModelBA') {
      return { ...e, rawValue: newRawValue };
    }
    if (e.key === 'FirstMainBusFormat' && options.busFormat !== undefined) {
      const val = Buffer.alloc(4);
      val.writeUInt32BE(options.busFormat, 0);
      return { ...e, rawValue: val };
    }
    return e;
  });

  // Encode new FieldsBlob
  const newFieldsBlob = encodeFieldsBlob(newEntries);

  // Write to database
  db.prepare('UPDATE Sm2Sequence SET FieldsBlob = ? WHERE FieldsBlob IS NOT NULL').run(newFieldsBlob);

  return {
    success: true,
    details: `Applied template: ${patchedData.length}B decompressed, ${newRawBlob.length}B compressed`,
  };
}

/**
 * Patch bus names in a decompressed FLStudioModelBA blob.
 * Because names are variable-length, this may change the blob size.
 *
 * @param {Buffer} data - Decompressed AdrDatabase data
 * @param {{ busNameOffset: number, busCount: number }} config - Current bus config
 * @param {string[]} newNames - New bus names
 * @returns {Buffer} New decompressed data with patched names
 */
function patchBusNames(data, config, newNames) {
  if (config.busNameOffset < 0) return data;

  // Read current names to find the exact byte range to replace
  let off = config.busNameOffset + 12; // skip flag(4) + id(4) + count(4)
  const oldNameStart = off;
  for (let i = 0; i < config.busCount; i++) {
    const len = data.readUInt32LE(off);
    if (len <= 0 || len > 200) break;
    off += 4 + len;
  }
  const oldNameEnd = off;
  const oldNameBytes = data.slice(oldNameStart, oldNameEnd);

  // Build new name bytes
  const nameParts = [];
  for (const name of newNames) {
    const lenBuf = Buffer.alloc(4);
    lenBuf.writeUInt32LE(name.length, 0);
    nameParts.push(lenBuf, Buffer.from(name, 'ascii'));
  }
  const newNameBytes = Buffer.concat(nameParts);

  // Splice: before + new names + after
  const before = data.slice(0, oldNameStart);
  const after = data.slice(oldNameEnd);
  const result = Buffer.concat([before, newNameBytes, after]);

  // Update the name count if it changed
  if (newNames.length !== config.busCount) {
    result.writeUInt32LE(newNames.length, config.busNameOffset + 8);
  }

  return result;
}

// ============================================================
// Template Management
// ============================================================

/**
 * Export a routing template from a configured project.
 * @param {Database} db - better-sqlite3 database (readonly)
 * @returns {Object} Template object (JSON-serializable)
 */
function exportTemplate(db) {
  const model = readFromDatabase(db);
  const config = readBusConfig(model.data);

  return {
    version: 1,
    buses: config.buses.map(b => ({
      id: b.id,
      type: b.type,
      channels: b.channels,
      format: CHANNELS_FORMAT[b.channels] || b.channels + 'ch',
      name: b.name || 'Bus ' + (b.id + 1),
    })),
    busFormat: model.busFormat,
    blobSize: model.data.length,
    blob: model.data.toString('base64'),
  };
}

/**
 * Import a routing template from JSON and apply it to a project.
 * @param {Database} db - better-sqlite3 database (writable)
 * @param {Object} template - Template object from exportTemplate()
 * @param {Object} [options]
 * @param {string[]} [options.busNames] - Override bus names
 * @returns {{ success: boolean, details: string }}
 */
function importTemplate(db, template, options = {}) {
  const templateData = Buffer.from(template.blob, 'base64');
  return applyTemplate(db, templateData, {
    busNames: options.busNames || template.buses.map(b => b.name),
    busFormat: template.busFormat,
  });
}

// ============================================================
// Database Safety — Backup & Restore (Phase 3)
// ============================================================

const fsSafety = require('fs');
const pathSafety = require('path');

/**
 * Backup the FieldsBlob for a timeline before any write operation.
 *
 * Writes the raw FieldsBlob bytes to a timestamped backup file in
 * <dbDir>/.fairlight-backup/<timelineName>_<timestamp>.blob
 *
 * @param {Object} db - better-sqlite3 database instance
 * @param {string} timelineName - Timeline to back up
 * @returns {string} Path to the backup file
 */
function backupFieldsBlob(db, timelineName) {
  const row = db.prepare(`
    SELECT s.FieldsBlob, t.Name as tlName
    FROM Sm2Sequence s LEFT JOIN Sm2Timeline t ON s.Sm2Timeline_id = t.Sm2Timeline_id
    WHERE t.Name = ? LIMIT 1
  `).get(timelineName);

  if (!row || !row.FieldsBlob) {
    throw new Error(`Cannot backup: timeline not found or no FieldsBlob: ${timelineName}`);
  }

  // Determine backup directory from database path
  const dbPath = db.name; // better-sqlite3 exposes .name as the file path
  const dbDir = pathSafety.dirname(dbPath);
  const backupDir = pathSafety.join(dbDir, '.fairlight-backup');
  fsSafety.mkdirSync(backupDir, { recursive: true });

  // Sanitize timeline name for filename
  const safeName = timelineName.replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 80);
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const backupPath = pathSafety.join(backupDir, `${safeName}_${timestamp}.blob`);

  fsSafety.writeFileSync(backupPath, Buffer.from(row.FieldsBlob));
  return backupPath;
}

/**
 * Restore a FieldsBlob from a backup file.
 *
 * @param {Object} db - better-sqlite3 database instance (writable)
 * @param {string} backupPath - Path to the .blob backup file
 * @param {string} timelineName - Timeline to restore to
 * @returns {{ success: boolean, restoredBytes: number }}
 */
function restoreFieldsBlob(db, backupPath, timelineName) {
  if (!fsSafety.existsSync(backupPath)) {
    throw new Error(`Backup file not found: ${backupPath}`);
  }

  const backupData = fsSafety.readFileSync(backupPath);

  const targetRow = db.prepare(`
    SELECT s.Sm2Sequence_id
    FROM Sm2Sequence s LEFT JOIN Sm2Timeline t ON s.Sm2Timeline_id = t.Sm2Timeline_id
    WHERE t.Name = ? LIMIT 1
  `).get(timelineName);

  if (!targetRow) {
    throw new Error(`Target timeline not found: ${timelineName}`);
  }

  const result = db.prepare('UPDATE Sm2Sequence SET FieldsBlob = ? WHERE Sm2Sequence_id = ?')
    .run(backupData, targetRow.Sm2Sequence_id);

  return {
    success: result.changes > 0,
    restoredBytes: backupData.length,
  };
}

// ============================================================
// Dynamic Bus Expansion Engine
// ============================================================
// Expands bus configuration from any source blob to any target layout.
// Uses 0xBC-anchored zone detection (verified across 35 projects).
// The bus property zone contains exactly 303 records (302 property + 1 name).

/**
 * Find the 0xBC bus name record for a given bus count.
 * @param {Buffer} data - Decompressed AdrDatabase
 * @param {number} busCount - Expected bus count
 * @returns {number} Offset of the 0xBC record, or -1 if not found
 */
function findBusNameRecord(data, busCount) {
  const bcPattern = Buffer.from([0x01, 0x00, 0x00, 0x00, 0xBC, 0x00, 0x00, 0x00]);
  let searchFrom = SECTION_6_OFFSET + 10000;
  while (searchFrom < data.length) {
    const idx = data.indexOf(bcPattern, searchFrom);
    if (idx === -1) return -1;
    const nc = data.readUInt32LE(idx + 8);
    if (nc === busCount) {
      const strLen = data.readUInt32LE(idx + 12);
      if (strLen > 0 && strLen < 200) return idx;
    }
    searchFrom = idx + 8;
  }
  return -1;
}

/**
 * Scan the bus property zone for all count=busCount records.
 * Anchored to 0xBC: searches from bcOffset-75000 to bcOffset+10000.
 * @param {Buffer} data - Decompressed AdrDatabase
 * @param {number} busCount - Current bus count to match
 * @param {number} bcOffset - Offset of the 0xBC bus name record
 * @returns {Array<{offset,id,count,dataStart,values,isNames}>}
 */
function findBusZoneRecords(data, busCount, bcOffset) {
  const searchStart = Math.max(BUS_TABLE_OFFSET + 4 + busCount * 8, bcOffset - 75000);
  const searchEnd = Math.min(data.length, bcOffset + 10000);
  const records = [];
  let search = searchStart;

  while (search < searchEnd - 12) {
    if (data.readUInt32LE(search) === 1) {
      const id = data.readUInt32LE(search + 4);
      const count = data.readUInt32LE(search + 8);
      if (count === busCount && id > 0 && id < 0x2000) {
        const dataStart = search + 12;
        if (id === 0xBC) {
          records.push({ offset: search, id, count, dataStart, values: [], isNames: true });
          let off = dataStart;
          for (let i = 0; i < count; i++) {
            if (off + 4 > data.length) break;
            const len = data.readUInt32LE(off);
            if (len <= 0 || len > 200) break;
            off += 4 + len;
          }
          search = off;
          continue;
        }
        const values = [];
        for (let i = 0; i < count; i++) {
          if (dataStart + i * 4 + 4 <= data.length) {
            values.push(data.readUInt32LE(dataStart + i * 4));
          }
        }
        records.push({ offset: search, id, count, dataStart, values, isNames: false });
        search = dataStart + count * 4;
        continue;
      }
    }
    search++;
  }
  return records;
}

/**
 * Expand a single property record to a new bus count.
 * @param {Buffer} data - Current blob
 * @param {{offset,id,count,values}} record - Record to expand
 * @param {number} newCount - Target bus count
 * @param {number[]} allValues - Complete value array for all newCount entries
 * @returns {Buffer} New blob with expanded record
 */
function expandRecord(data, record, newCount, allValues) {
  const oldSize = 12 + record.count * 4;
  const newSize = 12 + newCount * 4;
  const newRecord = Buffer.alloc(newSize);
  newRecord.writeUInt32LE(1, 0);
  newRecord.writeUInt32LE(record.id, 4);
  newRecord.writeUInt32LE(newCount, 8);
  for (let i = 0; i < newCount; i++) {
    newRecord.writeUInt32LE(allValues[i], 12 + i * 4);
  }
  return Buffer.concat([data.slice(0, record.offset), newRecord, data.slice(record.offset + oldSize)]);
}

/**
 * Expand bus names to a new set of names.
 * @param {Buffer} data - Current blob
 * @param {number} bcOffset - Offset of the 0xBC record
 * @param {number} oldCount - Current bus count
 * @param {string[]} newNames - New bus names
 * @returns {Buffer} New blob with expanded names
 */
function expandBusNameRecord(data, bcOffset, oldCount, newNames) {
  let off = bcOffset + 12;
  for (let i = 0; i < oldCount; i++) {
    const len = data.readUInt32LE(off);
    if (len <= 0 || len > 200 || off + 4 + len > data.length) break;
    off += 4 + len;
  }
  const oldEnd = off;
  const header = Buffer.alloc(12);
  header.writeUInt32LE(1, 0);
  header.writeUInt32LE(0xBC, 4);
  header.writeUInt32LE(newNames.length, 8);
  const nameParts = [header];
  for (const name of newNames) {
    const lenBuf = Buffer.alloc(4);
    lenBuf.writeUInt32LE(name.length, 0);
    nameParts.push(lenBuf, Buffer.from(name, 'ascii'));
  }
  return Buffer.concat([data.slice(0, bcOffset), Buffer.concat(nameParts), data.slice(oldEnd)]);
}

/**
 * Dynamically expand bus configuration from a source blob to a target layout.
 *
 * This is the core dynamic expansion function. It takes any source blob (with ≥1 bus)
 * and expands it to an arbitrary target layout with any mix of channel formats.
 *
 * @param {Buffer} sourceData - Decompressed AdrDatabase from source timeline
 * @param {Array<{name: string, channels: number}>} targetBuses - Target bus configuration
 * @returns {{ data: Buffer, stats: { oldBusCount, newBusCount, recordsExpanded, oldSize, newSize } }}
 */
function expandBuses(sourceData, targetBuses) {
  let modified = Buffer.from(sourceData);
  const oldConfig = readBusConfig(modified);
  const oldBusCount = oldConfig.busCount;
  const newBusCount = targetBuses.length;

  if (newBusCount === 0) throw new Error('targetBuses must not be empty');

  // Step 1: Find 0xBC anchor
  const bcOffset = findBusNameRecord(modified, oldBusCount);
  if (bcOffset < 0) throw new Error('Bus name record (0xBC) not found in source blob');

  // Step 2: Scan bus zone for all property records
  const busRecords = findBusZoneRecords(modified, oldBusCount, bcOffset);
  const normalRecords = busRecords.filter(r => !r.isNames);

  // Step 3: Expand bus table
  const oldTableSize = 4 + oldBusCount * 8;
  const newTableSize = 4 + newBusCount * 8;
  const newTable = Buffer.alloc(newTableSize);
  newTable.writeUInt32LE(newBusCount, 0);
  for (let i = 0; i < newBusCount; i++) {
    newTable.writeUInt16LE(i, 4 + i * 8);
    newTable.writeUInt16LE(BUS_TYPE_AUDIO, 4 + i * 8 + 2);
    newTable.writeUInt32LE(targetBuses[i].channels, 4 + i * 8 + 4);
  }
  modified = Buffer.concat([
    modified.slice(0, BUS_TABLE_OFFSET),
    newTable,
    modified.slice(BUS_TABLE_OFFSET + oldTableSize),
  ]);
  const tableShift = newTableSize - oldTableSize;

  // Step 4: Expand all property records (bottom-up to preserve offsets)
  const adjustedRecords = normalRecords.map(r => ({
    ...r,
    offset: r.offset + tableShift,
    dataStart: r.dataStart + tableShift,
  }));
  const sortedRecords = [...adjustedRecords].sort((a, b) => b.offset - a.offset);

  for (const rec of sortedRecords) {
    const allValues = [];
    for (let i = 0; i < newBusCount; i++) {
      if (rec.id === 0x01B4) {
        // Channel count per bus — MUST match target format for ALL buses
        allValues.push(targetBuses[i].channels);
      } else if (rec.id === 0x0458) {
        // Strip IDs — continue sequential
        if (i < rec.count) allValues.push(rec.values[i]);
        else allValues.push(rec.values[rec.count - 1] + (i - rec.count + 1));
      } else {
        // Preserve existing values; copy first value for new entries
        if (i < rec.count) allValues.push(rec.values[i]);
        else allValues.push(rec.values[0]);
      }
    }
    modified = expandRecord(modified, rec, newBusCount, allValues);
  }

  // Step 5: Expand bus names
  const bcPatternBuf = Buffer.from([0x01, 0x00, 0x00, 0x00, 0xBC, 0x00, 0x00, 0x00]);
  let newBcOffset = -1;
  let bcSearchStart = Math.max(SECTION_6_OFFSET + 10000, bcOffset + tableShift - 5000);
  while (bcSearchStart < modified.length) {
    const idx = modified.indexOf(bcPatternBuf, bcSearchStart);
    if (idx === -1) break;
    if (modified.readUInt32LE(idx + 8) === oldBusCount) {
      newBcOffset = idx;
      break;
    }
    bcSearchStart = idx + 8;
  }
  if (newBcOffset >= 0) {
    modified = expandBusNameRecord(modified, newBcOffset, oldBusCount, targetBuses.map(b => b.name));
  }

  // Step 6: Update AdrDatabase size field
  modified.writeUInt32LE(modified.length - 12, 8);

  return {
    data: modified,
    stats: {
      oldBusCount,
      newBusCount,
      recordsExpanded: sortedRecords.length,
      busZoneTotal: busRecords.length,
      oldSize: sourceData.length,
      newSize: modified.length,
    },
  };
}

/**
 * Apply dynamic bus expansion to a specific timeline in a project database.
 *
 * @param {Object} db - better-sqlite3 database (writable)
 * @param {string} sourceTimelineName - Timeline to read source blob from
 * @param {string} targetTimelineName - Timeline to write expanded blob to
 * @param {Array<{name: string, channels: number}>} targetBuses - Target bus layout
 * @returns {{ success: boolean, stats: Object }}
 */
function applyBusExpansion(db, sourceTimelineName, targetTimelineName, targetBuses) {
  // Read source blob
  const sourceRow = db.prepare(`
    SELECT s.Sm2Sequence_id, s.FieldsBlob, t.Name as tlName
    FROM Sm2Sequence s LEFT JOIN Sm2Timeline t ON s.Sm2Timeline_id = t.Sm2Timeline_id
    WHERE t.Name = ? LIMIT 1
  `).get(sourceTimelineName);
  if (!sourceRow) throw new Error(`Source timeline not found: ${sourceTimelineName}`);

  // Auto-backup target FieldsBlob before any write (Phase 3C)
  let backupPath = null;
  try {
    backupPath = backupFieldsBlob(db, targetTimelineName);
  } catch {
    // Backup is best-effort — don't block the operation
  }

  // Read target row
  const targetRow = db.prepare(`
    SELECT s.Sm2Sequence_id, s.FieldsBlob, t.Name as tlName
    FROM Sm2Sequence s LEFT JOIN Sm2Timeline t ON s.Sm2Timeline_id = t.Sm2Timeline_id
    WHERE t.Name = ? LIMIT 1
  `).get(targetTimelineName);
  if (!targetRow) throw new Error(`Target timeline not found: ${targetTimelineName}`);

  // Extract source FLStudioModelBA
  const sourceParsed = parseFieldsBlob(Buffer.from(sourceRow.FieldsBlob));
  let sourceData = null;
  for (const e of sourceParsed.entries) {
    if (e.key === 'FLStudioModelBA') {
      const sz = e.rawValue.readUInt32BE(0);
      sourceData = decompressFLModel(e.rawValue.slice(4, 4 + sz));
    }
  }
  if (!sourceData) throw new Error('No FLStudioModelBA in source timeline');

  // Expand
  const { data: expanded, stats } = expandBuses(sourceData, targetBuses);

  // Compress and write to target
  const compressed = compressFLModel(expanded);
  const newRawValue = Buffer.alloc(4 + compressed.length);
  newRawValue.writeUInt32BE(compressed.length, 0);
  compressed.copy(newRawValue, 4);

  // Set FirstMainBusFormat to match first bus
  const newBusFormatVal = Buffer.alloc(4);
  newBusFormatVal.writeUInt32BE(targetBuses[0].channels, 0);

  const targetParsed = parseFieldsBlob(Buffer.from(targetRow.FieldsBlob));
  const newEntries = targetParsed.entries.map(e => {
    if (e.key === 'FLStudioModelBA') return { ...e, rawValue: newRawValue };
    if (e.key === 'FirstMainBusFormat') return { ...e, rawValue: newBusFormatVal };
    return e;
  });

  const newFieldsBlob = encodeFieldsBlob(newEntries);
  const result = db.prepare('UPDATE Sm2Sequence SET FieldsBlob = ? WHERE Sm2Sequence_id = ?')
    .run(newFieldsBlob, targetRow.Sm2Sequence_id);

  return {
    success: result.changes > 0,
    stats,
    backupPath,
  };
}

// ============================================================
// Exports
// ============================================================

module.exports = {
  // Format constants
  FORMAT_CHANNELS,
  CHANNELS_FORMAT,
  SECTION_6_OFFSET,
  BUS_TABLE_OFFSET,

  // Low-level codec
  parseFieldsBlob,
  encodeFieldsBlob,
  decompressFLModel,
  compressFLModel,

  // Bus config operations
  readBusConfig,
  readFromDatabase,

  // Database safety (Phase 3)
  backupFieldsBlob,
  restoreFieldsBlob,

  // Dynamic bus expansion
  findBusNameRecord,
  findBusZoneRecords,
  expandBuses,
  applyBusExpansion,

  // Template operations (legacy)
  exportTemplate,
  importTemplate,
  applyTemplate,
  patchBusNames,
};
