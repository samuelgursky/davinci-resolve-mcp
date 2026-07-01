/**
 * offline_ref tool — timeline Offline Reference Clip link in .drp/.drt.
 * Plain-XML surgery (no FieldsBlob codec). The scripting API has NO method for
 * this, so file patching is the only programmatic route. Works on.drp and .drt.
 *
 * get — list offline-reference links in a file
 * set — link a reference clip to timeline(s) (insert/replace <OfflineClip>)
 * clear — unlink (remove <OfflineClip>)
 */

import { z } from 'zod';
import { getOfflineReferences, setOfflineReference, clearOfflineReference } from '../offline-ref.mjs';
import { listInProject, linkInProject, unlinkInProject } from '../offline-ref-db.mjs';

const getSchema = z.object({ filePath: z.string().describe('Absolute path to a .drp or .drt') });

const setSchema = z.object({
  filePath: z.string().describe('Absolute path to the source.drp/.drt'),
  outputPath: z.string().optional().describe('Where to write (default: in place)'),
  links: z
    .array(
      z.object({
        timelineDbId: z.string().optional().describe('Target timeline Sm2MpTimelineClip DbId (omit for a single-timeline.drt)'),
        allTimelines: z.boolean().optional().describe('Apply to every timeline in the file'),
        referenceDbId: z.string().optional().describe('Sm2MpVideoClip DbId of the reference movie (reliable)'),
        referenceMovie: z.string().optional().describe('Path/basename of the reference movie (best-effort resolution to DbId)'),
      }),
    )
    .describe('One or more link specs'),
  backup: z.boolean().optional().describe('Write a.bak of the source first (default true)'),
});

const clearSchema = z.object({
  filePath: z.string().describe('Absolute path to the source.drp/.drt'),
  outputPath: z.string().optional(),
  timelineDbIds: z.array(z.string()).optional().describe('Timelines to unlink (by DbId)'),
  all: z.boolean().optional().describe('Unlink every timeline'),
  backup: z.boolean().optional(),
});

// --- LIVE PROJECT DB path (Sm2Timeline.OfflineClip; project must be CLOSED) ---
// SQLite disk DB (projectDb/projectName) OR PostgreSQL studio DB (postgres {...}).
const pgSchema = z
  .object({
    host: z.string().optional().describe('Postgres host (or use IpAddress)'),
    IpAddress: z.string().optional().describe('Resolve database IpAddress (alias for host) — from project_manager_database list'),
    port: z.number().int().optional().describe('default 5432'),
    user: z.string().optional().describe('default "postgres"'),
    password: z.string().optional().describe('NEVER hardcoded — pass it (Resolve default "DaVinci") or set PGPASSWORD'),
    database: z.string().optional().describe('Postgres database name (or DbName)'),
    DbName: z.string().optional().describe('Resolve DbName (alias for database)'),
    pgDumpPath: z.string().optional().describe('Absolute path to pg_dump if not on PATH'),
  })
  .optional()
  .describe('Supply to target a PostgreSQL studio database instead of a SQLite disk DB');

const dbTarget = {
  projectDb: z.string().optional().describe('SQLite: path to the project Project.db (else resolved from projectName)'),
  projectName: z.string().optional().describe('SQLite: project name — auto-found under the Resolve Disk Database'),
  postgres: pgSchema,
};
const listDbSchema = z.object({ ...dbTarget });
const linkDbSchema = z.object({
  ...dbTarget,
  timelineName: z.string().optional(),
  timelineId: z.string().optional().describe('Sm2Timeline_id'),
  referenceDbId: z
    .string()
    .optional()
    .describe(
      'Sm2MpMedia uuid of the reference clip — PREFERRED on Postgres; resolve it via the project-scoped MCP (media_pool_item get_unique_id / get_clip_property)',
    ),
  referenceName: z
    .string()
    .optional()
    .describe(
      'Reference clip name/basename. On Postgres requires referenceFolderRoot (shared DB → cross-project name collisions); SQLite is single-project so name alone is fine',
    ),
  referenceFolderRoot: z
    .string()
    .optional()
    .describe(
      'Postgres only: ANY Sm2MpFolder uuid in the target project (e.g. the folder of a known current-project clip from the MCP) — scopes referenceName to that project',
    ),
  frameOffset: z.number().int().optional(),
  iConfirmProjectClosed: z.boolean().optional().describe('Required true — the project must be closed in Resolve before patching'),
});
const unlinkDbSchema = z.object({
  ...dbTarget,
  timelineName: z.string().optional(),
  timelineId: z.string().optional(),
  iConfirmProjectClosed: z.boolean().optional(),
});

export const offlineRefTool = {
  name: 'offline_ref',
  description:
    'Timeline Offline Reference Clip link — the source-viewer wipe/diff reference for conform QC (no scripting API exists). FILE path (plain XML in .drp/.drt): get, set, clear — but .drt-import remaps DbIds so the link may not connect. LIVE DB path (Sm2Timeline.OfflineClip; DbIds stable so it CONNECTS, project must be CLOSED): list_in_project, link_in_project, unlink_in_project — works on a SQLite disk database (projectDb/projectName) OR a PostgreSQL studio database (pass a `postgres` connection object). On Postgres the reference is PROJECT-SCOPED: pass an MCP-verified referenceDbId, or referenceName + referenceFolderRoot (any folder uuid in the target project) — a bare referenceName is refused because a shared DB collides clip names across projects.',
  async handler({ action, args }) {
    if (action === 'get') {
      const p = getSchema.parse(args);
      return getOfflineReferences(p.filePath);
    }
    if (action === 'set') {
      const p = setSchema.parse(args);
      return setOfflineReference(p.filePath, { links: p.links, outputPath: p.outputPath, backup: p.backup });
    }
    if (action === 'clear') {
      const p = clearSchema.parse(args);
      return clearOfflineReference(p.filePath, { timelineDbIds: p.timelineDbIds, all: p.all, outputPath: p.outputPath, backup: p.backup });
    }
    if (action === 'list_in_project') {
      return await listInProject(listDbSchema.parse(args));
    }
    if (action === 'link_in_project') {
      return await linkInProject(linkDbSchema.parse(args));
    }
    if (action === 'unlink_in_project') {
      return await unlinkInProject(unlinkDbSchema.parse(args));
    }
    throw new Error(`Unknown offline_ref action: ${action}`);
  },
};
