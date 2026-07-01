/**
 * media tool — Cluster M media front-end / AE ops. Dry-run PLANS + VERIFY reports (the AE
 * approves any apply). Never rewrites camera originals; path-maps scoped per episode. No Resolve.
 *
 * Actions:
 *   ingest_verify   — seal (hash manifest) / verify / dupes-by-hash (copy-completeness)
 *   media_inventory — ffprobe cards/turnovers → manifest + consistency (fps/codec/space/TC/gaps)
 *   sync            — TC picture↔sound pairing: per-take offset + long-take drift + MOS
 *   relink_manifest — offline media + path-map preflight (dry-run)
 *   rename_plan     — dry-run rename plan; refuses camera originals
 *   reel_normalize  — normalize reel/card names (plan + collisions)
 *   project_hygiene — dupes / orphan-offline / mixed-fps / empty bins / unlabeled versions
 *   turnover_package— assemble + checksum a dated color/sound/VFX folder manifest (dry-run)
 */
import { z } from 'zod';
import { ingestVerify, relinkManifest, renamePlan, reelNormalize, projectHygiene, turnoverPackage } from '../media-ops.mjs';
import { mediaInventory, syncByTC } from '../media-inventory.mjs';

const pathList = z.array(z.union([z.string(), z.object({}).passthrough()]));

const ingestSchema = z.object({
  mode: z.enum(['seal', 'verify', 'dupes']),
  files: pathList.optional(),
  manifest: z.object({}).passthrough().optional(),
  baseDir: z.string().optional(),
  label: z.string().optional(),
});

const inventorySchema = z.object({
  files: z.array(z.union([z.string(), z.object({ id: z.string().optional(), path: z.string(), expectedColorspace: z.string().optional() })])),
});

const syncSchema = z.object({
  clips: z.array(z.object({}).passthrough()).describe('[{id, type:picture|sound, tcStart, tcEnd?, fps, hasAudio?, durationFrames?}]'),
  driftToleranceFrames: z.number().optional(),
  longTakeFrames: z.number().optional(),
});

const relinkSchema = z.object({
  offlinePaths: z.array(z.string()),
  pathMap: z.array(z.object({ from: z.string(), to: z.string() })).describe('Per-episode prefix rewrites (scoped — never global)'),
  checkExists: z.boolean().optional(),
});

const renameSchema = z.object({
  names: z.array(z.string()),
  find: z.string(),
  replace: z.string().optional(),
  allowCameraOriginals: z.boolean().optional(),
});

const reelSchema = z.object({ reels: z.array(z.string()), pad: z.number().optional() });

const hygieneSchema = z.object({ project: z.object({}).passthrough() });

const turnoverSchema = z.object({
  inputs: z.array(z.object({ path: z.string(), category: z.enum(['color', 'sound', 'vfx', 'reference']).optional(), role: z.string().optional() })),
  date: z.string().optional().describe("Dated folder date 'YYYYMMDD' (caller-supplied for determinism)"),
  name: z.string().optional(),
  handles: z.number().optional(),
});

export const mediaTool = {
  name: 'media',
  description:
    'Media front-end / AE ops (Cluster M) — dry-run PLANS + VERIFY reports (AE approves the apply; never rewrites camera originals; path-maps scoped per episode). Actions: ingest_verify (seal a hash manifest / verify copy-completeness / dupes-by-HASH), media_inventory (ffprobe cards → manifest + consistency: mixed fps, wrong-space metadata, card-sequence gaps), sync (TC picture↔sound pairing: per-take offset, long-take drift, MOS), relink_manifest (offline-media + path-map preflight, dry-run), rename_plan (dry-run rename; refuses camera originals), reel_normalize (normalize reel names), project_hygiene (dupes/orphan-offline/mixed-fps/empty-bins/unlabeled-versions), turnover_package (assemble + checksum a dated color/sound/VFX folder manifest). Needs ffprobe for media_inventory.',
  async handler({ action, args }) {
    if (action === 'ingest_verify') {
      const p = ingestSchema.parse(args);
      return ingestVerify(p.mode, { files: p.files, manifest: p.manifest, baseDir: p.baseDir, label: p.label });
    }
    if (action === 'media_inventory') {
      const p = inventorySchema.parse(args);
      return mediaInventory(p.files);
    }
    if (action === 'sync') {
      const p = syncSchema.parse(args);
      return syncByTC(p.clips, { driftToleranceFrames: p.driftToleranceFrames, longTakeFrames: p.longTakeFrames });
    }
    if (action === 'relink_manifest') {
      const p = relinkSchema.parse(args);
      return relinkManifest(p.offlinePaths, p.pathMap, { checkExists: p.checkExists });
    }
    if (action === 'rename_plan') {
      const p = renameSchema.parse(args);
      return renamePlan(p.names, { find: p.find, replace: p.replace, allowCameraOriginals: p.allowCameraOriginals });
    }
    if (action === 'reel_normalize') {
      const p = reelSchema.parse(args);
      return reelNormalize(p.reels, { pad: p.pad });
    }
    if (action === 'project_hygiene') {
      const p = hygieneSchema.parse(args);
      return projectHygiene(p.project);
    }
    if (action === 'turnover_package') {
      const p = turnoverSchema.parse(args);
      return turnoverPackage(p.inputs, { date: p.date, name: p.name, handles: p.handles });
    }
    throw new Error(`Unknown media action: ${action}`);
  },
};
