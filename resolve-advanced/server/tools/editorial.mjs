/**
 * editorial tool — Cluster E editorial integrity. Turnover interchange → normalized events →
 * changelist + conform manifest with TIMING silent-lie guards. Report-only (gate: review). No Resolve.
 *
 * Actions:
 *   parse_interchange     — EDL / OTIO / XMEML / AAF (pyaaf2) / PRPROJ (gunzip+XML) / DRT+DRP (ZIP, one timeline) → normalized events
 *   list_sequences        — ONE picker entry point across xml/edl/otio/drt/drp/aaf/prproj → [{id,name,eventCount}]
 *                           (AAF rows also carry startTimecode/startFrame — see aaf.mjs sequenceSummary)
 *   convert_to_interchange— events (or a parsed source) → OTIO/EDL/DRT Resolve CAN import (the .prproj bridge)
 *   turnover_changelist   — diff old vs new events → shape verdict (identical|subset|superset|edit) + moved/retimed/replaced/new/gone (+timing flags)
 *   conform_manifest      — per-event assert: source resolved, handles, retime, reverse, TC-base
 *   marker_roundtrip      — marker/note round-trip with provenance tags
 */
import fs from 'node:fs/promises';
import { z } from 'zod';
import { parseInterchange, parseDrtEvents, diffChangelist, timingGuards, conformManifest, markerRoundtrip } from '../editorial.mjs';
import { parseAAF, parseAafDocument } from '../aaf.mjs';
import { parsePrproj, parsePrprojDoc } from '../prproj.mjs';
import { listSequences, detectFormat } from '../sequences.mjs';
import { authorInterchange, verifyRoundtrip } from '../author-interchange.mjs';

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

// drt/drp are accepted only so the caller gets parseInterchange's NAMED redirect to the
// path-based reader instead of a bare enum-rejection that reads as "unsupported".
const parseSchema = z.object({
  format: z.enum(['edl', 'otio', 'xml', 'xmeml', 'fcp7', 'aaf', 'prproj', 'drt', 'drp']),
  content: z
    .union([z.string(), z.object({}).passthrough()])
    .describe(
      'EDL text / OTIO JSON (string or object) / XMEML string. For AAF, PRPROJ, DRT or DRP (binary/ZIP): the file PATH.',
    ),
  fps: z.number().optional(),
  timeline: z.union([z.string(), z.number()]).optional().describe('drt/drp only: pool timeline name or index to walk (default: the first timeline-kind container; list_sequences names them)'),
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
  srcTolerance: z.number().optional().describe('Source-frame slack on RETIMED pairs only (default 1): a speed map evaluated and rounded lands a frame apart between apps (E150); 100% pairs compare exactly'),
  timingGuards: z.boolean().optional().describe('Also run the timing silent-lie guards (default true)'),
  sourceAliases: z.array(z.object({ from: z.string().optional(), to: z.string().optional(), pattern: z.string().optional(), replace: z.string().optional(), flags: z.string().optional() })).optional()
    .describe('Rename OLD sources before pairing (E141): {from,to} exact or {pattern,replace} regex — e.g. the offline "4K-2K" proxies vs the online "4K" masters. A systematic rename is also inferred automatically (inferAliases) and reported in sourceAliases.'),
  inferAliases: z.boolean().optional().describe('Infer a systematic source rename from unpaired cuts that share a record window (default true)'),
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
    'Editorial integrity (Cluster E) — turnover interchange → normalized events → changelist + conform manifest with TIMING silent-lie guards (flattened retime / dropped J/L-cut audio / framerate-pulldown slip / reverse dropped / transition-handle starvation → flag, skip-not-fake). Report-only (gate: review). Actions: parse_interchange (EDL/OTIO/XMEML natively — incl. Resolve-written OTIO generator clips (a Solid Color is a Clip with a NULL media_reference; it walks as a BL leg with generatorName, and an OTIO GeneratorReference carries its colour) and nested OTIO Stacks (compound clips — Resolve\'s writer nests them with a trim window) FLATTEN into record time with fromCompound on each cut, so Resolve\'s own OTIO exports re-conform (its FCP7 XML writer flattens a compound to ONE media-less clipitem instead — tagged `compound`, which the bridge drops with a reason in unresolvedCompounds unless the sourceMap maps the compound name to a flattened media file), Resolve-written FCP7 -1 junction edges (paired in record order) + Solid Color / Color Matte generators carrying their `fillcolor` (BL legs with `color` → fade-to-white and colour mattes author, E110), XMEML audio-track transitionitems as audio cross-fades on numbered lanes A/A2/…, and CMX FROM/TO CLIP NAME comments over the generic AX reel — + AAF via pyaaf2 (flat sound/picture slots number A/A2/… and V/V2/… in slot order so separate beds keep their lanes; NestedScope layers keep layer numbering; a NESTED SEQUENCE used as a clip — a SourceClip referencing a named CompositionMob — flattens through its reference window with fromCompound, like OTIO Stacks) + PRPROJ via gunzip+XML (real Premiere 2025 files — uuid ObjectUID/ObjectURef graph, TrackGroups, ClipTrackItem→SubClip→VideoClip→MediaSource→Media chain, zeros written as absence — and the legacy ObjectID/VideoTracks shape both walk; measured on a 739-sequence turnover that used to list ZERO; a NESTED SEQUENCE used as a clip — Source = Video/AudioSequenceSource → Sequence — flattens through its in-point window with fromCompound, like OTIO Stacks and AAF nested compositions; 13,711 such events on one real reels project; real transitions live in the track\'s TransitionItems list — read alongside ClipItems, attached with their DisplayName as type, HasOutgoingClip/HasIncomingClip false = fade from/to black or silence; tracks number as lanes V/V2…/A/A2… and a flattened nested sequence\'s inner lanes first-fit above what the parent already stacks — laneShift records the shift; markers are the sequence\'s OWN, read from Premiere\'s DVAMarker JSON) → normalized events incl. span-explicit transitions, BL fade legs, and freezes as zero-speed events (OTIO FreezeFrame, XMEML timeremap 0, PrProj in==out, AAF 0% motion effects); for AAF/PRPROJ/DRT/DRP pass the file PATH as content; DRT/DRP walk ONE timeline (`timeline` = pool name or index; default the first timeline-kind container) into events with sequence-relative record positions + the returned startFrame/startTimecode/fps read from the pool sequence — <In> is the source in-point (EMPTY on real audio clips → srcInAbsent), a keyed MediaTimemapBA Sm2TimeMap decodes to the speed (E140: the four retimed clips of a real reel read 80 — Premiere\'s 80 for the same cuts — with srcOut following the record window at that speed — and on a retime <In> is RECORD-domain (E143, measured live: the map spans the whole source stretched by 1/speed and the clip windows into that), so the event\'s srcIn is In × speed with the raw value kept as recordDomainIn; a hand conform that typed the source frame straight into In of an 80% clip shows a frame 20% of In earlier than intended, and this reader now says so; XMax 60000 + zero slope = a freeze → the zero-speed in==out event; a negative slope = reverse; a map the decoder cannot read stays speed null + retimeUnknown, never faked to 100%), Sm2TiTransition alignment 2 centres on the cut and 3 ends at it — so two Resolve timeline VERSIONS diff through turnover_changelist (E139); AAF also returns per-sequence startTimecode/startFrame — build the timeline at THAT start, not the Resolve 01:00:00:00 default — and per-clip `geometry` for Avid transform effects), list_sequences (ONE offline picker entry point across xml/edl/otio/drt/drp/aaf/prproj → [{id,name,eventCount}], plus startTimecode/startFrame for AAF and nestedIn — an AAF composition another composition uses as a clip is NESTED in it; offer the parent, its cuts arrive flattened), convert_to_interchange (author OTIO/EDL/DRT Resolve CAN import from events or a parsed source; the EDL target writes CMX transition pairs incl. BL fades — the .prproj→Resolve conform bridge, no Premiere needed; editorial timing/transitions survive and per-clip effects/color do not. SPEED/REVERSE survive on the otio (LinearTimeWarp) and edl (M2) targets ONLY — this FLAT drt target flattens every retime to 100% forward and returns `flattened`/`flattenedCount` naming each event that lost one (`flattened` is always present on `drt`, empty when there were none); for a .drt that AUTHORS retimes/dissolves/multi-track/audio, use drt.assemble_from_interchange), turnover_changelist (diff old vs new → a SHAPE verdict first — identical | subset (new keeps some of old\'s cuts unchanged in place and nothing else: a patch/selects reel of the same cut, NOT N deletions; a real Premiere auto-save kept 3 of 335) | superset (the reverse) | edit — with retained/oldCuts/newCuts, `sparse` and the retainedWindows for subset/superset, a transition that vanished or appeared with the cuts it joins counting as a consequence not an edit; RELINK-AWARE (E141): sourceAliases ({from,to} | {pattern,replace}) rename old sources before pairing, a systematic rename is INFERRED from unpaired cuts sharing a record window (one-to-one, recurring or clearly the same name) — or, for a source whose only cut was re-centred inside a dissolve, from OVERLAPPING windows under clearly-the-same names (LCS ≥ 0.8, E149, `byOverlap`) — and reported in sourceAliases — a real offline→online turnover paired 15 of 228 cuts until the "4K-2K" proxies aliased to the "4K" masters, then 186 — and a constant per-source source-window shift witnessed on ≥2 cuts is a TC REBASE (sourceTcOffsets), not trims; a cut moved INSIDE an unchanged dissolve span with the incoming\'s source-in and the outgoing\'s source-out sliding by the same delta is ONE junction_realigned (E142: Premiere keeps a fractional alignment, Resolve\'s conform re-centres it — 9 of 10 residual moves on a real reel were this; same picture, a consequence not an edit) and two labels of one transition family ("Cross Dissolve (Legacy)" vs "Cross Dissolve") are a relabel in transitionRelabels, so a picture-identical conform reads shape `equivalent`; then moved/retimed/trimmed/replaced/new/gone PLUS the junction diff: transition_added/transition_dropped/transition_changed with fade in/out or dissolve, outgoing/incoming, span and duration/type/pre-roll deltas — zero-length CMX carrier lines and the BL legs that carry fades fold into the junction diff instead of reading as gone/new sources; events pair by closest record position, consumed once, so a source cut twice at two speeds compares instance to instance; + timing flags incl. transition_dropped and dropped_split_audio on any A-track (the guards read the old cut through the same aliases the changelist adopted — E148: a proxy→master rename used to flag every dissolve dropped); a compound seen collapsed in one cut and flattened in the other reports compound_collapsed/compound_expanded once, never replaced+gone), conform_manifest (per-event assert: source resolved/handles/retime/reverse/TC-base; BL-aware — black legs need no source, fades no black-side handles, and a fade-out tail requirement lands on the picture source; a compound clipitem fails source_resolved by NAME with the remedy — map it to a flattened file or turn over as OTIO), marker_roundtrip (markers with provenance tags), verify_roundtrip (input events vs re-export events -> pass/mismatches + fitted per-source TC offsets (each source\'s DOMINANT offset across its cuts, E151 — the first pair\'s used to make 53 unchanged cuts read as drift) + marker compare w/ markersNotInExport honesty flag; FADE-AWARE: BL/Solid-Color legs merge out as blackSegments and fade-window boundary reshapes are excused into fadeReshapedBoundaries instead of failing; RETIME-AWARE: speed/reverse compare pairwise — EXPORT_OTIO carries an authored Sm2TimeMap back as LinearTimeWarp (measured), so a flattened/lost retime fails as drift geometry alone cannot catch; AUDIO-AWARE: declared audio events compare (a video-only export such as EXPORT_EDL flags audioNotInExport instead of failing) (channel legs deduped, mismatches tagged trackType audio) while the mirrored-A1 export of a video-only turnover stays informational; COLOUR-AWARE: an input generator leg carrying a fillcolor (fade-to-white, colour matte) must come back on the same track over its span with the same colour — Resolve\'s FCP7 writer emits it — else generator-colour fails (generatorColours reports the compare) — pass exportedFormat: an OTIO/EDL re-export cannot carry colour (measured) and reports generatorColourNotInExport instead of failing; COMPOUND-AWARE: an XML re-export that collapsed a compound to one clipitem over cuts the input flattened from that compound reports compoundsCollapsedInExport instead of count/source drift; RELINK/REALIGN-AWARE (E146): it runs the changelist first and adopts its inferred source renames (a real offline→online reel went from 216 mismatches to its true differences once "4K-2K" proxies aliased to the "4K" masters), excuses a record edge the changelist folded into junction_realigned (reported in junctionRealigned), and reports a named generator the export does not carry (a counting leader) as generatorsNotInExport; cuts PAIR BY WINDOW like the changelist (E147: same track + source, closest record position, consumed once) so a clip the export lost is one `missing`, an export-only clip one `extra`, and a different shot in the same window a `source` mismatch — never an index cascade over every cut that follows; the conform QC loop-closer). Offline (AAF needs pyaaf2; live AAF/DRP import is on the Python davinci-resolve MCP).',
  async handler({ action, args }) {
    if (action === 'parse_interchange') {
      const p = parseSchema.parse(args);
      // Binary formats parse out-of-band from a PATH: AAF via pyaaf2, .prproj via gunzip+XML.
      if (p.format === 'aaf') {
        // `sequences` carries the per-sequence start timecode, which the flattened event
        // list cannot express — a conform that places events without it lands the whole
        // timeline at the wrong start.
        const { events, sequences } = await parseAafDocument(p.content);
        return { format: 'aaf', count: events.length, events, sequences };
      }
      if (p.format === 'drt' || p.format === 'drp') {
        // A .drt/.drp is a ZIP: the caller must hand over the PATH. Inline bytes
        // (a slurped archive) name the requirement instead of surfacing ENOENT
        // on the first four bytes of the file.
        const isPath = typeof p.content === 'string' && await fs.access(p.content).then(() => true, () => false);
        if (!isPath) throw new Error(`parse_interchange: for ${p.format} pass the file PATH as content — a .${p.format} is a ZIP read by parseDRT(path), not text`);
        const r = await parseDrtEvents(p.content, { timeline: p.timeline });
        return { format: p.format, count: r.events.length, events: r.events, timeline: r.timeline, kind: r.kind, fps: r.fps, startFrame: r.startFrame, startTimecode: r.startTimecode };
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
        // skip-not-fake: the DRT clip schema has no per-clip speed field, so retimes cannot
        // ride into a .drt. Name every event that lost one rather than returning a timeline
        // the caller believes is conformed. Always present on 'drt' (empty = none to lose).
        ...(authored.flattened ? { flattened: authored.flattened, flattenedCount: authored.flattened.length } : {}),
      };
    }
    if (action === 'turnover_changelist') {
      const p = changelistSchema.parse(args);
      const result = diffChangelist(p.old, p.new, { recTolerance: p.recTolerance, srcTolerance: p.srcTolerance, sourceAliases: p.sourceAliases, inferAliases: p.inferAliases });
      // The guards read the old cut through the SAME aliases the changelist adopted (E148).
      if (p.timingGuards !== false) result.timing = timingGuards(p.old, p.new, { sourceAliases: result.sourceAliases });
      return result;
    }
    if (action === 'conform_manifest') {
      const p = conformManifestSchema.parse(args);
      return conformManifest(p.events, p.resolution, { minHandle: p.minHandle, expectTcBase: p.expectTcBase });
    }
    if (action === 'verify_roundtrip') {
      // Round-trip QC: input interchange events vs a re-EXPORT of the
      // authored timeline, normalized for the three measured cross-format
      // conventions (track label, source naming, per-source TC-absolute
      // source frames). Live-proven: AAF -> assemble -> import -> Resolve
      // OTIO export verified pass with srcOffsets 86400.
      const p = z.object({
        input: z.array(z.any()).describe('Normalized events of the ORIGINAL interchange (parse_interchange output)'),
        exported: z.array(z.any()).describe('Normalized events of the re-export (parse_interchange on the exported OTIO/EDL/XML)'),
        recTol: z.number().optional(),
        srcTol: z.number().optional(),
        sourceMap: z.record(z.object({ mediaFilePath: z.string() }).passthrough()).optional()
          .describe('The SAME reel→{mediaFilePath} map the assemble used — lets an EDL reel (CUTSRC) match the re-export\'s file basename (cut_src)'),
        exportedFormat: z.string().optional()
          .describe('Format of the re-export (otio|edl|xml|drt). Generator COLOUR can only be witnessed by an XML re-export (Resolve\'s OTIO/EDL writers carry none — measured); pass it so a colour compare against a colour-blind export reports generatorColourNotInExport instead of failing'),
        inferAliases: z.boolean().optional().describe('Adopt the changelist\'s inferred source renames (proxy→master) and its junction_realigned excuses (default true, E146)'),
      }).parse(args);
      // EDL reels vs exported basenames: derive the alias table from the
      // sourceMap that drove the assemble (the one authority linking them).
      const sourceAliases = {};
      for (const [reel, src] of Object.entries(p.sourceMap || {})) {
        const base = String(src.mediaFilePath).split('/').pop();
        if (base) sourceAliases[reel] = base;
      }
      return verifyRoundtrip(p.input, p.exported, { recTol: p.recTol, srcTol: p.srcTol, sourceAliases, exportedFormat: p.exportedFormat, inferAliases: p.inferAliases });
    }
    if (action === 'marker_roundtrip') {
      const p = markerSchema.parse(args);
      return markerRoundtrip(p.markers, { provenanceTag: p.provenanceTag });
    }
    throw new Error(`Unknown editorial action: ${action}`);
  },
};
