/**
 * Resolve version registry + DRT retargeting.
 *
 * Ground-truth-only: every row here was read from a REAL DaVinci Resolve export
 * (a `.drt`/`.drp` Resolve itself wrote). `DbPrjVer` is the project-database
 * version Resolve gates imports on — it does NOT increment 1:1 with the marketing
 * version (note 16 is absent below: Resolve 20 = 15, Resolve 21 = 17), so it can
 * never be guessed — only recorded from a real file.
 *
 * The schema (SeqContainer/<uuid>.xml, Sm2TiTrack + Type/Sequence, <Element>
 * wrappers, clip/transition/transform encodings) is byte-structurally IDENTICAL
 * across 19/20/21 for standard timeline content (media clips, cross-dissolves,
 * transforms) — verified against real exports. So retargeting such a timeline is a
 * pure version re-stamp. The gate for *non-standard* content is the capability map
 * (see ./capabilities.js): retarget down only when every element used is supported
 * by the target's DbPrjVer.
 *
 * To add a version: export any timeline from that Resolve, read its stamp, add a row.
 *
 * @module drt-format/resolve-versions
 */

const fs = require('node:fs');
const path = require('node:path');
const JSZip = require('jszip');
const { collectCapabilities, checkCapabilities } = require('./capabilities');

// key → verified stamp. key is the major marketing version (caller-facing).
const VERSIONS = {
  19: { marketing: '19.1.3', dbAppVer: '19.1.3.0007', dbPrjVer: '14' },
  20: { marketing: '20.3.2', dbAppVer: '20.3.2.0009', dbPrjVer: '15' },
  21: { marketing: '21.0.0', dbAppVer: '21.0.0.0048', dbPrjVer: '17' },
};

const PROJECT_SHELL = path.join(__dirname, 'templates', 'drt-project-shell.xml');

function resolveVersion(key) {
  const v = VERSIONS[String(key).split('.')[0]];
  if (!v) {
    throw new Error(
      `resolve-versions: no registry entry for Resolve ${key}. ` +
      `Known: ${Object.values(VERSIONS).map((x) => x.marketing).join(', ')}. ` +
      `Add it by exporting a timeline from that Resolve and recording its DbPrjVer.`,
    );
  }
  return v;
}

// Read the DbAppVer/DbPrjVer a DRT/DRP was authored with, from its SeqContainer header.
function readVersionStamp(seqXml) {
  const m = seqXml.match(/DbAppVer="([^"]*)" DbPrjVer="([^"]*)"/);
  return m ? { dbAppVer: m[1], dbPrjVer: m[2] } : null;
}

const SEQ_RE = /(^|\/)SeqContainer(\d*\.xml|\/[^/]+\.xml)$/;

// Value-based version re-stamp (not length-dependent → safe even if stamp widths differ).
// Shared by every format (DRT, DRP, DRX) — the DbAppVer/DbPrjVer header is universal.
function restampVersions(xmlStr, src, target) {
  return xmlStr
    .split(`DbAppVer="${src.dbAppVer}"`).join(`DbAppVer="${target.dbAppVer}"`)
    .split(`DbPrjVer="${src.dbPrjVer}"`).join(`DbPrjVer="${target.dbPrjVer}"`);
}

/**
 * Re-stamp a zip-based Resolve file (DRT or DRP) to a target version. Value-based,
 * so it's safe even if stamp widths differ. Re-stamps every XML entry in place
 * (keeping a DRP's full project.xml); adds a stamped generic shell only if the source
 * has no project.xml (a tool-built DRT).
 *
 * @param {Buffer} drtBuffer  a real-schema .drt/.drp (SeqContainer/<uuid>.xml + MpFolder)
 * @param {number|string} targetKey  e.g. 19, 20, 21
 * @returns {Promise<Buffer>} the retargeted file
 */
async function retargetDRT(drtBuffer, targetKey, opts = {}) {
  const target = resolveVersion(targetKey);
  const zin = await JSZip.loadAsync(drtBuffer);

  // find the source stamp from the (first) SeqContainer
  let seqEntry = null;
  zin.forEach((p, e) => { if (!e.dir && SEQ_RE.test(p) && !seqEntry) seqEntry = p; });
  if (!seqEntry) throw new Error('retargetDRT: no SeqContainer/<uuid>.xml found — not a real-schema DRT?');
  const seqXml = await zin.file(seqEntry).async('string');
  const src = readVersionStamp(seqXml);
  if (!src) throw new Error('retargetDRT: source SeqContainer has no DbAppVer/DbPrjVer header to retarget from.');

  // capability gate: refuse a downgrade the target can't actually open (unless forced).
  if (Number(target.dbPrjVer) < Number(src.dbPrjVer) && !opts.force) {
    const { used, unknownElements } = collectCapabilities(seqXml);
    const { ok, blocked } = checkCapabilities(used, unknownElements, target.dbPrjVer);
    if (!ok) {
      throw new Error(
        `retargetDRT: timeline uses capabilities newer than Resolve ${target.marketing} ` +
        `(DbPrjVer ${target.dbPrjVer}): ${blocked.map((b) => `${b.cap}≥${b.min}`).join(', ')}. ` +
        `Pass { force: true } to override, or strip/substitute those elements first.`,
      );
    }
  }

  const zout = new JSZip();
  const hasProject = Object.keys(zin.files).some(
    (p) => /(^|\/)project\.xml$/.test(p) && !zin.files[p].dir,
  );

  for (const p of Object.keys(zin.files)) {
    const e = zin.files[p];
    if (e.dir) continue;
    const data = await e.async('nodebuffer');
    // Re-stamp every XML entry in place — including project.xml, so a DRP keeps its
    // full project (settings/render/color) rather than having it replaced.
    zout.file(p, p.endsWith('.xml') ? restampVersions(data.toString('utf8'), src, target) : data);
  }
  // A tool-built DRT has no project.xml; add a stamped generic shell so the result
  // is a complete, importable DRT. (Real DRTs and all DRPs already carry one, kept above.)
  if (!hasProject) {
    let shell = fs.readFileSync(PROJECT_SHELL, 'utf8');
    const ss = readVersionStamp(shell);
    if (ss) shell = restampVersions(shell, ss, target);
    zout.file('project.xml', shell);
  }
  return zout.generateAsync({ type: 'nodebuffer' });
}

// DRP shares the zip handler: it just keeps (and re-stamps) its full project.xml.
const retargetDRP = retargetDRT;

/**
 * Retarget a DRX (DaVinci grade / gallery still) — a single XML file, not a zip.
 * Carries the same DbAppVer/DbPrjVer stamp, so it re-stamps the same way.
 * Color-domain capability gating is mapped separately (the DRX param registry),
 * so this re-stamps without a timeline-capability gate.
 * @param {Buffer|string} drxInput
 * @returns {Promise<Buffer>}
 */
async function retargetDRX(drxInput, targetKey) {
  const target = resolveVersion(targetKey);
  const xml = Buffer.isBuffer(drxInput) ? drxInput.toString('utf8') : String(drxInput);
  const src = readVersionStamp(xml);
  if (!src) throw new Error('retargetDRX: DRX has no DbAppVer/DbPrjVer header to retarget from.');
  return Buffer.from(restampVersions(xml, src, target), 'utf8');
}

/** Auto-detect format: a zip (DRT/DRP) vs a single XML (DRX). */
async function retarget(input, targetKey, opts = {}) {
  const buf = Buffer.isBuffer(input) ? input : Buffer.from(String(input));
  const isZip = buf.length > 1 && buf[0] === 0x50 && buf[1] === 0x4b; // 'PK' zip signature
  return isZip ? retargetDRT(buf, targetKey, opts) : retargetDRX(buf, targetKey);
}

module.exports = {
  VERSIONS, resolveVersion, readVersionStamp, restampVersions,
  retargetDRT, retargetDRP, retargetDRX, retarget,
};
