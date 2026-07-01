/**
 * Decode RESOLVEFX/OFX plugin parameter bags back to {pluginId, params}
 * specs (P1.6).
 *
 * Container structure (per drx-generator.js buildOFXToolEntry +
 * drx-parameters.RESOLVEFX comments):
 *
 *   nodeData.F7.F10 (tool list entry — F1 wraps each tool)
 *     F1 = standard node marker (varint, fieldNum 1, value 2)
 *     F2.F21 (OFX container)
 *       F1 = 0x4F4659 ("OFY" marker varint)
 *       F2 = pluginId UTF-8 string
 *       F3 = instanceId UTF-8 string
 *       F4 = enabled varint (1)
 *       F5[] = repeated param entries
 *             F1 = param name UTF-8
 *             F2 = wrapped value: F2 (float64) OR F5 (UTF-8 string)
 *
 * extractOFXTools(toolListBuf | toolListField) returns
 *   Array<{ pluginId, instanceId, enabled, params: {name: value} }>
 *
 * Each `value` is either a number (when F2.F2 was a float64) or a
 * string (when F2.F5 was UTF-8).
 *
 * P2 coverage: tool IDs beyond Film Grain land in the registry as
 * AutoResearch lands them. The extractor doesn't depend on the tool ID
 * registry — it surfaces the raw pluginId string from F2 of the OFX
 * container. Callers can look it up against RESOLVEFX themselves.
 *
 * @module drx-codec/extract-ofx-params
 */

// ─── Mini protobuf reader (CJS-local copy to avoid cross-dep) ────────────

function readVarint(buf, offset) {
  let result = 0n;
  let shift = 0n;
  let cur = offset;
  while (cur < buf.length) {
    const byte = buf[cur++];
    result |= BigInt(byte & 0x7f) << shift;
    if ((byte & 0x80) === 0) return { value: result, next: cur };
    shift += 7n;
  }
  throw new Error('Truncated varint');
}

function readField(buf, offset) {
  const tag = readVarint(buf, offset);
  const tagNum = Number(tag.value);
  const wireType = tagNum & 0x07;
  const fieldNum = tagNum >>> 3;
  let cur = tag.next;
  if (wireType === 0) {
    const v = readVarint(buf, cur);
    return { wireType, fieldNum, value: v.value, next: v.next };
  }
  if (wireType === 5) return { wireType, fieldNum, value: buf.readFloatLE(cur), next: cur + 4 };
  if (wireType === 1) return { wireType, fieldNum, value: buf.readDoubleLE(cur), next: cur + 8 };
  if (wireType === 2) {
    const len = readVarint(buf, cur);
    const start = len.next;
    const end = start + Number(len.value);
    return { wireType, fieldNum, value: buf.slice(start, end), next: end };
  }
  throw new Error(`Unsupported wire type ${wireType}`);
}

function readAllFields(buf) {
  const fields = [];
  let cur = 0;
  while (cur < buf.length) {
    const f = readField(buf, cur);
    fields.push(f);
    cur = f.next;
  }
  return fields;
}

function utf8(buf) {
  return Buffer.isBuffer(buf) ? buf.toString('utf-8') : '';
}

// ─── OFX decoder ─────────────────────────────────────────────────────────

const OFY_MARKER = 0x4F4659;

/**
 * Decode an F5 param-entry buffer to {name, value}.
 * F1 = name (length-delimited UTF-8)
 * F2 = wrapped value (F2 = float64 OR F5 = UTF-8 string)
 */
function decodeParamEntry(entryBuf) {
  let name = '';
  let value = null;
  const fields = readAllFields(entryBuf);
  for (const f of fields) {
    if (f.fieldNum === 1 && f.wireType === 2) {
      name = utf8(f.value);
    } else if (f.fieldNum === 2 && f.wireType === 2) {
      // f.value is the wrapped value buffer; walk it for F2 (float64) or F5 (string).
      const inner = readAllFields(f.value);
      for (const inn of inner) {
        if (inn.fieldNum === 2 && inn.wireType === 1) {
          value = inn.value; // float64
        } else if (inn.fieldNum === 5 && inn.wireType === 2) {
          value = utf8(inn.value);
        }
      }
    }
  }
  return { name, value };
}

/**
 * Decode an OFX container (F2.F21 contents) to one tool record.
 */
function decodeOFXContainer(containerBuf) {
  const fields = readAllFields(containerBuf);
  let marker = null;
  let pluginId = '';
  let instanceId = '';
  let enabled = false;
  const params = {};
  for (const f of fields) {
    if (f.fieldNum === 1 && f.wireType === 0) {
      marker = Number(f.value);
    } else if (f.fieldNum === 2 && f.wireType === 2) {
      pluginId = utf8(f.value);
    } else if (f.fieldNum === 3 && f.wireType === 2) {
      instanceId = utf8(f.value);
    } else if (f.fieldNum === 4 && f.wireType === 0) {
      enabled = Number(f.value) === 1;
    } else if (f.fieldNum === 5 && f.wireType === 2) {
      const { name, value } = decodeParamEntry(f.value);
      if (name) params[name] = value;
    }
  }
  return { marker, pluginId, instanceId, enabled, params };
}

/**
 * Walk a single tool-list entry (F7.F10[i]) looking for the F2.F21 OFX
 * container.
 *
 * Returns null when the entry isn't an OFX entry (e.g., the standard
 * node marker at F1=2 carries no plugin payload).
 */
function decodeToolEntry(entryBuf) {
  if (!Buffer.isBuffer(entryBuf) || entryBuf.length === 0) return null;
  const fields = readAllFields(entryBuf);
  for (const f of fields) {
    if (f.fieldNum === 2 && f.wireType === 2) {
      // F2 wraps F21 container in OFX entries.
      const inner = readAllFields(f.value);
      for (const inn of inner) {
        if (inn.fieldNum === 21 && inn.wireType === 2) {
          const ofx = decodeOFXContainer(inn.value);
          if (ofx.marker === OFY_MARKER) return ofx;
        }
      }
    }
  }
  return null;
}

/**
 * Extract OFX tools from a tool-list buffer (the F7.F10 field value).
 *
 * The F7.F10 field is itself a wrapper around repeated F1 entries.
 * Each F1 entry may be either the standard node marker (no OFX) or
 * an OFX container.
 *
 * @param {Buffer|Object} toolList - raw F10 buffer OR parser-surfaced
 *   { _fields: [...] } structure
 * @returns {Array<{pluginId, instanceId, enabled, params}>}
 */
function extractOFXTools(toolList) {
  const tools = [];

  let entries = [];
  if (Buffer.isBuffer(toolList)) {
    // toolList is the raw F10 buffer. F1 entries are length-delimited.
    const fields = readAllFields(toolList);
    for (const f of fields) {
      if (f.fieldNum === 1 && f.wireType === 2) entries.push(f.value);
    }
  } else if (toolList && Array.isArray(toolList._fields)) {
    for (const f of toolList._fields) {
      if (f.fieldNum === 1 && f.wireType === 2 && Buffer.isBuffer(f.value)) {
        entries.push(f.value);
      }
    }
  } else if (Array.isArray(toolList)) {
    // Caller passed a pre-extracted entries list.
    entries = toolList.filter((b) => Buffer.isBuffer(b));
  } else {
    return tools;
  }

  for (const e of entries) {
    const t = decodeToolEntry(e);
    if (t) tools.push(t);
  }
  return tools;
}

/**
 * Convenience: extract the FIRST OFX tool from a tool list. Many use
 * cases (Film Grain on a node) only have one plugin per node.
 *
 * @returns {Object|null}
 */
function extractOFXParams(toolList) {
  const tools = extractOFXTools(toolList);
  return tools.length > 0 ? tools[0] : null;
}

module.exports = {
  extractOFXParams,
  extractOFXTools,
  _internals: {
    decodeOFXContainer, decodeToolEntry, decodeParamEntry,
    readAllFields, OFY_MARKER,
  },
};
