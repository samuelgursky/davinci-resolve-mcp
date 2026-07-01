/**
 * project_read tool — "project as a database" READ tier. Read-only SQLite
 * over a Resolve Project.db — full offline introspection, analytics, diff, and a
 * guarded raw-query escape hatch. The Resolve API is a slow GUI-bound RPC that
 * can't expose most of this; SQL exposes all of it instantly.
 *
 * ZERO-RISK: opens the DB READ-ONLY (safe even while the project is open in
 * Resolve), no close/reopen, no backup needed. Pure SQLite → cloud-clean, no
 * Resolve required. Needs optional `better-sqlite3` (lazy).
 *
 * introspect — structured project overview (timelines, folders, media, offline-ref)
 * tables — table inventory + row counts (schema introspection)
 * query — guarded raw SELECT/WITH/PRAGMA (read-only enforced)
 * diff — structural diff of two project DBs
 */

import { z } from 'zod';
import { resolveDbPath, openGuarded } from '../db-patch.mjs';

const dbTarget = {
  projectDb: z.string().optional().describe('Path to a Project.db (a copy is fine)'),
  projectName: z.string().optional().describe('Project name — auto-found under the Resolve Disk Database'),
};

const introspectSchema = z.object({ ...dbTarget });
const timelineClipsSchema = z.object({ ...dbTarget, timeline: z.string().describe('Timeline name'), trackType: z.enum(['video', 'audio', 'all']).optional() });

// Timeline → clips join (RE'd 2026-06-22): the track links to its sequence via
// Sm2TiTrack.Sequence (NOT Sm2Sequence_id, which is empty); the sequence carries
// Sm2Timeline_id. Type: 0=video, 1=audio. The grade Body (DRX-format 0x81+zstd) is
// reached via Sm2TiItem.pLmVerTable → LmVersion(HasCorrection='1').Body.
const TIMELINE_CLIPS_SQL = `
 SELECT i.Name AS name, t.Type AS trackType, i.Start AS start, i.Duration AS duration,
 i.MediaReelNumber AS reel, i.MediaStartTime AS mediaStart, i.Sm2TiTrack_id AS trackId,
 lower(hex(v.Body)) AS gradeBody
 FROM Sm2TiItem i
 JOIN Sm2TiTrack t ON i.Sm2TiTrack_id = t.Sm2TiTrack_id
 JOIN Sm2Sequence s ON t.Sequence = s.Sm2Sequence_id
 JOIN Sm2Timeline tl ON s.Sm2Timeline_id = tl.Sm2Timeline_id
 LEFT JOIN "ListMgt::LmVersion" v ON v."ListMgt::LmVersionTable_id" = i.pLmVerTable AND v.HasCorrection = '1'
 WHERE tl.Name = ?`;
const tablesSchema = z.object({ ...dbTarget, withRowCounts: z.boolean().optional() });
const reportSchema = z.object({ ...dbTarget });
const auditSchema = z.object({ ...dbTarget });

// Per-timeline clip counts (video) via the cracked join — shared by report + audit.
const PER_TIMELINE_SQL = `
 SELECT tl.Name AS timeline, SUM(CASE WHEN t.Type=0 THEN 1 ELSE 0 END) AS video,
 SUM(CASE WHEN t.Type!=0 THEN 1 ELSE 0 END) AS audio
 FROM Sm2Timeline tl
 LEFT JOIN Sm2Sequence s ON s.Sm2Timeline_id = tl.Sm2Timeline_id
 LEFT JOIN Sm2TiTrack t ON t.Sequence = s.Sm2Sequence_id
 LEFT JOIN Sm2TiItem i ON i.Sm2TiTrack_id = t.Sm2TiTrack_id
 GROUP BY tl.Sm2Timeline_id ORDER BY tl.Name`;
const querySchema = z.object({
  ...dbTarget,
  sql: z.string().describe('A single read-only statement (SELECT/WITH/PRAGMA)'),
  limit: z.number().int().positive().optional(),
});
const diffSchema = z.object({ dbA: z.string(), dbB: z.string() });

const READ_ONLY_RE = /^\s*(SELECT|WITH|PRAGMA)\b/i;

function open(opts) {
  return openGuarded(resolveDbPath(opts), { writable: false });
}
function tableExists(db, t) {
  return !!db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?").get(t);
}
function count(db, t) {
  return tableExists(db, t) ? db.prepare(`SELECT COUNT(*) c FROM "${t}"`).get().c : null;
}

/** Read a timeline's clips from a Project.db (read-only). Shared by the
 * timeline_clips action + the color_trace tool. trackType: 'video'|'audio'|'all'. */
export function readTimelineClips(dbPath, timeline, trackType = 'all', includeGrade = false) {
  const db = openGuarded(dbPath, { writable: false });
  try {
    let rows = db.prepare(TIMELINE_CLIPS_SQL).all(timeline);
    if (trackType === 'video') rows = rows.filter((r) => r.trackType === 0);
    else if (trackType === 'audio') rows = rows.filter((r) => r.trackType !== 0);
    rows.sort((a, b) => a.trackType - b.trackType || Number(a.start) - Number(b.start));
    // grade Body is large + only needed for ColorTrace — strip it by default to avoid bloat.
    if (!includeGrade) for (const r of rows) delete r.gradeBody;
    return rows;
  } finally {
    db.close();
  }
}

export const projectReadTool = {
  name: 'project_read',
  description:
    "Read a Resolve Project.db as a database (READ-ONLY, zero-risk, no Resolve needed) — full offline introspection the scripting API can't give. Actions: introspect, timeline_clips (any timeline's clips, even cross/closed-project), report (analytics), audit (QC checks), tables, query (guarded SELECT), diff. Needs optional better-sqlite3.",
  async handler({ action, args }) {
    if (action === 'introspect') {
      const p = introspectSchema.parse(args);
      const dbPath = resolveDbPath(p);
      const db = open(p);
      try {
        const projectVersion = tableExists(db, 'SM_Project') ? (db.prepare('SELECT ProjectVersion v FROM SM_Project LIMIT 1').get()?.v ?? null) : null;
        const tls = tableExists(db, 'Sm2Timeline') ? db.prepare('SELECT Name, OfflineClip FROM Sm2Timeline ORDER BY Name').all() : [];
        const folders = tableExists(db, 'Sm2MpFolder') ? db.prepare('SELECT Name, ColorTag FROM Sm2MpFolder ORDER BY Name').all() : [];
        return {
          projectDb: dbPath,
          projectVersion,
          timelines: { count: tls.length, withOfflineRef: tls.filter((t) => t.OfflineClip).length, names: tls.map((t) => t.Name) },
          folders,
          mediaClips: count(db, 'Sm2MpMedia'),
        };
      } finally {
        db.close();
      }
    }

    if (action === 'timeline_clips') {
      const p = timelineClipsSchema.parse(args);
      const rows = readTimelineClips(resolveDbPath(p), p.timeline, p.trackType || 'all');
      if (!rows.length) throw new Error(`no timeline named "${p.timeline}" (or it has no clips)`);
      return { timeline: p.timeline, clipCount: rows.length, clips: rows };
    }

    if (action === 'tables') {
      const p = tablesSchema.parse(args);
      const db = open(p);
      try {
        const names = db
          .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
          .all()
          .map((r) => r.name);
        if (!p.withRowCounts) return { count: names.length, tables: names };
        return { count: names.length, tables: names.map((n) => ({ name: n, rows: count(db, n) })) };
      } finally {
        db.close();
      }
    }

    if (action === 'report') {
      const p = reportSchema.parse(args);
      const db = open(p);
      try {
        const per = db.prepare(PER_TIMELINE_SQL).all();
        const totalVideo = per.reduce((a, r) => a + (r.video || 0), 0);
        return {
          timelines: per.length,
          totalVideoClips: totalVideo,
          mediaClips: count(db, 'Sm2MpMedia'),
          folders: count(db, 'Sm2MpFolder'),
          offlineRefTimelines: tableExists(db, 'Sm2Timeline') ? db.prepare('SELECT COUNT(OfflineClip) c FROM Sm2Timeline').get().c : 0,
          clipsPerTimeline: per.map((r) => ({ timeline: r.timeline, video: r.video || 0, audio: r.audio || 0 })),
        };
      } finally {
        db.close();
      }
    }

    if (action === 'audit') {
      const p = auditSchema.parse(args);
      const db = open(p);
      try {
        const per = db.prepare(PER_TIMELINE_SQL).all();
        const issues = [];
        const empty = per.filter((r) => !r.video && !r.audio).map((r) => r.timeline);
        if (empty.length) issues.push({ check: 'empty_timelines', severity: 'warn', count: empty.length, timelines: empty });
        if (!per.length) issues.push({ check: 'no_timelines', severity: 'warn' });
        return { timelines: per.length, issues, ok: issues.length === 0 };
      } finally {
        db.close();
      }
    }

    if (action === 'query') {
      const p = querySchema.parse(args);
      if (!READ_ONLY_RE.test(p.sql)) throw new Error('query: only read-only statements allowed (SELECT / WITH / PRAGMA)');
      if (/;\s*\S/.test(p.sql.trim().replace(/;\s*$/, ''))) throw new Error('query: a single statement only (no ";")');
      const db = open(p);
      try {
        const rows = db.prepare(p.sql).all();
        const limit = p.limit ?? 1000;
        return { rowCount: rows.length, truncated: rows.length > limit, rows: rows.slice(0, limit) };
      } finally {
        db.close();
      }
    }

    if (action === 'diff') {
      const p = diffSchema.parse(args);
      const a = openGuarded(p.dbA, { writable: false });
      const b = openGuarded(p.dbB, { writable: false });
      try {
        const tlNames = (db) => new Set((tableExists(db, 'Sm2Timeline') ? db.prepare('SELECT Name FROM Sm2Timeline').all() : []).map((r) => r.Name));
        const na = tlNames(a);
        const nb = tlNames(b);
        return {
          timelines: {
            added: [...nb].filter((n) => !na.has(n)),
            removed: [...na].filter((n) => !nb.has(n)),
            countA: na.size,
            countB: nb.size,
          },
          mediaClips: { a: count(a, 'Sm2MpMedia'), b: count(b, 'Sm2MpMedia') },
          folders: { a: count(a, 'Sm2MpFolder'), b: count(b, 'Sm2MpFolder') },
        };
      } finally {
        a.close();
        b.close();
      }
    }

    throw new Error(`Unknown project_read action: ${action}`);
  },
};
