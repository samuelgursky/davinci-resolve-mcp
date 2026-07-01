/**
 * audio tool — offline audio operations via ffmpeg (M5, clean subset).
 * split — split on silence / timecodes / intervals
 * trim — tail-trim to a duration
 * convert — batch format conversion (WAV/MOV/MP3…)
 *
 * Uses ffmpeg via the OPTIONAL deps ffmpeg-static/ffprobe-static — lazy-loaded
 * per call so the core server never depends on them. align/loudness/QC (D1/rest
 * of D2) live in scattered/server-coupled sources and are not yet vendored.
 */

import { z } from 'zod';
import { createRequire } from 'node:module';
import { requireFfmpeg } from '../capabilities.mjs';

const require = createRequire(import.meta.url);

// The vendored modules default to system ffmpeg/ffprobe on PATH (no bundled
// binary — FFmpeg is GPL). Pre-flight a clear error if they aren't installed.
function load(mod) {
  requireFfmpeg();
  return require(`../../vendor/audio/${mod}.js`);
}

const splitSchema = z.object({ input: z.string(), output: z.string().optional(), mode: z.string().optional(), opts: z.object({}).passthrough().optional() });
const trimSchema = z.object({ input: z.string(), output: z.string(), durationFrames: z.number().optional(), opts: z.object({}).passthrough().optional() });
const convertSchema = z.object({ input: z.string(), output: z.string(), opts: z.object({}).passthrough().optional() });

export const audioTool = {
  name: 'audio',
  description:
    'Offline audio ops via system ffmpeg/ffprobe (must be on PATH — not bundled, FFmpeg is GPL; `brew install ffmpeg`). Actions: split (on silence/TC/intervals), trim (tail-trim), convert (format). align/loudness/QC not yet vendored.',
  async handler({ action, args }) {
    if (action === 'split') {
      const p = splitSchema.parse(args);
      const m = load('split');
      const fn = m.splitAudio || m.split || m.default;
      return fn(p.input, { output: p.output, mode: p.mode, ...(p.opts || {}) });
    }
    if (action === 'trim') {
      const p = trimSchema.parse(args);
      const m = load('trim');
      const fn = m.trimAudio || m.trim || m.default;
      return fn(p.input, p.output, { durationFrames: p.durationFrames, ...(p.opts || {}) });
    }
    if (action === 'convert') {
      const p = convertSchema.parse(args);
      const m = load('format-converter');
      const fn = m.convert || m.convertAudio || m.default;
      return fn(p.input, p.output, p.opts || {});
    }
    throw new Error(`Unknown audio action: ${action}`);
  },
};
