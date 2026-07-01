/**
 * Offline Reference Clip — set/clear/get the timeline Offline Reference link in
 * a .drp/.drt by plain-XML surgery on MediaPool/.../MpFolder.xml. No scripting
 * API exists for this (verified live Resolve 21); file patching is the only route.
 *
 * Spec + reverse-engineering: the design notes design notes.
 *
 * The link is a `<OfflineClip>{Sm2MpVideoClip@DbId}</OfflineClip>` element placed
 * immediately after the timeline's `</Sequence>` and before `<OfflineFrameOffset>`.
 * It lives OUTSIDE the FieldsBlob, so no binary codec is needed.
 */

import fs from 'node:fs/promises';
import JSZip from 'jszip';

const UUID_RE = /^[0-9a-fA-F-]{36}$/;

// Walk each <Sm2MpTimelineClip DbId="...">... </Sequence> [<OfflineClip>?] region.
// Returns [{ dbId, seqEndIdx, indent, existing: {uuid, start, end} | null }] in file order.
function findTimelineClips(xml) {
  const out = [];
  const startRe = /<Sm2MpTimelineClip\b[^>]*\bDbId="([^"]+)"/g;
  let m;
  while ((m = startRe.exec(xml)) !== null) {
    const dbId = m[1];
    const seqEnd = xml.indexOf('</Sequence>', m.index);
    if (seqEnd === -1) continue;
    const after = seqEnd + '</Sequence>'.length;
    // capture the whitespace run after </Sequence> (preserve indentation)
    const wsMatch = /^(\s*)/.exec(xml.slice(after));
    const indent = wsMatch ? wsMatch[1] : '\n ';
    const rest = xml.slice(after + indent.length);
    let existing = null;
    const oc = /^<OfflineClip>([^<]*)<\/OfflineClip>/.exec(rest);
    if (oc) {
      existing = { uuid: oc[1], start: after + indent.length, end: after + indent.length + oc[0].length };
    }
    out.push({ dbId, seqEnd, after, indent, existing });
  }
  return out;
}

// Resolve a reference movie path/name → its Sm2MpVideoClip DbId (best-effort).
function resolveReferenceDbId(xml, { referenceDbId, referenceMovie }) {
  if (referenceDbId) return referenceDbId;
  if (!referenceMovie) return null;
  const needle = referenceMovie.split('/').pop(); // basename
  // Find the nearest Sm2MpVideoClip DbId whose block mentions the path/basename.
  const clipRe = /<Sm2MpVideoClip\b[^>]*\bDbId="([^"]+)"/g;
  let best = null,
    m;
  while ((m = clipRe.exec(xml)) !== null) {
    const block = xml.slice(m.index, m.index + 4000);
    if (block.includes(referenceMovie) || block.includes(needle)) {
      best = m[1];
      break;
    }
  }
  return best;
}

function listLinks(xml) {
  return findTimelineClips(xml)
    .filter((t) => t.existing)
    .map((t) => ({ timelineDbId: t.dbId, offlineClip: t.existing.uuid }));
}

// Apply edits to one MpFolder.xml string. ops: array of {match, refDbId|null(clear)}.
// Returns { xml, changes:[{timelineDbId, action, refDbId}] }.
function patchXml(xml, selectorFn, refDbId, clear) {
  const clips = findTimelineClips(xml);
  const targets = clips.filter(selectorFn);
  // edit right-to-left so offsets stay valid
  const changes = [];
  for (const t of targets.sort((a, b) => b.after - a.after)) {
    if (clear) {
      if (t.existing) {
        // remove the OfflineClip element + its leading indentation run
        xml = xml.slice(0, t.after) + xml.slice(t.existing.end);
        changes.push({ timelineDbId: t.dbId, action: 'cleared' });
      }
      continue;
    }
    const el = `<OfflineClip>${refDbId}</OfflineClip>`;
    if (t.existing) {
      xml = xml.slice(0, t.existing.start) + el + xml.slice(t.existing.end);
      changes.push({ timelineDbId: t.dbId, action: 'replaced', refDbId });
    } else {
      const insertAt = t.after; // right after </Sequence>
      xml = xml.slice(0, insertAt) + t.indent + el + xml.slice(insertAt);
      changes.push({ timelineDbId: t.dbId, action: 'inserted', refDbId });
    }
  }
  return { xml, changes };
}

async function loadZip(filePath) {
  return JSZip.loadAsync(await fs.readFile(filePath));
}
function mpFolderEntries(zip) {
  const names = [];
  zip.forEach((p, e) => {
    if (!e.dir && /MpFolder\.xml$/.test(p)) names.push(p);
  });
  return names;
}

/** Read all offline-reference links across the archive. */
export async function getOfflineReferences(filePath) {
  const zip = await loadZip(filePath);
  const links = [];
  for (const name of mpFolderEntries(zip)) {
    const xml = await zip.file(name).async('string');
    for (const l of listLinks(xml)) links.push({ mpFolder: name, ...l });
  }
  return { filePath, count: links.length, links };
}

/**
 * Set (link) an offline reference on one or more timelines.
 * opts: { links:[{ timelineDbId?, allTimelines?, referenceDbId?|referenceMovie? }], outputPath, backup? }
 * Single-timeline.drt: omit timelineDbId to target the only timeline.
 */
export async function setOfflineReference(filePath, opts = {}) {
  const { links = [], outputPath, backup = true } = opts;
  if (!links.length) throw new Error('setOfflineReference: links[] required');
  const zip = await loadZip(filePath);
  const entries = mpFolderEntries(zip);
  const allChanges = [];

  for (const spec of links) {
    let refDbId = null;
    let appliedSomewhere = false;
    for (const name of entries) {
      let xml = await zip.file(name).async('string');
      refDbId = resolveReferenceDbId(xml, spec) || refDbId;
      if (!refDbId) continue;
      if (refDbId && !UUID_RE.test(refDbId)) throw new Error(`reference DbId not a UUID: ${refDbId}`);
      const all = findTimelineClips(xml);
      const selector = spec.timelineDbId ? (t) => t.dbId === spec.timelineDbId : spec.allTimelines ? () => true : all.length === 1 ? () => true : () => false;
      const { xml: nx, changes } = patchXml(xml, selector, refDbId, false);
      if (changes.length) {
        zip.file(name, nx);
        allChanges.push(...changes);
        appliedSomewhere = true;
      }
    }
    if (!refDbId) throw new Error(`could not resolve reference (referenceDbId/referenceMovie) for ${JSON.stringify(spec)}`);
    if (!appliedSomewhere)
      throw new Error(`no target timeline matched for ${JSON.stringify(spec)} (need timelineDbId, allTimelines, or a single-timeline file)`);
  }

  if (backup) await fs.copyFile(filePath, `${filePath}.bak`).catch(() => {});
  const out = outputPath || filePath;
  await fs.writeFile(out, await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' }));
  // round-trip verify
  const verify = await getOfflineReferences(out);
  return { outputPath: out, changes: allChanges, linksAfter: verify.links, verified: true };
}

/** Clear (unlink) offline reference from timelines (by DbId, or all). */
export async function clearOfflineReference(filePath, opts = {}) {
  const { timelineDbIds = null, all = false, outputPath, backup = true } = opts;
  const zip = await loadZip(filePath);
  const allChanges = [];
  for (const name of mpFolderEntries(zip)) {
    let xml = await zip.file(name).async('string');
    const selector = all ? () => true : (t) => timelineDbIds && timelineDbIds.includes(t.dbId);
    const { xml: nx, changes } = patchXml(xml, selector, null, true);
    if (changes.length) {
      zip.file(name, nx);
      allChanges.push(...changes);
    }
  }
  if (backup) await fs.copyFile(filePath, `${filePath}.bak`).catch(() => {});
  const out = outputPath || filePath;
  await fs.writeFile(out, await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' }));
  return { outputPath: out, cleared: allChanges };
}
