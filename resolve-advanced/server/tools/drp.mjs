/**
 * drp tool — DaVinci Resolve project (.drp) authoring + editing. All actions
 * local/offline (the server-only validate/validate_async/status from a
 * managed/API-backed build are intentionally omitted — this MCP has no API backend).
 *
 * Author: create_empty_project, assemble_timeline, add_media_clip
 * Place: place_fusion_title, place_generator, place_transition
 * Edit: move_clip, delete_clip, trim_clip, trim_clip_head, split_clip, ripple_timeline
 * Media: relink_media, repoint_media
 * Grade: inject_grades, extract_node_graphs, diff
 */

import fs from 'node:fs/promises';
import { z } from 'zod';
import { drp } from '../libs.mjs';
import { decodeGroupGrades } from '../group-grade-read.mjs';

const xmlEscape = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');

// Selector fields shared by the in-place edit ops.
const sel = {
  clipIndex: z.number().int().nonnegative().optional().describe('0-based clip on the track (default 0)'),
  clipDbId: z.string().optional().describe('Select the clip by DbId'),
  nameContains: z.string().optional().describe('Select the clip by Name substring'),
  timelineUuid: z.string().optional().describe('Target SeqContainer DbId; default = first timeline with a video track'),
  trackType: z.enum(['video', 'audio']).optional().describe('Track vector: video (default) or audio'),
};
const io = {
  drpPath: z.string().describe('Absolute path to the source.drp'),
  outputPath: z.string().describe('Absolute path for the written .drp'),
};

const S = {
  create_empty_project: z.object({ outputPath: io.outputPath, timelineName: z.string().optional() }),
  assemble_timeline: z.object({
    outputPath: io.outputPath,
    spec: z
      .object({})
      .passthrough()
      .describe('{ timelineName?, elements:[{type:"title"|"generator",track,startFrame,...}], transitions? } — startFrame >= 86400'),
  }),
  add_media_clip: z.object({
    outputPath: io.outputPath,
    mediaFile: z.string(),
    spec: z.object({ width: z.number().int(), height: z.number().int(), frameCount: z.number().int(), fps: z.number() }),
    timelineName: z.string().optional(),
    durationFrames: z.number().int().positive().optional(),
  }),
  place_fusion_title: z.object({
    ...io,
    startFrame: z.number().int(),
    trackIndex: z.number().int().positive().optional(),
    durationFrames: z.number().int().positive().optional(),
    name: z.string().optional(),
    text: z.string().optional(),
    font: z.string().optional(),
    style: z.string().optional(),
    size: z.number().optional(),
    vJustify: z.number().int().optional(),
    hJustify: z.number().int().optional(),
    color: z.object({ r: z.number(), g: z.number(), b: z.number() }).partial().optional(),
    timelineUuid: sel.timelineUuid,
  }),
  place_generator: z.object({
    ...io,
    startFrame: z.number().int(),
    generatorName: z.string().optional(),
    trackIndex: z.number().int().positive().optional(),
    durationFrames: z.number().int().positive().optional(),
    timelineUuid: sel.timelineUuid,
  }),
  place_transition: z.object({
    ...io,
    track: z.number().int().positive(),
    atFrame: z.number().int(),
    durationFrames: z.number().int().positive().optional(),
    timelineUuid: sel.timelineUuid,
  }),
  move_clip: z.object({ ...io, fromTrack: z.number().int().positive(), toTrack: z.number().int().positive(), toStart: z.number().int().optional(), ...sel }),
  delete_clip: z.object({ ...io, fromTrack: z.number().int().positive(), ripple: z.boolean().optional(), ...sel }),
  trim_clip: z.object({ ...io, track: z.number().int().positive(), newDuration: z.number().int().positive(), ripple: z.boolean().optional(), ...sel }),
  trim_clip_head: z.object({ ...io, track: z.number().int().positive(), frames: z.number().int().positive(), ripple: z.boolean().optional(), ...sel }),
  split_clip: z.object({ ...io, track: z.number().int().positive(), at: z.number().int(), timelineUuid: sel.timelineUuid, trackType: sel.trackType }),
  ripple_timeline: z.object({ ...io, at: z.number().int(), delta: z.number().int(), timelineUuid: sel.timelineUuid }),
  relink_media: z.object({ ...io, mappings: z.array(z.object({ from: z.string(), to: z.string() })) }),
  repoint_media: z.object({ ...io, mappings: z.array(z.object({}).passthrough()).describe('[{from,to,fromSpec,toSpec}] spec={width,height,frameCount,fps}') }),
  inject_grades: z.object({ ...io, grades: z.array(z.object({}).passthrough()).describe('[{ clipId|resolveId, drxContent }]') }),
  extract_node_graphs: z.object({ drpPath: io.drpPath, includeBodyHex: z.boolean().optional() }),
  extract_group_grades: z.object({
    drpPath: io.drpPath,
    groups: z.array(z.string()).optional().describe('Color group names; default = all groups in the project'),
    includePreClip: z.boolean().optional(),
  }),
  diff: z.object({ pathA: z.string(), pathB: z.string() }),
  extract_lut_refs: z.object({ drpPath: io.drpPath }),
};

// Ops that take (drpPath, opts) and return { buffer,...accounting }. We strip
// the buffer from the response after writing it.
async function writeOp(fnName, drpPath, opts, outputPath) {
  const gen = drp();
  if (typeof gen[fnName] !== 'function') return { error: `drp-format does not expose ${fnName}` };
  const res = await gen[fnName](drpPath, opts);
  await fs.writeFile(outputPath, res.buffer);
  return { outputPath, bytes: res.buffer.length, ...res, buffer: undefined };
}

export const drpTool = {
  name: 'drp',
  description:
    'DaVinci Resolve project (.drp) authoring + editing — offline, no Resolve required. Actions: create_empty_project, assemble_timeline, add_media_clip, place_fusion_title, place_generator, place_transition, move_clip, delete_clip, trim_clip, trim_clip_head, split_clip, ripple_timeline, relink_media, repoint_media, inject_grades, extract_node_graphs, extract_group_grades, diff, extract_lut_refs.',
  async handler({ action, args }) {
    const gen = drp();

    if (action === 'create_empty_project') {
      const p = S.create_empty_project.parse(args);
      const res = await gen.createEmptyProject({ timelineName: p.timelineName });
      await fs.writeFile(p.outputPath, res.buffer);
      return { outputPath: p.outputPath, bytes: res.buffer.length, timelineName: res.timelineName, startFrame: res.startFrame };
    }
    if (action === 'assemble_timeline') {
      const p = S.assemble_timeline.parse(args);
      const res = await gen.assembleTimeline(p.spec);
      await fs.writeFile(p.outputPath, res.buffer);
      return { outputPath: p.outputPath, bytes: res.buffer.length, timelineName: res.timelineName, startFrame: res.startFrame };
    }
    if (action === 'add_media_clip') {
      const p = S.add_media_clip.parse(args);
      const res = await gen.addMediaClip({ mediaFile: p.mediaFile, spec: p.spec, timelineName: p.timelineName, durationFrames: p.durationFrames });
      await fs.writeFile(p.outputPath, res.buffer);
      return { outputPath: p.outputPath, bytes: res.buffer.length, timelineName: res.timelineName, mediaFile: res.mediaFile };
    }

    if (action === 'place_fusion_title') {
      const p = S.place_fusion_title.parse(args);
      const { drpPath, outputPath, ...opts } = p;
      return writeOp('placeFusionTitle', drpPath, opts, outputPath);
    }
    if (action === 'place_generator') {
      const p = S.place_generator.parse(args);
      const { drpPath, outputPath, ...opts } = p;
      return writeOp('placeGenerator', drpPath, opts, outputPath);
    }
    if (action === 'place_transition') {
      const p = S.place_transition.parse(args);
      const { drpPath, outputPath, ...opts } = p;
      return writeOp('placeTransition', drpPath, opts, outputPath);
    }
    if (action === 'move_clip') {
      const p = S.move_clip.parse(args);
      const { drpPath, outputPath, ...opts } = p;
      return writeOp('moveClip', drpPath, opts, outputPath);
    }
    if (action === 'delete_clip') {
      const p = S.delete_clip.parse(args);
      const { drpPath, outputPath, ...opts } = p;
      return writeOp('deleteClip', drpPath, opts, outputPath);
    }
    if (action === 'trim_clip') {
      const p = S.trim_clip.parse(args);
      const { drpPath, outputPath, ...opts } = p;
      return writeOp('trimClip', drpPath, opts, outputPath);
    }
    if (action === 'trim_clip_head') {
      const p = S.trim_clip_head.parse(args);
      const { drpPath, outputPath, ...opts } = p;
      return writeOp('trimClipHead', drpPath, opts, outputPath);
    }
    if (action === 'split_clip') {
      const p = S.split_clip.parse(args);
      const { drpPath, outputPath, ...opts } = p;
      return writeOp('splitClip', drpPath, opts, outputPath);
    }
    if (action === 'ripple_timeline') {
      const p = S.ripple_timeline.parse(args);
      const { drpPath, outputPath, ...opts } = p;
      return writeOp('rippleTimeline', drpPath, opts, outputPath);
    }

    if (action === 'relink_media') {
      const p = S.relink_media.parse(args);
      const res = await gen.relinkMedia(p.drpPath, { mappings: p.mappings });
      await fs.writeFile(p.outputPath, res.buffer);
      return { outputPath: p.outputPath, bytes: res.buffer.length, relinked: res.relinked };
    }
    if (action === 'repoint_media') {
      const p = S.repoint_media.parse(args);
      const res = await gen.repointMedia(p.drpPath, { mappings: p.mappings });
      await fs.writeFile(p.outputPath, res.buffer);
      return { outputPath: p.outputPath, bytes: res.buffer.length, relinked: res.relinked, specPatched: res.specPatched };
    }

    if (action === 'inject_grades') {
      const p = S.inject_grades.parse(args);
      const report = await gen.injectGrades(p.drpPath, p.grades, { outputPath: p.outputPath });
      return { outputPath: p.outputPath, gradeCount: p.grades.length, bytes: report.bytes, clipsInjected: report.clipsInjected, misses: report.misses };
    }
    if (action === 'diff') {
      const p = S.diff.parse(args);
      return gen.diff(p.pathA, p.pathB);
    }
    if (action === 'extract_lut_refs') {
      const p = S.extract_lut_refs.parse(args);
      if (typeof gen.extractProjectLUTRefs !== 'function') return { error: 'drp-format does not expose extractProjectLUTRefs' };
      const refs = await gen.extractProjectLUTRefs(p.drpPath);
      return { drpPath: p.drpPath, recognizedSlots: gen.LUT_RECOGNIZED_SLOTS, refs };
    }
    if (action === 'extract_node_graphs') {
      const p = S.extract_node_graphs.parse(args);
      const internals = gen.diffInternals || gen._diffInternals;
      const indexFn = internals && internals.indexDrp;
      if (!indexFn) return { error: 'drp-format does not expose diff internals (indexDrp)' };
      const index = await indexFn(p.drpPath);
      const graphs = [];
      for (const clip of index.clipsById.values()) {
        if (!clip.bodyHex) continue;
        const drxContent = `<?xml version="1.0" encoding="UTF-8"?>\n<Resolve_Color_Exchange>\n <Label>${xmlEscape(clip.mediaFilePath || clip.clipId)}</Label>\n <Width>1920</Width>\n <Height>1080</Height>\n <Body>${clip.bodyHex}</Body>\n</Resolve_Color_Exchange>\n`;
        const entry = { clipId: clip.clipId, trackType: clip.trackType, sequence: clip.sequence, mediaFilePath: clip.mediaFilePath, drxContent };
        if (p.includeBodyHex) entry.bodyHex = clip.bodyHex;
        graphs.push(entry);
      }
      return { drpPath: p.drpPath, clipsWithGrade: graphs.length, totalClips: index.clipsById.size, graphs };
    }
    if (action === 'extract_group_grades') {
      const p = S.extract_group_grades.parse(args);
      const groups = await decodeGroupGrades(p.drpPath, { groups: p.groups, includePreClip: p.includePreClip });
      return { drpPath: p.drpPath, groupCount: Object.keys(groups).length, groups };
    }

    throw new Error(`Unknown drp action: ${action}`);
  },
};
