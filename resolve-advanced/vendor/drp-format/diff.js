/**
 * DaVinci Resolve DRP Structural Diff
 *
 * Compares two DRP archives and returns a normalized delta DTO. Clip
 * identity is the Sm2TiVideoClip / Sm2TiAudioClip DbId; grade changes
 * are detected by sha256 of the per-clip <Body> hex blob (DRX bytes
 * are deterministic for the same grade, so byte equality is the right
 * test). For per-parameter grade deltas, callers should pair this with
 * drx-codec.grade.compare on the diffed clip's body.
 *
 * Schema documented in
 * docs/design/drp-drx-drt-closeout-harness/knowledge/diff-dto-schema.md
 *
 * @module drp-format/diff
 */

const fs = require('node:fs/promises');
const crypto = require('node:crypto');
const JSZip = require('jszip');

const CLIP_TAGS = ['Sm2TiVideoClip', 'Sm2VideoClip', 'Sm2TiAudioClip', 'Sm2AudioClip'];

/** Find all SeqContainer*.xml entries regardless of folder name.
 * Matches BOTH tool-authored `SeqContainer<N>.xml` AND real Resolve `SeqContainer/<uuid>.xml` (F1 fix). */
function listSeqContainerEntries(zip) {
  const out = [];
  zip.forEach((relativePath, entry) => {
    if (entry.dir) return;
    if (/(^|\/)SeqContainer(\d*\.xml|\/[^/]+\.xml)$/.test(relativePath)) {
      out.push(relativePath);
    }
  });
  return out.sort();
}

function findProjectXmlEntry(zip) {
  let found = null;
  zip.forEach((p, e) => {
    if (!e.dir && /(^|\/)project\.xml$/.test(p)) found = p;
  });
  return found;
}

function hashBody(bodyHex) {
  return crypto.createHash('sha256').update(bodyHex).digest('hex');
}

function tagOf(match) { return match[1]; }
function trackTypeFromTag(tag) {
  return tag.endsWith('VideoClip') ? 'video' : 'audio';
}

/**
 * Scrape clips out of a SeqContainer XML. Returns
 *   [{ clipId, trackType, mediaFilePath, start, duration, bodyHex|null }]
 *
 * Light regex parsing — we never write back through this path, so we
 * don't need fast-xml-parser's lossy round-trip. The fields we extract
 * are stable across Resolve's pretty-printing conventions.
 */
function extractClips(seqXml) {
  const clips = [];
  const tagAlternation = CLIP_TAGS.join('|');
  // Open tag + attrs + content up to matching close tag. Nested clips of
  // the same tag are not produced by Resolve's serializer in practice.
  const clipRe = new RegExp(
    `<(${tagAlternation})\\b([^>]*?)DbId="([^"]+)"([^>]*)>([\\s\\S]*?)</\\1>`,
    'g',
  );
  let m;
  while ((m = clipRe.exec(seqXml)) !== null) {
    const tag = tagOf(m);
    const dbId = m[3];
    const inner = m[5];
    const mediaFilePath = extractScalar(inner, 'MediaFilePath');
    const start = extractInt(inner, 'Start');
    const duration = extractInt(inner, 'Duration');
    const bodyMatch = inner.match(/<Body>([0-9a-fA-F\s]*)<\/Body>/);
    let bodyHex = null;
    if (bodyMatch) {
      const stripped = bodyMatch[1].replace(/[^0-9a-fA-F]/g, '');
      if (stripped.length > 0) bodyHex = stripped;
    }
    clips.push({
      clipId: dbId,
      trackType: trackTypeFromTag(tag),
      mediaFilePath,
      start,
      duration,
      bodyHex,
    });
  }
  return clips;
}

function extractScalar(xml, tagName) {
  const re = new RegExp(`<${tagName}>([\\s\\S]*?)</${tagName}>`);
  const m = xml.match(re);
  return m ? m[1].trim() : null;
}

function extractInt(xml, tagName) {
  const v = extractScalar(xml, tagName);
  if (v === null || v === '') return null;
  const n = Number.parseInt(v, 10);
  return Number.isFinite(n) ? n : null;
}

/**
 * Walk a DRP and return a flat clip index plus project-level metadata.
 *
 *   {
 *     seqContainers: [path, …],
 *     clipsById: Map<dbId, ClipRecord>,
 *     mediaPaths: Set<string>,
 *     projectXml: string | null,
 *     projectSettings: { projectName?, … } parsed from project.xml,
 *   }
 */
async function indexDrp(drpPath) {
  const buf = await fs.readFile(drpPath);
  const zip = await JSZip.loadAsync(buf);

  const seqContainers = listSeqContainerEntries(zip);
  const clipsById = new Map();
  const mediaPaths = new Set();

  for (const p of seqContainers) {
    const xml = await zip.file(p).async('string');
    const clips = extractClips(xml);
    for (const c of clips) {
      c.sequence = p;
      // First occurrence wins on DbId collision (shouldn't happen with
      // real Resolve UUIDs).
      if (!clipsById.has(c.clipId)) clipsById.set(c.clipId, c);
      if (c.mediaFilePath) mediaPaths.add(c.mediaFilePath);
    }
  }

  const projEntry = findProjectXmlEntry(zip);
  let projectXml = null;
  let projectSettings = {};
  if (projEntry) {
    projectXml = await zip.file(projEntry).async('string');
    projectSettings = extractProjectSettings(projectXml);
  }

  return { seqContainers, clipsById, mediaPaths, projectXml, projectSettings };
}

/**
 * Pull a small whitelist of settings from project.xml for the
 * timelineSettingDeltas section. Expand as concrete callers ask for
 * more.
 */
function extractProjectSettings(projectXml) {
  const settings = {};
  // tool-authored DRPs use <Name>; some Resolve-exported variants
  // use <ProjectName>. Check both.
  const projectName =
    extractScalar(projectXml, 'ProjectName') ||
    extractScalar(projectXml, 'Name');
  if (projectName !== null) settings.projectName = projectName;
  const tlFrameRate = extractScalar(projectXml, 'TimelineFrameRate');
  if (tlFrameRate !== null) settings.timelineFrameRate = tlFrameRate;
  const tlResWidth = extractScalar(projectXml, 'TimelineResolutionWidth');
  const tlResHeight = extractScalar(projectXml, 'TimelineResolutionHeight');
  if (tlResWidth !== null && tlResHeight !== null) {
    settings.timelineResolution = `${tlResWidth}x${tlResHeight}`;
  }
  const colorScience = extractScalar(projectXml, 'ColorScience');
  if (colorScience !== null) settings.colorScience = colorScience;
  return settings;
}

/**
 * Diff two DRPs structurally. See diff-dto-schema.md for the return shape.
 *
 * @param {string} drpAPath - "before" / "left" DRP
 * @param {string} drpBPath - "after" / "right" DRP
 * @returns {Promise<DrpDiff>}
 */
async function diff(drpAPath, drpBPath) {
  if (typeof drpAPath !== 'string' || typeof drpBPath !== 'string') {
    throw new TypeError('diff: drpAPath and drpBPath must be strings');
  }

  const [a, b] = await Promise.all([indexDrp(drpAPath), indexDrp(drpBPath)]);

  const addedClips = [];
  const removedClips = [];
  const movedClips = [];
  const gradeChanges = [];

  // Walk A → find removed + (moved + gradeChanged within shared set)
  for (const [clipId, clipA] of a.clipsById) {
    const clipB = b.clipsById.get(clipId);
    if (!clipB) {
      removedClips.push(packClipDelta(clipA));
      continue;
    }

    // Move detection: any change in (sequence, start) for the same clip.
    if (clipA.sequence !== clipB.sequence || clipA.start !== clipB.start) {
      movedClips.push({
        clipId,
        trackType: clipA.trackType,
        before: { sequence: clipA.sequence, start: clipA.start },
        after: { sequence: clipB.sequence, start: clipB.start },
      });
    }

    // Grade detection: hash hex bodies, compare.
    const beforeHash = clipA.bodyHex ? hashBody(clipA.bodyHex) : null;
    const afterHash = clipB.bodyHex ? hashBody(clipB.bodyHex) : null;
    if (beforeHash !== afterHash) {
      gradeChanges.push({
        clipId,
        sequence: clipB.sequence,
        beforeBodyHash: beforeHash,
        afterBodyHash: afterHash,
        hadGrade: Boolean(clipA.bodyHex),
        hasGrade: Boolean(clipB.bodyHex),
      });
    }
  }

  // Walk B → find added
  for (const [clipId, clipB] of b.clipsById) {
    if (!a.clipsById.has(clipId)) {
      addedClips.push(packClipDelta(clipB));
    }
  }

  // Timeline settings diff (whitelist set extracted above).
  const timelineSettingDeltas = diffSettings(a.projectSettings, b.projectSettings);

  // Media pool diff — basic, source: clip MediaFilePath sets.
  const mediaPoolDeltas = {
    added: [...b.mediaPaths].filter((p) => !a.mediaPaths.has(p)),
    removed: [...a.mediaPaths].filter((p) => !b.mediaPaths.has(p)),
  };

  // sameClipCount: clips present in both, no matter whether they changed.
  let sameClipCount = 0;
  for (const id of a.clipsById.keys()) {
    if (b.clipsById.has(id)) sameClipCount += 1;
  }

  const summary = {
    seqContainersA: a.seqContainers.length,
    seqContainersB: b.seqContainers.length,
    clipsA: a.clipsById.size,
    clipsB: b.clipsById.size,
    sameClipCount,
    hasAnyChange:
      addedClips.length > 0 ||
      removedClips.length > 0 ||
      movedClips.length > 0 ||
      gradeChanges.length > 0 ||
      timelineSettingDeltas.length > 0 ||
      mediaPoolDeltas.added.length > 0 ||
      mediaPoolDeltas.removed.length > 0,
  };

  return {
    addedClips,
    removedClips,
    movedClips,
    gradeChanges,
    timelineSettingDeltas,
    mediaPoolDeltas,
    summary,
  };
}

function packClipDelta(clip) {
  return {
    clipId: clip.clipId,
    trackType: clip.trackType,
    sequence: clip.sequence,
    mediaFilePath: clip.mediaFilePath,
    start: clip.start,
    duration: clip.duration,
  };
}

function diffSettings(beforeMap, afterMap) {
  const keys = new Set([...Object.keys(beforeMap), ...Object.keys(afterMap)]);
  const deltas = [];
  for (const k of keys) {
    const before = beforeMap[k];
    const after = afterMap[k];
    if (before !== after) {
      deltas.push({ key: k, before: before ?? null, after: after ?? null });
    }
  }
  return deltas;
}

module.exports = {
  diff,
  _internals: {
    indexDrp,
    extractClips,
    extractProjectSettings,
    diffSettings,
    hashBody,
  },
};
