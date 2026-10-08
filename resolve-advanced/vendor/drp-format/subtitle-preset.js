/** Native subtitle templates' nested Fusion compositions. Patch literal inputs only;
 * never execute Lua or discard the surrounding keyed envelope/tool graph. */
const zlib = require('node:zlib');
const TEMPLATE = 'Templates/Edit/Titles/Subtitles/Animated/Word Highlight';
const INPUTS = {
  font: 'Font', fontStyle: 'Style', size: 'Size', position: 'Center',
  // The macro exposes Clone controls, but TextPlus renders shading element 1
  // using these persisted inputs. Writing the clones alone leaves its fill
  // at the template's default pale yellow (Green1=.92, Blue1=.52).
  textRed: 'Red1', textGreen: 'Green1', textBlue: 'Blue1', textAlpha: 'Alpha1',
  textFillMode: 'Type1',
  highlightRed: 'HighlightColorRed', highlightGreen: 'HighlightColorGreen', highlightBlue: 'HighlightColorBlue',
  outlineRed: 'HOutlineR', outlineGreen: 'HOutlineG', outlineBlue: 'HOutlineB',
  outlineEnabled: 'HOutline', thickness: 'HOutlineThickness',
};
const COMMON_INPUTS = Object.fromEntries(Object.entries(INPUTS).filter(([key]) =>
  ['font', 'fontStyle', 'size', 'position', 'textRed', 'textGreen', 'textBlue', 'textAlpha', 'textFillMode'].includes(key)));
function unpack(blob) {
  const b = Buffer.from(blob);
  const outer = zlib.inflateSync(b.subarray(4), { maxOutputLength: 32 * 1024 * 1024 });
  if (b.readUInt32BE(0) !== outer.length) throw new Error('CompositionBA outer length mismatch');
  const dataStart = outer.indexOf('Composition {');
  if (dataStart < 4 || outer.readUInt32BE(dataStart - 4) !== outer.length - dataStart) {
    throw new Error('unsupported CompositionBA keyed envelope (expected one composition)');
  }
  const marker = outer.indexOf('Compressed = true, }', dataStart);
  if (marker < 0) throw new Error('unsupported uncompressed Fusion composition');
  const lenOffset = outer.indexOf(0, marker) + 1;
  if (lenOffset <= marker || lenOffset + 4 >= outer.length) throw new Error('invalid nested composition delimiter');
  const inner = zlib.inflateSync(outer.subarray(lenOffset + 4), { maxOutputLength: 32 * 1024 * 1024, info: true });
  if (inner.engine.bytesWritten !== outer.length - lenOffset - 4 || inner.buffer.length !== outer.readUInt32LE(lenOffset)) {
    throw new Error('CompositionBA inner length/trailing bytes mismatch');
  }
  const header = outer.subarray(dataStart, lenOffset - 1).toString('utf8');
  const ids = [...header.matchAll(/TEMPLATE_ID\s*=\s*"([^"\r\n]+)"/g)];
  if (ids.length !== 1) throw new Error('composition must have one TEMPLATE_ID');
  return { outer, dataStart, lenOffset, text: inner.buffer.toString('utf8'), templateId: ids[0][1] };
}
// Mask strings/comments while retaining offsets, so braces and input-like text
// inside strings cannot change the target table.
function mask(text) {
  if (/\[(?:=*)\[/.test(text)) throw new Error('unsupported Lua long string in preset');
  return text.replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|--[^\r\n]*/g, (s) => ' '.repeat(s.length));
}
function table(text, pattern) {
  const masked = mask(text), matches = [...masked.matchAll(pattern)];
  if (matches.length !== 1) throw new Error('unsupported/ambiguous subtitle TextPlus tool layout');
  const open = masked.indexOf('{', matches[0].index);
  let depth = 1, close = open + 1;
  for (; close < masked.length && depth; close++) {
    if (masked[close] === '{') depth++;
    if (masked[close] === '}') depth--;
  }
  if (depth) throw new Error('unbalanced Fusion table');
  return { start: open + 1, end: close - 1 };
}
function inputTable(text) {
  const tool = table(text, /\bTemplate\s*=\s*TextPlus\s*\{/g);
  const inputs = table(text.slice(tool.start, tool.end), /\bInputs\s*=\s*\{/g);
  return { start: tool.start + inputs.start, end: tool.start + inputs.end };
}
function literal(value) {
  if (typeof value === 'string') return JSON.stringify(value).replace(/\u2028/g, '\\n').replace(/\u2029/g, '\\n');
  if (Array.isArray(value) && value.length === 2 && value.every(Number.isFinite)) return `{ ${value.join(', ')} }`;
  if (Number.isFinite(value)) return String(value);
  throw new Error('preset input must be a finite number, string, or position pair');
}
function parseLiteral(value) {
  const s = value.trim();
  if (/^"(?:[^"\\]|\\.)*"$/.test(s)) return JSON.parse(s);
  if (/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i.test(s)) return Number(s);
  const vector = /^\{\s*([^,]+),\s*([^,}]+),?\s*\}$/.exec(s);
  if (vector && [Number(vector[1]), Number(vector[2])].every(Number.isFinite)) return [Number(vector[1]), Number(vector[2])];
  throw new Error('input is not a supported literal');
}
function inputRange(text, name) {
  const matches = [...mask(text).matchAll(new RegExp(`\\b${name}\\s*=\\s*Input\\s*\\{`, 'g'))];
  if (!matches.length) return null;
  if (matches.length !== 1) throw new Error(`ambiguous preset input ${name}`);
  return { ...table(text, new RegExp(`\\b${name}\\s*=\\s*Input\\s*\\{`, 'g')), keyStart: matches[0].index };
}
function decodePreset(blob) {
  const u = unpack(blob), values = {};
  if (u.templateId.startsWith('Templates/Edit/Titles/Subtitles/')) {
    const range = inputTable(u.text), inputs = u.text.slice(range.start, range.end);
    for (const [key, name] of Object.entries(u.templateId === TEMPLATE ? INPUTS : COMMON_INPUTS)) {
      const r = inputRange(inputs, name);
      if (!r) continue; // Missing inputs use Resolve's defaults; do not invent values.
      const body = inputs.slice(r.start, r.end), value = /^\s*Value\s*=\s*([\s\S]*?),?\s*$/.exec(body);
      if (value) { try {
        const literal = parseLiteral(value[1].replace(/,\s*$/, ''));
        values[key] = key === 'textFillMode' ? ({0:'solid',1:'image',2:'gradient'}[literal] ?? 'unsupported') : literal;
      } catch { /* animated/expression */ } }
    }
    // TextPlus's observed native Type1 default is solid (0). Unlike font or
    // colour defaults, this enum is needed to distinguish dormant RGB inputs.
    if (!inputRange(inputs,'Type1')) values.textFillMode = 'solid';
  }
  return { templateId: u.templateId, inputs: values,
    parameterEditingSupported: u.templateId.startsWith('Templates/Edit/Titles/Subtitles/'),
    editableInputs: Object.keys(u.templateId === TEMPLATE ? INPUTS
      : u.templateId.startsWith('Templates/Edit/Titles/Subtitles/') ? COMMON_INPUTS : {}) };
}
function setPresetInputs(blob, changes) {
  const u = unpack(blob);
  if (!u.templateId.startsWith('Templates/Edit/Titles/Subtitles/')) throw new Error('not a subtitle template');
  const mapping = u.templateId === TEMPLATE ? INPUTS : COMMON_INPUTS;
  for (const key of Object.keys(changes)) if (!mapping[key]) throw new Error(`unknown or unsupported preset input ${key} for ${u.templateId}`);
  if ('textFillMode' in changes && changes.textFillMode !== 'solid') throw new Error('textFillMode only supports explicit solid fill');
  const current = decodePreset(blob).inputs;
  if (Object.keys(changes).some(key => ['textRed','textGreen','textBlue','textAlpha'].includes(key))
      && current.textFillMode !== 'solid' && changes.textFillMode !== 'solid') {
    throw new Error('Text fill is gradient/image/connected; RGB would be invisible. Supply textFillMode:"solid" explicitly to replace the fill mode');
  }
  if (Object.entries(changes).every(([k, v]) => JSON.stringify(current[k]) === JSON.stringify(v))) return Buffer.from(blob);
  const range = inputTable(u.text);
  let inputs = u.text.slice(range.start, range.end);
  for (const [key, value] of Object.entries(changes)) {
    const name = INPUTS[key];
    if (!name) throw new Error(`unknown preset input ${key}`);
    const r = inputRange(inputs, name), replacement = `${name} = Input { Value = ${literal(key === 'textFillMode' ? 0 : value)}, }, `;
    if (r) {
      const body = inputs.slice(r.start, r.end);
      if (!/^\s*Value\s*=/.test(body) || /\b(?:Expression|SourceOp|Source)\s*=/.test(mask(body))) {
        throw new Error(`refusing to replace connected/animated input ${name}`);
      }
      // Validate the entire body before replacing; preserve unusual inputs by refusing.
      parseLiteral(body.replace(/^\s*Value\s*=\s*/, '').replace(/,\s*$/, ''));
      const tail = inputs.slice(r.end + 1).replace(/^\s*,\s*/, '');
      inputs = inputs.slice(0, r.keyStart) + replacement + tail;
    } else {
      // Resolve can omit the separator after its last input. Prepending a
      // comma-terminated field preserves that valid Lua table unchanged.
      inputs = ` ${replacement}${inputs}`;
    }
  }
  const inner = Buffer.from(u.text.slice(0, range.start) + inputs + u.text.slice(range.end), 'utf8');
  const len = Buffer.alloc(4); len.writeUInt32LE(inner.length);
  const outer = Buffer.concat([u.outer.subarray(0, u.lenOffset), len, zlib.deflateSync(inner, { level: 9 })]);
  outer.writeUInt32BE(outer.length - u.dataStart, u.dataStart - 4);
  const outerLen = Buffer.alloc(4); outerLen.writeUInt32BE(outer.length);
  const result = Buffer.concat([outerLen, zlib.deflateSync(outer)]);
  const back = decodePreset(result);
  for (const [key, value] of Object.entries(changes)) {
    if (JSON.stringify(back.inputs[key]) !== JSON.stringify(value)) throw new Error(`preset readback mismatch: ${key}`);
  }
  return result;
}
module.exports = { decodePreset, setPresetInputs, TEMPLATE, INPUTS };
