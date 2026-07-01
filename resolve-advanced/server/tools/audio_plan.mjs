/**
 * audio_plan tool — Fairlight audio track planning + coverage/loudness analysis
 * (offline, pure Node — the "what routing to build" layer above the bus patcher).
 *
 * list_templates — built-in content-type templates (doc/narrative/podcast/social)
 * select_template — pick a template by content type
 * track_plan — template (+opts) → concrete track/bus plan
 * analyze_coverage — clips → coverage/gap/overlap/silence report
 * check_loudness — measurements vs a target LUFS → pass/fail
 */

import { z } from 'zod';
import { audioFairlight } from '../libs.mjs';

const selectSchema = z.object({ contentType: z.string().describe('documentary | narrative | podcast | social |...') });
const planSchema = z.object({
  contentType: z.string().optional(),
  template: z.object({}).passthrough().optional().describe('Explicit template (else resolved from contentType)'),
  opts: z.object({}).passthrough().optional(),
});
const coverageSchema = z.object({
  clips: z.array(z.object({}).passthrough()).describe('Timeline audio clips: [{ start, duration, track,... }]'),
  opts: z.object({}).passthrough().optional(),
});
const loudnessSchema = z.object({
  measurements: z.object({}).passthrough().describe('Measured loudness: { integratedLUFS, truePeak, lra,... }'),
  targetLUFS: z.number().describe('Target integrated LUFS (e.g. -23 EBU R128, -24 ATSC, -14 streaming)'),
});

export const audioPlanTool = {
  name: 'audio_plan',
  description:
    'Fairlight audio track planning + coverage/loudness analysis — offline, pure Node. Actions: list_templates, select_template, track_plan, analyze_coverage, check_loudness.',
  async handler({ action, args }) {
    const af = audioFairlight();
    if (action === 'list_templates') {
      return { templates: af.AUDIO_TEMPLATES, channelTypes: af.CHANNEL_TYPES, loudnessTargets: af.LOUDNESS_TARGETS };
    }
    if (action === 'select_template') {
      const p = selectSchema.parse(args);
      return { template: af.selectTemplate(p.contentType) };
    }
    if (action === 'track_plan') {
      const p = planSchema.parse(args);
      const template = p.template || af.selectTemplate(p.contentType || 'documentary');
      return { plan: af.generateTrackPlan(template, p.opts || {}) };
    }
    if (action === 'analyze_coverage') {
      const p = coverageSchema.parse(args);
      return af.analyzeAudioCoverage(p.clips, p.opts || {});
    }
    if (action === 'check_loudness') {
      const p = loudnessSchema.parse(args);
      return af.checkLoudness(p.measurements, p.targetLUFS);
    }
    throw new Error(`Unknown audio_plan action: ${action}`);
  },
};
