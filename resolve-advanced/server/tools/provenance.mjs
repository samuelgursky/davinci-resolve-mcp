/**
 * provenance tool — Cluster P provenance / bookkeeping / audit (the trust/defense layer).
 * Report-only (gate: review). PURE/offline. No Resolve.
 *
 * Actions:
 *   gallery_lineage  — stills labels (SC##_approved_v##) + albums + TIFF-for-VFX export plan
 *   grade_provenance — parse the AUTO provenance labels off a grade → per-node "why"
 *   cdl_export       — export ASC CDL from a DRX with a round-trip assert
 *   cdl_diff         — diff two ASC CDL objects
 *   revision_tracking— v001→v004: what changed, who approved (normalized history)
 *   episode_report   — one-page readback: stages/gates/who-when/drift/deliverables/tool+spec version
 */
import { z } from 'zod';
import { galleryLineage, gradeProvenance, cdlExport, cdlDiff, revisionHistory, episodeReport } from '../provenance-audit.mjs';

const drxRef = z
  .object({ drxPath: z.string().optional(), content: z.string().optional() })
  .refine((a) => a.drxPath || a.content, { message: 'provide drxPath or content' });

const gallerySchema = z.object({
  stills: z.array(
    z.object({
      id: z.union([z.string(), z.number()]),
      scene: z.union([z.string(), z.number()]).optional(),
      status: z.string().optional(),
      version: z.number().optional(),
      label: z.string().optional(),
      album: z.string().optional(),
    }),
  ),
  exportFormat: z.string().optional(),
});

const cdlExportSchema = z
  .object({ drxPath: z.string().optional(), content: z.string().optional(), format: z.enum(['cdl', 'ccc']).optional() })
  .refine((a) => a.drxPath || a.content, { message: 'provide drxPath or content' });
const cdlDiffSchema = z.object({ a: z.object({}).passthrough(), b: z.object({}).passthrough(), tol: z.number().optional() });

const revisionSchema = z.object({ revisions: z.array(z.object({}).passthrough()) });
const episodeSchema = z.object({ data: z.object({}).passthrough() });

export const provenanceTool = {
  name: 'provenance',
  description:
    'Provenance / bookkeeping / audit (Cluster P) — the trust/defense layer. Report-only (gate: review). Actions: gallery_lineage (stills label convention SC##_approved_v## + albums + TIFF-for-VFX export plan), grade_provenance ("why is this clip graded this way" — parses the AUTO provenance labels off a grade), cdl_export (export ASC CDL from a DRX with a round-trip assert against the silent-identity lie), cdl_diff (diff two CDLs), revision_tracking (v001→v004: what changed / who approved), episode_report (one-page readback: stages/gates/who-when/drift/deliverables/tool+spec version → markdown). PURE/offline.',
  async handler({ action, args }) {
    if (action === 'gallery_lineage') {
      const p = gallerySchema.parse(args);
      return galleryLineage(p.stills, { exportFormat: p.exportFormat });
    }
    if (action === 'grade_provenance') {
      const p = drxRef.parse(args);
      return gradeProvenance({ drxPath: p.drxPath, content: p.content });
    }
    if (action === 'cdl_export') {
      const p = cdlExportSchema.parse(args);
      return cdlExport({ drxPath: p.drxPath, content: p.content }, { format: p.format });
    }
    if (action === 'cdl_diff') {
      const p = cdlDiffSchema.parse(args);
      return cdlDiff(p.a, p.b, { tol: p.tol });
    }
    if (action === 'revision_tracking') {
      const p = revisionSchema.parse(args);
      return revisionHistory(p.revisions);
    }
    if (action === 'episode_report') {
      const p = episodeSchema.parse(args);
      return episodeReport(p.data);
    }
    throw new Error(`Unknown provenance action: ${action}`);
  },
};
