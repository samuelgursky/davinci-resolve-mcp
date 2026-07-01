/**
 * composition-text — read/replace the displayed text of a Fusion Title (Text+)
 * inside a Resolve 21 `<CompositionBA>` blob.
 *
 * Encoding (reverse-engineered, verified by live Resolve 21 import + re-export):
 *   CompositionBA = [4-byte BE uncompressed-length][ zlib( outer ) ]
 *   outer         = <UTF-16BE keyed envelope> + `Composition { … Compressed = true, }`
 *                   + 0x00 + [4-byte LE inner-length][ zlib( innerTools ) ]
 *   innerTools    = the Fusion tool table, including
 *                   `StyledText = Input { Value = "<displayed text>", }`
 *
 * So the on-screen text is two zlib layers deep. setTitleText rewrites the
 * StyledText value and re-frames both layers; decodeTitleText reads it back
 * (tolerant of Resolve's own re-compression framing).
 *
 * @module drp-format/composition-text
 */

const zlib = require('node:zlib');

// Matches the StyledText value, allowing Lua escape sequences (e.g. \" \\ \n) inside it.
const STYLED_RE = /StyledText = Input \{ Value = "((?:[^"\\]|\\.)*)"/;
const COMPRESSED_MARKER = 'Compressed = true, }';

// Fusion stores StyledText as a Lua string. Escape on write, unescape on read so callers
// work with the logical text (quotes, backslashes, newlines all supported).
function luaEscape(s) {
  return String(s)
    .replace(/\\/g, '\\\\')
    .replace(/"/g, '\\"')
    .replace(/\n/g, '\\n')
    .replace(/\r/g, '\\r')
    .replace(/\t/g, '\\t');
}
function luaUnescape(s) {
  return s.replace(/\\(["\\nrt])/g, (_, c) => ({ '"': '"', '\\': '\\', n: '\n', r: '\r', t: '\t' }[c]));
}

// inflate that tolerates trailing bytes after the zlib stream (Resolve re-exports
// embed the nested stream mid-buffer).
function inflateLoose(buf) {
  return zlib.inflateSync(buf, { finishFlush: zlib.constants.Z_SYNC_FLUSH });
}

/**
 * Read the displayed title text from a CompositionBA hex string.
 * Robust to both tool-authored and Resolve-re-exported framing.
 * @param {string} hex
 * @returns {string|null}
 */
function decodeTitleText(hex) {
  const b = Buffer.from(hex, 'hex');
  let outer = null;
  for (const start of [4, 0]) {
    try { outer = inflateLoose(b.subarray(start)); break; } catch { /* try next */ }
  }
  if (!outer) return null;

  const buffers = [outer];
  // Scan for nested zlib streams (78 01 / 78 9c / 78 da) and decompress each.
  for (let i = 0; i < outer.length - 1; i += 1) {
    if (outer[i] === 0x78 && (outer[i + 1] === 0x01 || outer[i + 1] === 0x9c || outer[i + 1] === 0xda)) {
      try { buffers.push(inflateLoose(outer.subarray(i))); } catch { /* not a stream here */ }
    }
  }
  const text = Buffer.concat(buffers).toString('utf8');
  const m = text.match(STYLED_RE);
  return m ? luaUnescape(m[1]) : null;
}

/**
 * Return a new CompositionBA hex with the displayed title text replaced.
 * Operates on the template framing (the nested tool stream runs to the end
 * of the outer payload). The replacement text must not contain a double-quote.
 * @param {string} hex
 * @param {string} newText
 * @returns {string}
 */
// Re-frame helper: decompress outer + nested inner zlib, transform the inner Fusion-tool
// text, then re-compress both layers and fix both length prefixes. Used by all setters.
function rewriteInner(hex, transform) {
  const b = Buffer.from(hex, 'hex');
  const outer = zlib.inflateSync(b.subarray(4));

  const marker = outer.lastIndexOf(COMPRESSED_MARKER);
  if (marker < 0) throw new Error('composition-text: composition marker not found (unexpected framing)');
  const zNull = outer.indexOf(0x00, marker);
  if (zNull < 0) throw new Error('composition-text: inner-length delimiter not found');
  const innerLenOff = zNull + 1;
  const nestedOff = innerLenOff + 4;

  const innerText = inflateLoose(outer.subarray(nestedOff)).toString('utf8');
  const inner2 = Buffer.from(transform(innerText), 'utf8');

  const nInner = zlib.deflateSync(inner2, { level: 9 });
  const innerLen = Buffer.alloc(4);
  innerLen.writeUInt32LE(inner2.length, 0);
  const outer2 = Buffer.concat([outer.subarray(0, innerLenOff), innerLen, nInner]);

  const nOuter = zlib.deflateSync(outer2); // default level (matches Resolve's 78 9c outer)
  const outerLen = Buffer.alloc(4);
  outerLen.writeUInt32BE(outer2.length, 0);
  return Buffer.concat([outerLen, nOuter]).toString('hex');
}

// Settable Text+ inputs that exist in the bundled template (Resolve only serializes
// non-default inputs, so these are the ones present to rewrite). key -> { name, type }.
const TITLE_FIELDS = {
  text: { name: 'StyledText', type: 'string' },
  font: { name: 'Font', type: 'string' },
  style: { name: 'Style', type: 'string' },
  size: { name: 'Size', type: 'number' },
  vJustify: { name: 'VerticalJustificationNew', type: 'int' },
  hJustify: { name: 'HorizontalJustificationNew', type: 'int' },
};

function fieldRegex(name, type) {
  const val = type === 'string' ? '"(?:[^"\\\\]|\\\\.)*"' : '[^,}]+';
  return new RegExp(`(${name} = Input \\{ Value = )(${val})`);
}

/**
 * Set one or more Text+ inputs on a CompositionBA blob.
 * @param {string} hex
 * @param {{text?:string,font?:string,style?:string,size?:number,vJustify?:number,hJustify?:number}} inputs
 * @returns {string} new hex
 */
// Set/replace the text color (Red1/Green1/Blue1, 0..1). These inputs aren't serialized in the
// default Text+, so when absent we INJECT them right after StyledText (verified live: Resolve
// accepts and persists them). When present, we replace in place.
function applyColor(t, { r = 1, g = 1, b = 1 }) {
  for (const [name, v] of [['Red1', r], ['Green1', g], ['Blue1', b]]) {
    const val = Number(v);
    if (!Number.isFinite(val) || val < 0 || val > 1) throw new RangeError(`setTitleInputs: color ${name} must be 0..1`);
    const re = new RegExp(`(${name} = Input \\{ Value = )[^,}]+`);
    if (re.test(t)) {
      t = t.replace(re, (_m, pre) => `${pre}${val}`);
    } else {
      // inject after the StyledText input (which always exists)
      t = t.replace(/(StyledText = Input \{ Value = "(?:[^"\\]|\\.)*", \}, )/, (m) => `${m}${name} = Input { Value = ${val}, }, `);
    }
  }
  return t;
}

function setTitleInputs(hex, inputs = {}) {
  const { color, ...simple } = inputs;
  const keys = Object.keys(simple).filter((k) => simple[k] !== undefined && simple[k] !== null);
  for (const k of keys) if (!TITLE_FIELDS[k]) throw new Error(`setTitleInputs: unknown input "${k}"`);
  if (keys.length === 0 && !color) return hex;

  return rewriteInner(hex, (innerText) => {
    let t = innerText;
    for (const k of keys) {
      const { name, type } = TITLE_FIELDS[k];
      let valueStr;
      if (type === 'string') {
        valueStr = `"${luaEscape(String(simple[k]))}"`;
      } else {
        const n = Number(simple[k]);
        if (!Number.isFinite(n)) throw new TypeError(`setTitleInputs: ${k} must be a number`);
        valueStr = type === 'int' ? String(Math.round(n)) : String(n);
      }
      const re = fieldRegex(name, type);
      if (!re.test(t)) throw new Error(`setTitleInputs: input "${name}" not present in composition`);
      t = t.replace(re, (_m, pre) => `${pre}${valueStr}`);
    }
    if (color) t = applyColor(t, color);
    return t;
  });
}

function setTitleText(hex, newText) {
  if (typeof newText !== 'string') throw new TypeError('setTitleText: newText must be a string');
  return setTitleInputs(hex, { text: newText });
}

/**
 * Read all settable Text+ inputs from a CompositionBA blob.
 * @param {string} hex
 * @returns {object} e.g. { text, font, style, size, vJustify, hJustify }
 */
function decodeTitleInputs(hex) {
  const b = Buffer.from(hex, 'hex');
  let outer = null;
  for (const start of [4, 0]) {
    try { outer = inflateLoose(b.subarray(start)); break; } catch { /* try next */ }
  }
  if (!outer) return {};
  const buffers = [outer];
  for (let i = 0; i < outer.length - 1; i += 1) {
    if (outer[i] === 0x78 && (outer[i + 1] === 0x01 || outer[i + 1] === 0x9c || outer[i + 1] === 0xda)) {
      try { buffers.push(inflateLoose(outer.subarray(i))); } catch { /* not a stream */ }
    }
  }
  const text = Buffer.concat(buffers).toString('utf8');
  const out = {};
  for (const [key, { name, type }] of Object.entries(TITLE_FIELDS)) {
    const m = text.match(fieldRegex(name, type));
    if (!m) continue;
    if (type === 'string') out[key] = luaUnescape(m[2].slice(1, -1));
    else out[key] = Number(m[2]);
  }
  const col = {};
  for (const [key, name] of [['r', 'Red1'], ['g', 'Green1'], ['b', 'Blue1']]) {
    const m = text.match(new RegExp(`${name} = Input \\{ Value = ([0-9.]+)`));
    if (m) col[key] = Number(m[1]);
  }
  if (Object.keys(col).length) out.color = col;
  return out;
}

module.exports = { decodeTitleText, setTitleText, setTitleInputs, decodeTitleInputs, TITLE_FIELDS };
