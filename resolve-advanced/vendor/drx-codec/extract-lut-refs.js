/**
 * P5.1 — Per-node LUT reference extractor.
 *
 * When a Resolve color node has a LUT attached (Right-click → LUT in the
 * node graph), Resolve stores the LUT identification as two parameters
 * inside a corrector block at the node's F9 position. The existing
 * `extractNodes` parser already surfaces those correctors' parameters,
 * but it only unwraps int/float value envelopes (F1 of the envelope).
 * The LUT path lives in F5 of the envelope (a string), which the
 * generic extractor doesn't reach.
 *
 * This module scans a node's correctors for the NODE_LUT_REF.LUT_PATH
 * param ID, drops into the value envelope to pull the F5 string, and
 * returns the resolved LUT reference. Pairs with `extract-lut-refs`
 * for DRP project-level LUTs (drp-format/extract-lut-refs.js) which
 * surfaces the same shape from a different artifact.
 *
 * REVERSE-ENGINEERED 2026-06-19 (Session 31) from a paired DRX capture:
 *   - no-LUT  → node.F9 contains only F2 (5-byte common tail).
 *   - with-LUT → node.F9 contains an additional F1 corrector that holds
 *                the LUT params, plus the same F2 common tail.
 *
 * @module drx-codec/extract-lut-refs
 */

const drxParams = require('../drx-parameters');

const { NODE_LUT_REF } = drxParams;

/**
 * Read a string from a parameter's value envelope.
 *
 * The DRX parser surfaces param.value as either:
 *   - The raw envelope object (when the envelope's F1 was undefined)
 *   - The unwrapped F1 value (when F1 was set — e.g. floats)
 *
 * For LUT paths, F5 of the envelope carries the string as a length-
 * delimited bytes field. The parser greedily tries to re-parse those
 * bytes as a nested protobuf message (and produces garbage) but
 * preserves the original buffer in `_fields[N].rawValue`. We hunt
 * for field 5 in `_fields` and read the rawValue as UTF-8.
 *
 * Accepts strings directly and Buffer values for robustness against
 * future parser improvements.
 *
 * @param {Object|string|Buffer} value
 * @returns {string|null}
 */
function envelopeToString(value) {
  if (value == null) return null;
  if (typeof value === 'string') return value;
  if (Buffer.isBuffer(value)) return value.toString('utf8');
  if (typeof value !== 'object') return null;
  // Direct F5 access (in case parser improves and surfaces it cleanly).
  if (typeof value.F5 === 'string') return value.F5;
  if (Buffer.isBuffer(value.F5)) return value.F5.toString('utf8');
  // Fall back to scanning _fields for field 5's raw bytes.
  if (Array.isArray(value._fields)) {
    for (const field of value._fields) {
      if (field.fieldNum !== 5) continue;
      if (Buffer.isBuffer(field.rawValue)) return field.rawValue.toString('utf8');
      if (typeof field.rawValue === 'string') return field.rawValue;
      if (field.value && Buffer.isBuffer(field.value)) return field.value.toString('utf8');
      // Nested-parsed value: its own _fields may carry the raw bytes
      // at a wire-type-2 inner field. Drill one level for robustness.
      if (field.value && Array.isArray(field.value._fields)) {
        for (const inner of field.value._fields) {
          if (Buffer.isBuffer(inner.rawValue)) return inner.rawValue.toString('utf8');
        }
      }
    }
  }
  return null;
}

/**
 * Coerce a param.value to a number for SLOT_META (varint payload).
 *
 * @param {Object|number|bigint} value
 * @returns {number|null}
 */
function envelopeToNumber(value) {
  if (value == null) return null;
  if (typeof value === 'number') return value;
  if (typeof value === 'bigint') return Number(value);
  if (typeof value === 'object') {
    if (typeof value.F2 === 'number') return value.F2;
    if (typeof value.F2 === 'bigint') return Number(value.F2);
    if (typeof value.F1 === 'number') return value.F1;
    if (typeof value.F1 === 'bigint') return Number(value.F1);
  }
  return null;
}

/**
 * Extract a per-node LUT reference from a node's correctors list.
 *
 * Scans every corrector in the node for the LUT_PATH param ID.
 * Returns null if no LUT is attached.
 *
 * @param {Object} node — node object from drx-parser's extractNodes,
 *   must have a `correctors` array
 * @returns {{lutPath: string, slotMeta: number|null}|null}
 */
function extractNodeLutRef(node) {
  if (!node || !Array.isArray(node.correctors)) return null;
  for (const corrector of node.correctors) {
    if (!Array.isArray(corrector.parameters)) continue;
    let lutPath = null;
    let slotMeta = null;
    for (const param of corrector.parameters) {
      if (param.id === NODE_LUT_REF.LUT_PATH) {
        lutPath = envelopeToString(param.value);
      } else if (param.id === NODE_LUT_REF.SLOT_META) {
        slotMeta = envelopeToNumber(param.value);
      }
    }
    if (lutPath) {
      return { lutPath, slotMeta };
    }
  }
  return null;
}

/**
 * Extract LUT references from every node in a parsed DRX.
 *
 * Returns one entry per node that carries a LUT. The output shape
 * mirrors `drp-format.extractProjectLUTRefs` so callers (e.g. the
 * clf_lut MCP tool's `extract_refs_from_drx` action) can ingest
 * DRX and DRP LUT refs through the same pipeline.
 *
 * @param {Object} parsedDRX — output of drx-parser.parseDRXContent
 * @returns {Array<{nodeId, nodeIndex, lutPath, slotMeta, source}>}
 */
function extractDrxLutRefs(parsedDRX) {
  if (!parsedDRX || !Array.isArray(parsedDRX.nodes)) return [];
  const refs = [];
  for (const node of parsedDRX.nodes) {
    const ref = extractNodeLutRef(node);
    if (ref) {
      refs.push({
        nodeId: node.id ?? null,
        nodeIndex: node.index ?? null,
        lutPath: ref.lutPath,
        slotMeta: ref.slotMeta,
        source: 'drx_node',
      });
    }
  }
  return refs;
}

module.exports = {
  extractNodeLutRef,
  extractDrxLutRefs,
  _internals: { envelopeToString, envelopeToNumber, NODE_LUT_REF },
};
