/**
 * editorial tool — Cluster E editorial integrity. Turnover interchange → normalized events →
 * changelist + conform manifest with TIMING silent-lie guards. Report-only (gate: review). No Resolve.
 *
 * Actions:
 *   parse_interchange   — EDL / OTIO / XMEML (AAF = honest refuse) → normalized edit events
 *   turnover_changelist — diff old vs new events → moved/retimed/replaced/new/gone (+timing flags)
 *   conform_manifest    — per-event assert: source resolved, handles, retime, reverse, TC-base
 *   marker_roundtrip    — marker/note round-trip with provenance tags
 */
import { z } from 'zod';
import { parseInterchange, diffChangelist, timingGuards, conformManifest, markerRoundtrip } from '../editorial.mjs';

const eventArray = z.array(z.object({}).passthrough());

const parseSchema = z.object({
  format: z.enum(['edl', 'otio', 'xml', 'xmeml', 'fcp7', 'aaf']),
  content: z.union([z.string(), z.object({}).passthrough()]).describe('EDL text / OTIO JSON (string or object) / XMEML string'),
  fps: z.number().optional(),
});

const changelistSchema = z.object({
  old: eventArray.describe('Old (locked-cut) normalized events, OR provide oldFormat+oldContent'),
  new: eventArray.describe('New (turnover) normalized events'),
  recTolerance: z.number().optional(),
  timingGuards: z.boolean().optional().describe('Also run the timing silent-lie guards (default true)'),
});

const conformManifestSchema = z.object({
  events: eventArray,
  resolution: z.object({}).passthrough().describe('source → { online?, path?, handleIn?, handleOut?, tcBase?, reverse?, speed? }'),
  minHandle: z.number().optional(),
  expectTcBase: z.string().optional(),
});

const markerSchema = z.object({
  markers: z.array(
    z.object({ frame: z.number(), name: z.string().optional(), note: z.string().optional(), color: z.string().optional(), source: z.string().optional() }),
  ),
  provenanceTag: z.string().optional(),
});

export const editorialTool = {
  name: 'editorial',
  description:
    'Editorial integrity (Cluster E) — turnover interchange → normalized events → changelist + conform manifest with TIMING silent-lie guards (flattened retime / dropped J/L-cut audio / framerate-pulldown slip / reverse dropped / transition-handle starvation → flag, skip-not-fake). Report-only (gate: review). Actions: parse_interchange (EDL/OTIO/XMEML → events; AAF = honest refuse), turnover_changelist (diff old vs new → moved/retimed/replaced/new/gone + timing flags), conform_manifest (per-event assert: source resolved/handles/retime/reverse/TC-base), marker_roundtrip (markers with provenance tags). PURE/offline.',
  async handler({ action, args }) {
    if (action === 'parse_interchange') {
      const p = parseSchema.parse(args);
      const events = parseInterchange(p.format, p.content, { fps: p.fps });
      return { format: p.format, count: events.length, events };
    }
    if (action === 'turnover_changelist') {
      const p = changelistSchema.parse(args);
      const result = diffChangelist(p.old, p.new, { recTolerance: p.recTolerance });
      if (p.timingGuards !== false) result.timing = timingGuards(p.old, p.new);
      return result;
    }
    if (action === 'conform_manifest') {
      const p = conformManifestSchema.parse(args);
      return conformManifest(p.events, p.resolution, { minHandle: p.minHandle, expectTcBase: p.expectTcBase });
    }
    if (action === 'marker_roundtrip') {
      const p = markerSchema.parse(args);
      return markerRoundtrip(p.markers, { provenanceTag: p.provenanceTag });
    }
    throw new Error(`Unknown editorial action: ${action}`);
  },
};
