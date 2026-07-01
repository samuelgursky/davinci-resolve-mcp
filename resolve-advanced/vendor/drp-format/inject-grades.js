/**
 * DaVinci Resolve DRP Grade Injection
 *
 * Replaces the per-clip <Body> grade payload inside SeqContainer XMLs of a
 * DRP archive with new payloads carried by DRX files. The DRX file's own
 * <Body>HEX</Body> blob and the clip's <Body>HEX</Body> blob use the same
 * marker-byte+zstd-compressed-protobuf encoding, so the injection is byte
 * substitution — no protobuf understanding required at this layer.
 *
 * Resolve emits SeqContainer*.xml under "SeqContainer/" in exported DRPs.
 * The the packager writes them under "Primary1/". This module
 * discovers the folder by scanning zip entries so both layouts work.
 *
 * @module drp-format/inject-grades
 */

const fs = require('node:fs/promises');
const JSZip = require('jszip');

/** Find all SeqContainer*.xml entries regardless of folder name. */
function listSeqContainerEntries(zip) {
  const out = [];
  zip.forEach((relativePath, entry) => {
    if (entry.dir) return;
    // Match any "<anything>/SeqContainer<N>.xml" path.
    if (/(^|\/)SeqContainer\d*\.xml$/.test(relativePath)) {
      out.push(relativePath);
    }
  });
  return out;
}

/**
 * Extract the hex blob from a DRX XML string. The blob is the same payload
 * (marker 0x81 + zstd-compressed protobuf) that lives inside a clip's
 * <Body> field in a SeqContainer.
 */
function extractDrxBodyHex(drxContent) {
  // Use a non-greedy match across the entire XML — fast-xml-parser would
  // be overkill and would normalize whitespace we don't control.
  const match = drxContent.match(/<Body>([\s\S]*?)<\/Body>/);
  if (!match) {
    throw new Error('DRX content has no <Body>HEX</Body> block');
  }
  // The hex stream may contain whitespace from how Resolve formats DRX
  // exports — strip everything that isn't hex.
  return match[1].replace(/[^0-9a-fA-F]/g, '');
}

/**
 * Replace the <Body> content of the first clip in seqXml whose DbId
 * matches targetDbId. Returns null when no match (caller must decide
 * whether that's an error or just a miss across multiple SeqContainers).
 *
 * Scoping: the regex anchors on `<Sm2TiVideoClip ... DbId="<id>"` and
 * runs forward to the matching `</Sm2TiVideoClip>`. Inside that range we
 * replace exactly one <Body>HEX</Body>. If a clip has no Body yet (a
 * brand-new clip with no grade) we don't synthesize the surrounding
 * LmVersionTable scaffolding — that's a builder responsibility, not an
 * injector one. Callers wanting to add grades to clean clips should
 * build the DRP fresh via buildDRP with the grade in the spec.
 */
function replaceBodyForClip(seqXml, targetDbId, newBodyHex) {
  // 1. Locate the clip element opening tag.
  //    Sm2TiVideoClip is the post-monorepo tag (matches seq-container-builder).
  //    Older / different layouts may use Sm2VideoClip — accept both.
  const clipOpenRe = new RegExp(
    `<(Sm2TiVideoClip|Sm2VideoClip)([^>]*?)DbId="${escapeRegex(targetDbId)}"([^>]*)>`,
  );
  const openMatch = seqXml.match(clipOpenRe);
  if (!openMatch) return null;

  const clipTag = openMatch[1];
  const openStart = openMatch.index;
  const openEnd = openStart + openMatch[0].length;

  // 2. Find the matching close tag, respecting potential nesting (a clip
  //    doesn't nest a clip of the same tag in practice — confirmed in the
  //    builder — but we walk depth anyway to be defensive).
  const closeTag = `</${clipTag}>`;
  const openTag = `<${clipTag}`;
  let depth = 1;
  let cursor = openEnd;
  while (depth > 0) {
    const nextOpen = seqXml.indexOf(openTag, cursor);
    const nextClose = seqXml.indexOf(closeTag, cursor);
    if (nextClose === -1) return null;
    if (nextOpen !== -1 && nextOpen < nextClose) {
      depth += 1;
      cursor = nextOpen + openTag.length;
    } else {
      depth -= 1;
      cursor = nextClose + closeTag.length;
    }
  }
  const clipEnd = cursor;

  // 3. Within the clip's range, replace exactly one <Body>...</Body>.
  const clipRange = seqXml.slice(openStart, clipEnd);
  const bodyRe = /<Body>([\s\S]*?)<\/Body>/;
  if (!bodyRe.test(clipRange)) return null;
  const newClipRange = clipRange.replace(
    bodyRe,
    `<Body>${newBodyHex}</Body>`,
  );

  return seqXml.slice(0, openStart) + newClipRange + seqXml.slice(clipEnd);
}

function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Inject DRX grade payloads into the matching clips of an existing DRP.
 *
 * @param {string} drpPath - Absolute path to the source .drp
 * @param {Array<{clipId?: string, resolveId?: string, drxContent: string}>} grades
 *   Each entry targets one clip by DbId (clipId is the canonical name;
 *   resolveId is accepted as an alias for callers that use Resolve's
 *   field naming). drxContent is the full DRX XML; we extract its <Body>
 *   blob and inject it into the clip's <Body>.
 * @param {object} [opts]
 * @param {string} [opts.outputPath] - Where to write the modified DRP.
 *   If omitted, the source file is overwritten in place atomically.
 * @returns {Promise<{bytes: number, clipsInjected: number, misses: string[]}>}
 *   bytes: size of the written DRP.
 *   clipsInjected: number of grade entries that found their target.
 *   misses: clip IDs that didn't match any SeqContainer's clip.
 */
async function injectGrades(drpPath, grades, opts = {}) {
  if (typeof drpPath !== 'string') {
    throw new TypeError('injectGrades: drpPath must be a string');
  }
  if (!Array.isArray(grades) || grades.length === 0) {
    throw new TypeError('injectGrades: grades must be a non-empty array');
  }

  const sourceBuf = await fs.readFile(drpPath);
  const zip = await JSZip.loadAsync(sourceBuf);

  const seqPaths = listSeqContainerEntries(zip);
  if (seqPaths.length === 0) {
    throw new Error(`No SeqContainer*.xml found in ${drpPath}`);
  }

  // Cache each SeqContainer's XML in memory; rewrite only the ones whose
  // content changes. Cheaper than per-clip re-read and keeps the original
  // file order stable in the output zip.
  const seqXmls = new Map();
  for (const p of seqPaths) {
    seqXmls.set(p, await zip.file(p).async('string'));
  }

  let clipsInjected = 0;
  const misses = [];

  for (const entry of grades) {
    const targetId = entry.clipId || entry.resolveId;
    if (!targetId) {
      throw new Error('injectGrades: every grade entry needs clipId or resolveId');
    }
    if (typeof entry.drxContent !== 'string' || entry.drxContent.length === 0) {
      throw new Error(`injectGrades: grade for clip ${targetId} has no drxContent`);
    }

    const bodyHex = extractDrxBodyHex(entry.drxContent);

    let injected = false;
    for (const p of seqPaths) {
      const before = seqXmls.get(p);
      const after = replaceBodyForClip(before, targetId, bodyHex);
      if (after !== null) {
        seqXmls.set(p, after);
        injected = true;
        break; // a clip appears in exactly one SeqContainer
      }
    }

    if (injected) {
      clipsInjected += 1;
    } else {
      misses.push(targetId);
    }
  }

  // Write modified SeqContainer XMLs back into the zip in place.
  for (const p of seqPaths) {
    zip.file(p, seqXmls.get(p));
  }

  const outBuf = await zip.generateAsync({
    type: 'nodebuffer',
    compression: 'DEFLATE',
    compressionOptions: { level: 6 },
  });

  const outputPath = opts.outputPath || drpPath;
  if (opts.outputPath && opts.outputPath !== drpPath) {
    await fs.writeFile(outputPath, outBuf);
  } else {
    // Atomic in-place overwrite.
    const tmp = `${drpPath}.injecting`;
    await fs.writeFile(tmp, outBuf);
    await fs.rename(tmp, drpPath);
  }

  return { bytes: outBuf.length, clipsInjected, misses };
}

module.exports = {
  injectGrades,
  // Exposed for unit tests; not part of the public API.
  _internals: {
    listSeqContainerEntries,
    extractDrxBodyHex,
    replaceBodyForClip,
  },
};
