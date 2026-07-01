/**
 * color_trace tool — a better ColorTrace. Match clips between a SOURCE and
 * TARGET timeline (cross-project, content-key-aware) → a trace plan mapping each
 * target clip to the source clip whose grade should carry over.
 *
 * Resolve's native ColorTrace matches by TC/name/order within a project and breaks
 * on renames/reorders/retimes. This reads clip lists from ANY project's Project.db
 * (READ-only, no Resolve, even cross-project) and matches with a layered key.
 *
 * plan — source timeline + target timeline → { matches[], summary }
 *
 * NOTE (current scope): this is the MATCH engine. The grade read + apply
 * (drx-codec decode → ApplyGradeFromDRX) is the next layer — it needs graded source
 * data + the live API; each match carries a `gradeApply` stub describing what would
 * be traced.
 */

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { z } from 'zod';
import { resolveDbPath } from '../db-patch.mjs';
import { readTimelineClips } from './project_read.mjs';

const side = (name) => ({
  [`${name}ProjectDb`]: z.string().optional(),
  [`${name}ProjectName`]: z.string().optional(),
  [`${name}Timeline`]: z.string(),
});
const planSchema = z.object({
  ...side('source'),
  ...side('target'),
  emitDir: z.string().optional().describe('If set, write a .drx per matched+graded clip here (for ApplyGradeFromDRX via the live API)'),
});

const xmlEscape = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
// Wrap a grade Body (the DRX-format 0x81+zstd blob from LmVersion.Body) in a FULL
// Gallery::GyStill.drx — the structure Resolve's ApplyGradeFromDRX actually applies.
//
export const drxEnvelope = (label, bodyHex) => {
  const stillId = crypto.randomUUID();
  const verId = crypto.randomUUID();
  return `<?xml version="1.0" encoding="UTF-8"?>
<!--DbAppVer="19.1.3.0007" DbPrjVer="14"-->
<Gallery::GyStill DbId="${stillId}">
 <FieldsBlob/>
 <SrcHint>${xmlEscape(label)}</SrcHint>
 <SrcType>1</SrcType>
 <GalleryPath/>
 <Label>${xmlEscape(label)}</Label>
 <RecTC>01:00:00:00</RecTC>
 <SrcTC>00:00:00:00</SrcTC>
 <DpxDescriptor>50</DpxDescriptor>
 <Width>1920</Width>
 <Height>1080</Height>
 <BitDepth>10</BitDepth>
 <PAR>1</PAR>
 <Endianship>1</Endianship>
 <CreateTime>2026-01-01T00:00:00.000</CreateTime>
 <pClipFullVer>
 <ListMgt::LmVersion DbId="${verId}">
 <FieldsBlob/>
 <Name/>
 <HasCorrection>true</HasCorrection>
 <VerType>0</VerType>
 <ImplVersion>1</ImplVersion>
 <IncludedInRecording>true</IncludedInRecording>
 <FlatPassEnabled>false</FlatPassEnabled>
 <RGBAOutputEnabled>false</RGBAOutputEnabled>
 <Body>${bodyHex}</Body>
 <UseVersionClipProcParams>true</UseVersionClipProcParams>
 </ListMgt::LmVersion>
 </pClipFullVer>
 <PrimaryCCMode>0</PrimaryCCMode>
</Gallery::GyStill>
`;
};

// Normalize a clip name to a match key: drop path + extension, lowercase,
// collapse separators, strip trailing version tokens (_v2,.01, etc.).
function normalize(name) {
  let n = String(name || '')
    .split('/')
    .pop()
    .replace(/\.[^.]+$/, '')
    .toLowerCase();
  n = n.replace(/[_\-.\s]+/g, ' ').trim();
  n = n.replace(/\s+v?\d{1,3}$/, '').trim();
  return n;
}

function buildIndex(clips) {
  const exact = new Map();
  const norm = new Map();
  for (const c of clips) {
    if (!c.name) continue;
    if (!exact.has(c.name)) exact.set(c.name, c);
    const k = normalize(c.name);
    if (k && !norm.has(k)) norm.set(k, c);
  }
  return { exact, norm };
}

function matchClip(target, idx) {
  if (target.name && idx.exact.has(target.name)) return { src: idx.exact.get(target.name), method: 'exact-name', confidence: 1.0 };
  const k = normalize(target.name);
  if (k && idx.norm.has(k)) return { src: idx.norm.get(k), method: 'normalized-name', confidence: 0.85 };
  return { src: null, method: null, confidence: 0 };
}

export const colorTraceTool = {
  name: 'color_trace',
  description:
    'Better ColorTrace — match clips between a SOURCE and TARGET timeline (cross-project, from Project.db, read-only, no Resolve) → a trace plan for carrying grades across a re-conform. Action: plan.',
  async handler({ action, args }) {
    if (action === 'plan') {
      const p = planSchema.parse(args);
      const srcDb = resolveDbPath({ projectDb: p.sourceProjectDb, projectName: p.sourceProjectName });
      const tgtDb = resolveDbPath({ projectDb: p.targetProjectDb, projectName: p.targetProjectName });
      const srcClips = readTimelineClips(srcDb, p.sourceTimeline, 'video', true); // includeGrade
      const tgtClips = readTimelineClips(tgtDb, p.targetTimeline, 'video');
      if (!srcClips.length) throw new Error(`source timeline "${p.sourceTimeline}" has no video clips`);
      if (!tgtClips.length) throw new Error(`target timeline "${p.targetTimeline}" has no video clips`);
      if (p.emitDir) fs.mkdirSync(p.emitDir, { recursive: true });

      const idx = buildIndex(srcClips);
      const byMethod = { 'exact-name': 0, 'normalized-name': 0, unmatched: 0 };
      let gradesReady = 0;
      const matches = tgtClips.map((t, i) => {
        const m = matchClip(t, idx);
        byMethod[m.method || 'unmatched'] += 1;
        let gradeApply = null;
        if (m.src && m.src.gradeBody) {
          gradesReady += 1;
          gradeApply = { status: 'ready', sourceClip: m.src.name };
          if (p.emitDir) {
            // emit a .drx (lossless source-grade pass-through) for ApplyGradeFromDRX onto the target clip.
            const drxPath = path.join(p.emitDir, `trace-${String(i).padStart(4, '0')}.drx`);
            fs.writeFileSync(drxPath, drxEnvelope(m.src.name, m.src.gradeBody));
            gradeApply.drxPath = drxPath;
            gradeApply.applyVia = { api: 'timeline_item_color.safe_apply_drx', target: { timeline: p.targetTimeline, clipName: t.name, start: t.start } };
          }
        } else if (m.src) {
          gradeApply = { status: 'no-source-grade', sourceClip: m.src.name };
        }
        return {
          target: { name: t.name, start: t.start },
          source: m.src ? { name: m.src.name, start: m.src.start } : null,
          method: m.method,
          confidence: m.confidence,
          gradeApply,
        };
      });
      const matched = matches.filter((m) => m.source).length;
      return {
        source: { timeline: p.sourceTimeline, clips: srcClips.length },
        target: { timeline: p.targetTimeline, clips: tgtClips.length },
        summary: { matched, unmatched: tgtClips.length - matched, gradesReady, byMethod },
        emitDir: p.emitDir || null,
        matches,
      };
    }
    throw new Error(`Unknown color_trace action: ${action}`);
  },
};
