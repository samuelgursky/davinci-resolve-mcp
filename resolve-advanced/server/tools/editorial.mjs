/**
 * editorial tool — Cluster E editorial integrity. Turnover interchange → normalized events →
 * changelist + conform manifest with TIMING silent-lie guards. Report-only (gate: review). No Resolve.
 *
 * Actions:
 *   parse_interchange     — EDL / OTIO / XMEML / AAF (pyaaf2) / PRPROJ (gunzip+XML) → normalized events
 *   list_sequences        — ONE picker entry point across xml/edl/otio/drt/drp/aaf/prproj → [{id,name,eventCount}]
 *   convert_to_interchange— events (or a parsed source) → OTIO/EDL/DRT Resolve CAN import (the .prproj bridge)
 *   turnover_changelist   — diff old vs new events → moved/retimed/replaced/new/gone (+timing flags)
 *   conform_manifest      — per-event assert: source resolved, handles, retime, reverse, TC-base
 *   marker_roundtrip      — marker/note round-trip with provenance tags
 */
import fs from 'node:fs/promises';
import { z } from 'zod';
import { parseInterchange, diffChangelist, timingGuards, conformManifest, markerRoundtrip } from '../editorial.mjs';
import { parseAAF } from '../aaf.mjs';
import { parsePrproj, parsePrprojDoc } from '../prproj.mjs';
import { listSequences, detectFormat } from '../sequences.mjs';
import { authorInterchange } from '../author-interchange.mjs';

const eventArray = z.array(z.object({}).passthrough());

/** Parse any supported turnover file (by path) into normalized events. Async (AAF spawns). */
async function parseAnySource(sourcePath, sourceFormat) {
  const fmt = detectFormat(sourcePath, sourceFormat);
  if (fmt === 'aaf') return parseAAF(sourcePath);
  if (fmt === 'prproj') return parsePrproj(sourcePath);
  if (fmt === 'drt' || fmt === 'drp')
    throw new Error('convert_to_interchange: .drt/.drp already import into Resolve directly — use timeline.import_from_drp, not the bridge.');
  const content = await fs.readFile(sourcePath, 'utf8');
  return parseInterchange(fmt, content, {});
}

const parseSchema = z.object({
  format: z.enum(['edl', 'otio', 'xml', 'xmeml', 'fcp7', 'aaf', 'prproj']),
  content: z
    .union([z.string(), z.object({}).passthrough()])
    .describe('EDL text / OTIO JSON (string or object) / XMEML string. For AAF or PRPROJ (binary): the file PATH.'),
  fps: z.number().optional(),
});

const listSequencesSchema = z.object({
  path: z.string().describe('Absolute path to an xml/fcpxml/edl/otio/drt/drp/aaf/prproj file'),
  format: z.string().optional().describe('Override format detection (edl|otio|xml|drt|drp|aaf|prproj)'),
  fps: z.number().optional(),
});

const convertSchema = z
  .object({
    events: eventArray.optional().describe('Normalized events to author (or provide sourcePath+sourceFormat)'),
    sourcePath: z.string().optional().describe('Parse this file first (edl/otio/xml/aaf/prproj) then author'),
    sourceFormat: z.string().optional().describe('Format of sourcePath (default: detect by extension)'),
    target: z.enum(['otio', 'edl', 'drt']).default('otio').describe('Interchange to author (Resolve-importable)'),
    outputPath: z.string().optional().describe('Write the authored file here; otherwise return the content'),
    name: z.string().optional(),
    fps: z.number().optional(),
  })
  .describe('Author an interchange Resolve can import from events or a parsed source — the .prproj→Resolve bridge');

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
    'Editorial integrity (Cluster E) — turnover interchange → normalized events → changelist + conform manifest with TIMING silent-lie guards (flattened retime / dropped J/L-cut audio / framerate-pulldown slip / reverse dropped / transition-handle starvation → flag, skip-not-fake). Report-only (gate: review). Actions: parse_interchange (EDL/OTIO/XMEML natively + AAF via pyaaf2 + PRPROJ via gunzip+XML → normalized events; for AAF/PRPROJ pass the file PATH as content), list_sequences (ONE offline picker entry point across xml/edl/otio/drt/drp/aaf/prproj → [{id,name,eventCount}]), convert_to_interchange (author OTIO/EDL/DRT Resolve CAN import from events or a parsed source — the .prproj→Resolve conform bridge, no Premiere needed; editorial timing/transitions/speed survive, per-clip effects/color do not), turnover_changelist (diff old vs new → moved/retimed/replaced/new/gone + timing flags), conform_manifest (per-event assert: source resolved/handles/retime/reverse/TC-base), marker_roundtrip (markers with provenance tags). Offline (AAF needs pyaaf2; live AAF/DRP import is on the Python davinci-resolve MCP).',
  async handler({ action, args }) {
    if (action === 'parse_interchange') {
      const p = parseSchema.parse(args);
      // Binary formats parse out-of-band from a PATH: AAF via pyaaf2, .prproj via gunzip+XML.
      if (p.format === 'aaf') {
        const events = await parseAAF(p.content);
        return { format: 'aaf', count: events.length, events };
      }
      if (p.format === 'prproj') {
        const doc = parsePrprojDoc(p.content);
        const events = parsePrproj(p.content);
        return { format: 'prproj', count: events.length, events, projectVersion: doc.projectVersion, mediaPaths: doc.mediaPaths };
      }
      const events = parseInterchange(p.format, p.content, { fps: p.fps });
      return { format: p.format, count: events.length, events };
    }
    if (action === 'list_sequences') {
      const p = listSequencesSchema.parse(args);
      const sequences = await listSequences(p.path, { format: p.format, fps: p.fps });
      return { path: p.path, count: sequences.length, sequences };
    }
    if (action === 'convert_to_interchange') {
      const p = convertSchema.parse(args);
      let events = p.events;
      if (!events || !events.length) {
        if (!p.sourcePath) throw new Error('convert_to_interchange: provide events, or sourcePath (+sourceFormat)');
        events = await parseAnySource(p.sourcePath, p.sourceFormat);
      }
      const authored = await authorInterchange(events, p.target, { name: p.name, fps: p.fps });
      let written = null;
      if (p.outputPath) {
        await fs.writeFile(p.outputPath, authored.buffer || authored.content);
        written = { outputPath: p.outputPath, bytes: (authored.buffer || Buffer.from(authored.content)).length };
      }
      return {
        target: authored.target,
        eventCount: events.length,
        ...(written || { content: authored.content }),
        ...(authored.spec ? { spec: authored.spec } : {}),
      };
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
