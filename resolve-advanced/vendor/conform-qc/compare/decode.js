'use strict';

/**
 * compare/decode.js — the default sharp-backed frame loader (an ADAPTER).
 *
 * Decodes an image (path or Buffer) to a normalized grayscale buffer the pure
 * metrics operate on. Handles the fixtures' mixed bit depths (8-bit proxy frames
 * vs 16-bit review renders) by normalizing to 0..1. The comparator core stays
 * pure; this is where the only image dependency (sharp) lives.
 */

const sharp = require('sharp');

/**
 * @param {string|Buffer} input
 * @param {{width:number,height:number}} size
 * @returns {Promise<{data:Float64Array,width:number,height:number}>}
 */
async function decodeGrayNormalized(input, { width, height }) {
  const { data } = await sharp(input)
    .resize(width, height, { fit: 'fill' })
    .greyscale()
    .raw()
    .toBuffer({ resolveWithObject: true });
  const n = width * height;
  const out = new Float64Array(n);
  if (data.length === n * 2) {
    // 16-bit grayscale
    for (let i = 0; i < n; i++) out[i] = data.readUInt16LE(i * 2) / 65535;
  } else {
    for (let i = 0; i < n; i++) out[i] = data[i] / 255;
  }
  return { data: out, width, height };
}

module.exports = { decodeGrayNormalized };
