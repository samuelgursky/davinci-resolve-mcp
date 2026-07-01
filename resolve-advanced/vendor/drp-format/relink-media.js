/**
 * relink-media — repoint a Resolve project's media to new file paths, OFFLINE
 * (without Resolve running).
 *
 * Finding (verified live, Resolve 21): Resolve links media by the path stored INSIDE
 * the Media Pool's binary `BtVideoInfo`/`BtAudioInfo` "Clip" blobs, NOT by the timeline
 * clip's plain-text <MediaFilePath>. Editing only the plain text leaves the clip pointing
 * at the old file. And Resolve does NOT re-conform metadata on import — it keeps the
 * blob's cached resolution/duration/fps. So relink = rewrite the blob path (+ the plain
 * text), and the clip comes online (lint: 0 offline) carrying its existing metadata.
 *
 * Blob layout: `[4-byte ?][4-byte BE payload-length][payload]`, where the payload holds
 * the directory and filename as protobuf-style length-delimited fields
 * (`0x0a <varint len> <dir>`, `0x12 <varint len> <filename>`). Rewriting a field updates
 * its varint length and the 4-byte payload-length header by the byte delta.
 *
 * Scope: repoints existing media (keeps the source's cached specs — intended for moved/
 * renamed files or same-spec swaps). It does NOT synthesize metadata for a differently-
 * formatted file; run Resolve's media "Update"/reconform for that.
 *
 * @module drp-format/relink-media
 */

const fs = require('node:fs');
const nodePath = require('node:path');
const JSZip = require('jszip');

function varintEncode(n) {
  const out = [];
  let v = n >>> 0;
  while (v > 0x7f) { out.push((v & 0x7f) | 0x80); v >>>= 7; }
  out.push(v);
  return Buffer.from(out);
}

// Replace a length-delimited field whose VALUE is `oldVal` with `newVal`, rewriting the
// preceding minimal varint length. Returns { buf, delta, found }.
function replaceLenField(buf, oldVal, newVal) {
  const i = buf.indexOf(oldVal);
  if (i < 0) return { buf, delta: 0, found: false };
  const oldLen = varintEncode(oldVal.length);
  const lenStart = i - oldLen.length;
  if (lenStart < 0 || !buf.subarray(lenStart, i).equals(oldLen)) {
    // Length prefix doesn't match the minimal varint we expect — refuse rather than corrupt.
    return { buf, delta: 0, found: false };
  }
  const newLen = varintEncode(newVal.length);
  const out = Buffer.concat([buf.subarray(0, lenStart), newLen, newVal, buf.subarray(i + oldVal.length)]);
  return { buf: out, delta: out.length - buf.length, found: true };
}

// Rewrite dir + filename inside one media blob and fix its 4-byte BE payload-length header.
function relinkBlob(blob, fromDir, fromName, toDir, toName) {
  let buf = blob;
  let delta = 0;
  let touched = false;
  for (const [oldV, newV] of [[fromDir, toDir], [fromName, toName]]) {
    if (oldV.equals(newV)) continue;
    const r = replaceLenField(buf, oldV, newV);
    buf = r.buf; delta += r.delta; touched = touched || r.found;
  }
  if (!touched) return { blob, changed: false };
  // Header payload length lives at bytes [4,8) big-endian.
  if (buf.length >= 8) {
    const hdr = buf.readUInt32BE(4);
    buf.writeUInt32BE(hdr + delta, 4);
  }
  return { blob: buf, changed: true };
}

/**
 * Relink one or more media files to new paths across a .drp, offline.
 *
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {Array<{from:string,to:string}>} [opts.mappings] - absolute path remaps.
 * @param {string} [opts.from] - single remap source (with opts.to).
 * @param {string} [opts.to]   - single remap destination.
 * @returns {Promise<{buffer:Buffer, relinked:Array<{from:string,to:string,blobsEdited:number,textRefs:number}>}>}
 */
async function relinkMedia(drpInput, opts = {}) {
  const mappings = opts.mappings || (opts.from && opts.to ? [{ from: opts.from, to: opts.to }] : []);
  if (mappings.length === 0) throw new TypeError('relinkMedia: provide { from, to } or { mappings: [...] }');
  for (const m of mappings) {
    if (!nodePath.isAbsolute(m.from) || !nodePath.isAbsolute(m.to)) {
      throw new Error(`relinkMedia: paths must be absolute (got ${m.from} -> ${m.to})`);
    }
  }

  const buf = Buffer.isBuffer(drpInput) ? drpInput : await fs.promises.readFile(drpInput);
  const zip = await JSZip.loadAsync(buf);

  const report = mappings.map((m) => ({ from: m.from, to: m.to, blobsEdited: 0, textRefs: 0 }));

  const names = Object.keys(zip.files).filter((n) => !zip.files[n].dir && n.endsWith('.xml'));
  for (const name of names) {
    let xml = await zip.file(name).async('string');
    let dirty = false;

    mappings.forEach((m, mi) => {
      const fromDir = nodePath.dirname(m.from);
      const fromName = nodePath.basename(m.from);
      const toDir = nodePath.dirname(m.to);
      const toName = nodePath.basename(m.to);

      // 1) plain-text <MediaFilePath> (timeline clips) and <Name> (media pool).
      const beforeText = xml;
      xml = xml.split(`<MediaFilePath>${m.from}</MediaFilePath>`).join(`<MediaFilePath>${m.to}</MediaFilePath>`);
      xml = xml.split(`<Name>${fromName}</Name>`).join(`<Name>${toName}</Name>`);
      if (xml !== beforeText) { dirty = true; report[mi].textRefs += 1; }

      // 2) binary media blobs (hex between > and <).
      const fromDirB = Buffer.from(fromDir, 'utf8');
      const fromNameB = Buffer.from(fromName, 'utf8');
      const toDirB = Buffer.from(toDir, 'utf8');
      const toNameB = Buffer.from(toName, 'utf8');
      xml = xml.replace(/>([0-9a-fA-F]{40,})</g, (whole, hex) => {
        const blob = Buffer.from(hex, 'hex');
        if (blob.indexOf(fromNameB) < 0 && blob.indexOf(fromDirB) < 0) return whole;
        const r = relinkBlob(blob, fromDirB, fromNameB, toDirB, toNameB);
        if (!r.changed) return whole;
        dirty = true;
        report[mi].blobsEdited += 1;
        return `>${r.blob.toString('hex')}<`;
      });
    });

    if (dirty) zip.file(name, xml);
  }

  const outBuf = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return { buffer: outBuf, relinked: report };
}

// In-place same-length value replacement inside a blob (no header bookkeeping needed).
function bufReplaceU32BE(buf, oldV, newV) {
  if (oldV == null || newV == null || oldV === newV) return buf;
  const o = Buffer.alloc(4); o.writeUInt32BE(oldV >>> 0, 0);
  const n = Buffer.alloc(4); n.writeUInt32BE(newV >>> 0, 0);
  const out = Buffer.from(buf);
  let i = 0; while ((i = out.indexOf(o, i)) >= 0) { n.copy(out, i); i += 4; }
  return out;
}
function bufReplaceDoubleLE(buf, oldV, newV) {
  if (oldV == null || newV == null || oldV === newV) return buf;
  const o = Buffer.alloc(8); o.writeDoubleLE(oldV, 0);
  const n = Buffer.alloc(8); n.writeDoubleLE(newV, 0);
  const out = Buffer.from(buf);
  let i = 0; while ((i = out.indexOf(o, i)) >= 0) { n.copy(out, i); i += 8; }
  return out;
}

// Patch resolution (Geometry blob: width/height u32be) + frame count & fps (Time blob: u32be + LE
// double) for the Media Pool entry whose <Name> matches `toName`. Verified mapping (Resolve 21):
// see resolve21-schema-reconciliation.md / design note P8.
function patchSpecBlobs(mpXml, toName, fromSpec, toSpec) {
  let patched = false;
  const out = mpXml.replace(/<Sm2MpVideoClip\b[\s\S]*?<\/Sm2MpVideoClip>/g, (entry) => {
    const nm = entry.match(/<Name>([^<]*)<\/Name>/);
    if (!nm || nm[1] !== toName) return entry;
    let e = entry;
    e = e.replace(/<Geometry>([0-9a-fA-F]+)<\/Geometry>/, (_m, hex) => {
      let b = Buffer.from(hex, 'hex');
      b = bufReplaceU32BE(b, fromSpec.width, toSpec.width);
      b = bufReplaceU32BE(b, fromSpec.height, toSpec.height);
      patched = true;
      return `<Geometry>${b.toString('hex')}</Geometry>`;
    });
    e = e.replace(/<Time>([0-9a-fA-F]+)<\/Time>/, (_m, hex) => {
      let b = Buffer.from(hex, 'hex');
      b = bufReplaceU32BE(b, fromSpec.frameCount, toSpec.frameCount);
      b = bufReplaceDoubleLE(b, fromSpec.fps, toSpec.fps);
      patched = true;
      return `<Time>${b.toString('hex')}</Time>`;
    });
    return e;
  });
  return { xml: out, patched };
}

/**
 * Relink media to a new file AND fix its cached specs (resolution / frame count / fps) so the clip
 * is correct for a differently-formatted file. Resolve doesn't reconform on import, so the cached
 * Media Pool metadata must match the target file — patched here by same-length value replacement.
 *
 * @param {Buffer|string} drpInput
 * @param {object} opts
 * @param {Array<{from:string,to:string,fromSpec:object,toSpec:object}>} [opts.mappings]
 *   fromSpec/toSpec: { width, height, frameCount, fps } — fromSpec = the entry's CURRENT specs
 *   (what to find), toSpec = the target file's specs (e.g. from ffprobe). Same codec family.
 * @param {string} [opts.from] @param {string} [opts.to] @param {object} [opts.fromSpec] @param {object} [opts.toSpec]
 * @returns {Promise<{buffer:Buffer, relinked:Array, specPatched:Array<{to:string,patched:boolean}>}>}
 */
async function repointMedia(drpInput, opts = {}) {
  const mappings = opts.mappings
    || (opts.from && opts.to ? [{ from: opts.from, to: opts.to, fromSpec: opts.fromSpec, toSpec: opts.toSpec }] : []);
  if (mappings.length === 0) throw new TypeError('repointMedia: provide { from, to, fromSpec, toSpec } or { mappings }');

  // 1) relink the path (handles plain text + Clip-blob path with varint framing).
  const relinked = await relinkMedia(drpInput, { mappings: mappings.map((m) => ({ from: m.from, to: m.to })) });

  // 2) patch the cached specs per entry.
  const zip = await JSZip.loadAsync(relinked.buffer);
  const mpPath = 'MediaPool/Master/MpFolder.xml';
  let mp = await zip.file(mpPath).async('string');
  const specPatched = [];
  for (const m of mappings) {
    if (!m.toSpec || !m.fromSpec) { specPatched.push({ to: m.to, patched: false }); continue; }
    const res = patchSpecBlobs(mp, nodePath.basename(m.to), m.fromSpec, m.toSpec);
    mp = res.xml;
    specPatched.push({ to: m.to, patched: res.patched });
  }
  zip.file(mpPath, mp);
  const buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  return { buffer, relinked: relinked.relinked, specPatched };
}

module.exports = { relinkMedia, repointMedia };
