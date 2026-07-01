/**
 * deliverable tool — Cluster D deliverable QC / compliance (the #1 reject-preventer).
 * All actions MEASURE-only, report-only (gate: review — never auto-`pass`-clear). No Resolve.
 *
 * Actions:
 *   deliverable_qc         — ffprobe a rendered file vs its spec → pass/fail per field
 *   loudness_qc            — ffmpeg ebur128: integrated LUFS + true-peak dBTP + LRA vs target
 *   reframe_blanking_check — letterbox/pillarbox + active-picture bounds + illegal edge pixels
 *   conform_completeness   — all clips online, handles present, duration == reference (frame-exact)
 *   re_delivery_diff       — old vs new render: frame-count/duration Δ + spec drift
 *   render_manifest        — build (checksums + frame counts) / reconcile actual outputs
 *   expand_deliverable     — model texted/textless/stems/slate/leader entities + their rules
 */
import { z } from 'zod';
import { deliverableQc, loudnessQc, reframeBlankingCheck, conformCompleteness, reDeliveryDiff } from '../deliverable-qc.mjs';
import { buildManifest, reconcileManifest } from '../render-manifest.mjs';
import { expandDeliverable } from '../deliverable-entities.mjs';

const specSchema = z.object({}).passthrough();

const deliverableQcSchema = z.object({
  file: z.string().describe('Rendered media file to QC'),
  spec: specSchema.describe('Deliverable spec: { video:{codec,width,height,fps,scan,color*}, audio:{...}, container, durationSeconds, filenameRegex }'),
  filename: z.string().optional().describe('Override filename for the filenameRegex check (default: basename of file)'),
  fpsTol: z.number().optional(),
});

const loudnessQcSchema = z.object({
  file: z.string().describe('Rendered media file to measure'),
  target: z.object({}).passthrough().describe('{ integrated, integratedTol, truePeakMax, lraMax }'),
});

const reframeSchema = z.object({
  png: z.string().describe('Display-referred extracted frame (PNG)'),
  blackThreshold: z.number().optional(),
  barFraction: z.number().optional(),
});

const conformCompletenessSchema = z.object({
  timeline: z
    .object({ clips: z.array(z.object({}).passthrough()), timelineFrames: z.number().optional() })
    .describe('{ clips:[{id, online?, handleIn?, handleOut?}], timelineFrames? }'),
  referenceFrames: z.number().optional().describe('Offline-reference frame count (frame-exact check)'),
  minHandle: z.number().optional().describe('Minimum handle frames required each side'),
});

const reDeliveryDiffSchema = z.object({ old: z.string(), new: z.string() });

const renderManifestSchema = z
  .object({
    mode: z.enum(['build', 'reconcile']).describe('build a manifest, or reconcile an existing one against disk'),
    outputs: z
      .array(z.object({ name: z.string().optional(), path: z.string(), entity: z.string().optional() }))
      .optional()
      .describe('For build: expected output files'),
    manifest: z.object({}).passthrough().optional().describe('For reconcile: a prior build result'),
    probeFrames: z.boolean().optional(),
  })
  .refine((a) => (a.mode === 'build' ? !!a.outputs : !!a.manifest), { message: 'build needs outputs; reconcile needs manifest' });

const expandSchema = z.object({
  name: z.string().optional(),
  spec: specSchema.describe('Master compliance spec'),
  entities: z.array(z.enum(['texted', 'textless', 'stems_ME', 'slate', 'leader'])).optional(),
});

export const deliverableTool = {
  name: 'deliverable',
  description:
    'Deliverable QC / compliance (Cluster D) — the #1 reject-preventer. MEASURE/report-only (gate: review — never auto-pass-clear). Actions: deliverable_qc (ffprobe a render vs its spec → pass/fail per field: codec/raster/fps/scan/color tags/audio layout/naming/duration), loudness_qc (ebur128 integrated LUFS + true-peak dBTP + LRA vs target), reframe_blanking_check (letterbox/pillarbox + active-picture bounds + illegal edge pixels), conform_completeness (all online, handles, duration == reference frame-exact), re_delivery_diff (old vs new render: frame/duration Δ + spec drift), render_manifest (build checksums+frame-counts / reconcile actual outputs), expand_deliverable (model texted/textless/stems/slate/leader entities + rules). Needs ffmpeg/ffprobe on PATH for the file actions.',
  async handler({ action, args }) {
    if (action === 'deliverable_qc') {
      const p = deliverableQcSchema.parse(args);
      return deliverableQc(p.file, p.spec, { filename: p.filename, fpsTol: p.fpsTol });
    }
    if (action === 'loudness_qc') {
      const p = loudnessQcSchema.parse(args);
      return loudnessQc(p.file, p.target);
    }
    if (action === 'reframe_blanking_check') {
      const p = reframeSchema.parse(args);
      const r = await reframeBlankingCheck(p.png, { blackThreshold: p.blackThreshold, barFraction: p.barFraction });
      if (!r) throw new Error(`reframe_blanking_check: unreadable frame '${p.png}' (skip-not-fake)`);
      return { ...r, gate: 'review' };
    }
    if (action === 'conform_completeness') {
      const p = conformCompletenessSchema.parse(args);
      return conformCompleteness(p.timeline, { referenceFrames: p.referenceFrames, minHandle: p.minHandle });
    }
    if (action === 're_delivery_diff') {
      const p = reDeliveryDiffSchema.parse(args);
      return reDeliveryDiff(p.old, p.new);
    }
    if (action === 'render_manifest') {
      const p = renderManifestSchema.parse(args);
      if (p.mode === 'build') return buildManifest(p.outputs, { probeFrames: p.probeFrames });
      return reconcileManifest(p.manifest, { probeFrames: p.probeFrames });
    }
    if (action === 'expand_deliverable') {
      const p = expandSchema.parse(args);
      return expandDeliverable({ name: p.name, spec: p.spec, entities: p.entities });
    }
    throw new Error(`Unknown deliverable action: ${action}`);
  },
};
