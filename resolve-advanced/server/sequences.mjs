/**
 * list_sequences — ONE offline enumeration entry point for the app's "which sequence?" picker.
 *
 * Works across xml/fcpxml/edl/otio/drt/drp/aaf and returns a uniform
 *   [{ id, name, eventCount, index }]
 * so the Conform surface can drive a single selector regardless of the turnover format.
 * .prproj is an honest refuse. AAF goes through pyaaf2 (aaf.mjs); drt/drp reuse the DRT parser.
 *
 * Detection is by file extension unless an explicit `format` is passed.
 */
import fs from 'node:fs/promises';
import path from 'node:path';

import { parseInterchange } from './editorial.mjs';
import { listAafSequences } from './aaf.mjs';
import { listPrprojSequences } from './prproj.mjs';
import { drt } from './libs.mjs';

const EXT_FORMAT = {
  '.edl': 'edl',
  '.otio': 'otio',
  '.xml': 'xml',
  '.fcpxml': 'xml',
  '.xmeml': 'xml',
  '.drt': 'drt',
  '.drp': 'drp',
  '.aaf': 'aaf',
  '.prproj': 'prproj',
};

/** Normalize a format string / file extension to a canonical parser key. */
export function detectFormat(filePath, explicit) {
  if (explicit) {
    const f = String(explicit).toLowerCase();
    if (['xmeml', 'fcp7', 'fcpxml'].includes(f)) return 'xml';
    return f;
  }
  const ext = path.extname(String(filePath || '')).toLowerCase();
  const fmt = EXT_FORMAT[ext];
  if (!fmt) {
    throw new Error(`list_sequences: unknown extension '${ext || '(none)'}' — pass an explicit format (edl|otio|xml|drt|drp|aaf).`);
  }
  return fmt;
}

/** Map a parseDRT() result → uniform [{id,name,eventCount,index}]. Shared with the drt tool. */
export function summarizeDrtTimelines(parsed) {
  return (parsed.timelines || []).map((tl, index) => {
    const vids = (tl.videoTracks || []).reduce((n, t) => n + (t.clips ? t.clips.length : 0), 0);
    const auds = (tl.audioTracks || []).reduce((n, t) => n + (t.clips ? t.clips.length : 0), 0);
    return {
      id: parsed.seqContainers && parsed.seqContainers[index] ? parsed.seqContainers[index] : tl.name || `seq${index + 1}`,
      name: tl.name || `Sequence ${index + 1}`,
      eventCount: vids + auds,
      index,
    };
  });
}

/**
 * Enumerate sequences in a turnover file.
 * @param {string} filePath absolute path to the interchange/project file
 * @param {{format?:string, fps?:number}} [opts]
 * @returns {Promise<Array<{id:string,name:string,eventCount:number,index:number}>>}
 */
export async function listSequences(filePath, opts = {}) {
  const fmt = detectFormat(filePath, opts.format);

  if (fmt === 'prproj') return listPrprojSequences(filePath);

  if (fmt === 'aaf') {
    const seqs = await listAafSequences(filePath);
    return seqs.map((s, index) => ({ ...s, index }));
  }

  if (fmt === 'drt' || fmt === 'drp') {
    const parsed = await drt().parseDRT(filePath);
    return summarizeDrtTimelines(parsed);
  }

  // Text interchange (edl/otio/xml/xmeml/fcp7) — a single sequence per file.
  const content = await fs.readFile(filePath, 'utf8');
  const events = parseInterchange(fmt, content, { fps: opts.fps });
  const name = path.basename(filePath);
  return [{ id: name, name, eventCount: events.length, index: 0 }];
}
