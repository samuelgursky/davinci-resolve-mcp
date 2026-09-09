/**
 * Timeline clips from an exported .drp — the DB-agnostic twin of
 * project_read.readTimelineClips. A Postgres / cloud / network library has no
 * Project.db to open, but ProjectManager.ExportProject works on ANY project by
 * name without loading it, and the .drp it writes carries every field the
 * color_trace matcher keys on:
 *
 *   MediaPool/**\/MpFolder.xml   <Sm2Timeline><Name>…</Name><Sequence><Sm2Sequence DbId=SEQ>
 *   SeqContainer/<uuid>.xml     <Sm2TiTrack><Type>0</Type><Sequence>SEQ</Sequence><Items>
 *                                 <Sm2TiVideoClip DbId=…> Name/Start/Duration/In/MediaRef/
 *                                 MediaFilePath/MediaReelNumber/pLmVerTable(pActive → LmVersion Body)
 *
 * Measured on Resolve 19.1.3.7 exports (DbPrjVer 14): one container per
 * timeline, tracks reference their sequence by id, the grade body sits inline
 * in the clip's version table. Row shape matches readTimelineClips so the
 * matcher cannot tell the two sources apart.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

const scalar = (xml, tag) => {
  const m = xml.match(new RegExp(`<${tag}>([^<]*)</${tag}>`));
  return m ? m[1].trim() : null;
};
const blank = (xml, tag) => new RegExp(`<${tag}/>`).test(xml);

/** Walk every `<Sm2Timeline>` in the media-pool folder XMLs → [{name, timelineId, sequenceId}]. */
export function listDrpTimelines(mpFolderXmls) {
  const out = [];
  for (const xml of mpFolderXmls) {
    for (const m of xml.matchAll(/<Sm2Timeline DbId="([^"]+)">([\s\S]*?)<\/Sm2Timeline>/g)) {
      const body = m[2];
      const name = scalar(body, 'Name');
      const seq = body.match(/<Sm2Sequence DbId="([^"]+)"/);
      out.push({ name, timelineId: m[1], sequenceId: seq ? seq[1] : null });
    }
  }
  return out;
}

/** Decode `<In>` the way project_read does: plain decimal, or the FIRST field of a
 * pipe-joined composite ('47|0000eaffffffef3f'). Anything else → null, never 0. */
function decodeIn(v) {
  if (v === null || v === '') return null;
  const head = String(v).split('|', 1)[0];
  return /^-?\d+(\.\d+)?$/.test(head) ? Number(head) : null;
}

/** Active grade of one clip element: {gradeVersion, gradeBody} or nulls.
 * pActive names the active version; fall back to the first corrected one. */
function activeGrade(clipXml) {
  const vt = clipXml.match(/<pLmVerTable>([\s\S]*?)<\/pLmVerTable>/);
  if (!vt) return { gradeVersion: null, gradeBody: null };
  const active = scalar(vt[1], 'pActive');
  const versions = [...vt[1].matchAll(/<ListMgt::LmVersion DbId="([^"]+)">([\s\S]*?)<\/ListMgt::LmVersion>/g)].map((m) => {
    const body = m[2];
    const bodyHex = (body.match(/<Body>([0-9a-fA-F\s]*)<\/Body>/) || [null, ''])[1];
    return {
      id: m[1],
      name: scalar(body, 'Name'),
      corrected: /<HasCorrection>true<\/HasCorrection>/.test(body),
      bodyHex: bodyHex ? bodyHex.replace(/[^0-9a-fA-F]/g, '').toLowerCase() : '',
    };
  });
  const pick = versions.find((v) => v.id === active && v.corrected && v.bodyHex) || versions.find((v) => v.corrected && v.bodyHex);
  return pick ? { gradeVersion: pick.name, gradeBody: pick.bodyHex } : { gradeVersion: null, gradeBody: null };
}

/** Clips of the tracks that belong to `sequenceId` inside one SeqContainer XML.
 * trackType 0 = video (Sm2TiVideoClip), 1 = audio (Sm2TiAudioClip). */
export function parseSeqContainerClips(containerXml, sequenceId, { includeGrade = false } = {}) {
  const rows = [];
  for (const t of containerXml.matchAll(/<Sm2TiTrack DbId="([^"]+)">([\s\S]*?)<\/Sm2TiTrack>/g)) {
    const trackXml = t[2];
    if (sequenceId && scalar(trackXml, 'Sequence') !== sequenceId) continue;
    const trackType = Number(scalar(trackXml, 'Type') ?? 0);
    const tag = trackType === 0 ? 'Sm2TiVideoClip' : 'Sm2TiAudioClip';
    for (const c of trackXml.matchAll(new RegExp(`<${tag} DbId="([^"]+)">([\\s\\S]*?)</${tag}>`, 'g'))) {
      const x = c[2];
      const g = includeGrade ? activeGrade(x) : { gradeVersion: null, gradeBody: null };
      rows.push({
        itemId: c[1],
        name: scalar(x, 'Name'),
        trackType,
        start: Number(scalar(x, 'Start')),
        duration: Number(scalar(x, 'Duration')),
        reel: blank(x, 'MediaReelNumber') ? '' : scalar(x, 'MediaReelNumber') || '',
        mediaStart: scalar(x, 'MediaStartTime'),
        sourceIn: decodeIn(scalar(x, 'In')),
        mediaPath: blank(x, 'MediaFilePath') ? '' : scalar(x, 'MediaFilePath') || '',
        poolId: scalar(x, 'MediaRef'), // per-project media ref; equal only inside one project
        trackId: t[1],
        gradeVersion: g.gradeVersion,
        hasGrade: /<HasCorrection>true<\/HasCorrection>/.test(x),
        ...(includeGrade ? { gradeBody: g.gradeBody } : {}),
      });
    }
  }
  rows.sort((a, b) => a.trackType - b.trackType || a.start - b.start);
  return rows;
}

/** Unzip a .drp into a temp dir and return {dir, mpFolderXmls, containers:[{file, xml}]}. */
export function openDrp(drpPath) {
  if (!fs.existsSync(drpPath)) throw new Error(`.drp not found: ${drpPath}`);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'drp-clips-'));
  const r = spawnSync('unzip', ['-q', '-o', drpPath, '-d', dir], { encoding: 'utf8' });
  if (r.status !== 0) throw new Error(`unzip failed for ${drpPath}: ${(r.stderr || '').slice(-200)}`);
  const walk = (d, out = []) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p, out);
      else out.push(p);
    }
    return out;
  };
  const files = walk(dir);
  const read = (p) => fs.readFileSync(p, 'utf8');
  return {
    dir,
    mpFolderXmls: files.filter((p) => /MpFolder\.xml$/.test(p)).map(read),
    containers: files.filter((p) => /(^|\/)SeqContainer\/[^/]+\.xml$/.test(p)).map((p) => ({ file: p, xml: read(p) })),
    close: () => {
      try {
        fs.rmSync(dir, { recursive: true, force: true });
      } catch {
        /* ignore */
      }
    },
  };
}

/** readTimelineClips twin for a .drp: clips of the named timeline, video by default. */
export function readTimelineClipsFromDrp(drpPath, timeline, trackType = 'video', includeGrade = false) {
  const drp = openDrp(drpPath);
  try {
    const timelines = listDrpTimelines(drp.mpFolderXmls);
    const tl = timelines.find((t) => t.name === timeline);
    if (!tl) {
      throw new Error(`timeline "${timeline}" not found in ${drpPath}. Timelines: ${timelines.map((t) => JSON.stringify(t.name)).join(', ') || '(none)'}`);
    }
    if (!tl.sequenceId) throw new Error(`timeline "${timeline}" has no <Sm2Sequence> in its media-pool entry`);
    const holder = drp.containers.find((c) => c.xml.includes(`<Sequence>${tl.sequenceId}</Sequence>`));
    if (!holder) throw new Error(`no SeqContainer references sequence ${tl.sequenceId} for timeline "${timeline}"`);
    let rows = parseSeqContainerClips(holder.xml, tl.sequenceId, { includeGrade });
    if (trackType === 'video') rows = rows.filter((r) => r.trackType === 0);
    else if (trackType === 'audio') rows = rows.filter((r) => r.trackType !== 0);
    return rows;
  } finally {
    drp.close();
  }
}
