/**
 * Offline Reference Clip — LIVE PROJECT DB patch path.
 *
 * Unlike the .drp/.drt file patch (offline-ref.mjs), this writes the offline-ref
 * link directly into the project's SQLite `Project.db` — `Sm2Timeline.OfflineClip`
 * is a plain `uuid` column. Because it's the REAL project, DbIds are stable, so the
 * link actually connects on reopen (the file/.drt-import path remaps DbIds and the
 * link dangles). Same DB the Fairlight bus patcher targets.
 *
 * ⚠️ SAFETY (unsanctioned territory — Blackmagic doesn't support DB edits):
 * - Patch ONLY with the project CLOSED (Resolve holds it in RAM + oversaves on save).
 * - Always back up Project.db first (done automatically).
 * - Schema is version-specific — we check the `Sm2Timeline.OfflineClip` column exists
 * and refuse if the schema doesn't match, rather than blindly writing.
 * - Caller must pass iConfirmProjectClosed: true for any write.
 *
 * TWO BACKENDS:
 * - SQLite disk database (default): pass projectDb/projectName. Needs the
 * optional native dep `better-sqlite3` (lazy-loaded).
 * - PostgreSQL (studio databases): pass a `postgres` connection object. The
 * schema mirrors SQLite but identifiers are CamelCase and must be quoted.
 * Needs the optional dep `pg` (lazy-loaded). Connection params come from the
 * caller (host/IpAddress, database/DbName, user, password, port); the password
 * is NEVER hardcoded — pass it (Resolve's default is "DaVinci") or set
 * PGPASSWORD. The project must still be CLOSED, and we pg_dump a backup first.
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

const DISK_DB_ROOT = path.join(os.homedir(), 'Library/Application Support/Blackmagic Design/DaVinci Resolve/Resolve Disk Database/Resolve Projects');

function loadSqlite() {
  try {
    return require('better-sqlite3');
  } catch {
    throw new Error("offline_ref DB path needs the optional native dep 'better-sqlite3'. Install: npm i better-sqlite3");
  }
}

/** Recursively locate <projectName>/Project.db under the Resolve Disk Database. */
export function findProjectDb(projectName, root = DISK_DB_ROOT) {
  const hits = [];
  const walk = (dir, depth) => {
    if (depth > 8) return;
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) {
        if (e.name === projectName && fs.existsSync(path.join(full, 'Project.db'))) {
          hits.push(path.join(full, 'Project.db'));
        }
        walk(full, depth + 1);
      }
    }
  };
  if (fs.existsSync(root)) walk(root, 0);
  return hits;
}

function openDb(dbPath, writable) {
  const Database = loadSqlite();
  if (!fs.existsSync(dbPath)) throw new Error(`Project.db not found: ${dbPath}`);
  const db = new Database(dbPath, { readonly: !writable });
  // schema guard — refuse unless Sm2Timeline.OfflineClip exists (version safety)
  const cols = db
    .prepare('PRAGMA table_info(Sm2Timeline)')
    .all()
    .map((c) => c.name);
  if (!cols.includes('OfflineClip')) {
    db.close();
    throw new Error('Sm2Timeline.OfflineClip column not found — unsupported Project.db schema/version; refusing to patch.');
  }
  return db;
}

function resolveDbPath({ projectDb, projectName }) {
  if (projectDb) return projectDb;
  if (!projectName) throw new Error('provide projectDb (path) or projectName');
  const hits = findProjectDb(projectName);
  if (!hits.length) throw new Error(`no Project.db found for project "${projectName}" under the Resolve Disk Database`);
  if (hits.length > 1) throw new Error(`multiple Project.db match "${projectName}": ${hits.join(', ')} — pass projectDb explicitly`);
  return hits[0];
}

/** List timelines + their current offline-ref state (read-only) — SQLite disk DB. */
function listInProjectSqlite(opts = {}) {
  const dbPath = resolveDbPath(opts);
  const db = openDb(dbPath, false);
  try {
    const rows = db.prepare('SELECT Sm2Timeline_id AS id, Name, OfflineClip, OfflineFrameOffset FROM Sm2Timeline ORDER BY Name').all();
    return { backend: 'sqlite', projectDb: dbPath, count: rows.length, linked: rows.filter((r) => r.OfflineClip).length, timelines: rows };
  } finally {
    db.close();
  }
}

// Resolve a reference clip to its Sm2MpMedia uuid (explicit id, or by name/basename).
function resolveRefId(db, { referenceDbId, referenceName }) {
  if (referenceDbId) return referenceDbId;
  if (!referenceName) throw new Error('provide referenceDbId or referenceName');
  const base = referenceName.split('/').pop();
  const row = db.prepare('SELECT Sm2MpMedia_id AS id, Name FROM Sm2MpMedia WHERE Name = ? OR Name = ?').get(referenceName, base);
  if (!row) throw new Error(`reference clip not found in media pool by name: ${referenceName}`);
  return row.id;
}

function backup(dbPath) {
  const bak = `${dbPath}.bak`;
  fs.copyFileSync(dbPath, bak);
  return bak;
}

function selectTimeline(db, { timelineId, timelineName }) {
  if (timelineId) {
    const r = db.prepare('SELECT Sm2Timeline_id AS id, Name, OfflineClip FROM Sm2Timeline WHERE Sm2Timeline_id = ?').get(timelineId);
    if (!r) throw new Error(`no timeline with id ${timelineId}`);
    return r;
  }
  if (timelineName) {
    const rs = db.prepare('SELECT Sm2Timeline_id AS id, Name, OfflineClip FROM Sm2Timeline WHERE Name = ?').all(timelineName);
    if (!rs.length) throw new Error(`no timeline named "${timelineName}"`);
    if (rs.length > 1) throw new Error(`multiple timelines named "${timelineName}" — pass timelineId`);
    return rs[0];
  }
  throw new Error('provide timelineId or timelineName');
}

/** Link an offline reference clip to a timeline — SQLite disk DB (project CLOSED). */
function linkInProjectSqlite(opts = {}) {
  if (!opts.iConfirmProjectClosed) {
    throw new Error('Refusing to write: close the project in Resolve first (it oversaves on save), then pass iConfirmProjectClosed: true.');
  }
  const dbPath = resolveDbPath(opts);
  const bak = backup(dbPath);
  const db = openDb(dbPath, true);
  try {
    const tl = selectTimeline(db, opts);
    const refId = resolveRefId(db, opts);
    const frameOffset = Number.isInteger(opts.frameOffset) ? opts.frameOffset : 0;
    db.prepare('UPDATE Sm2Timeline SET OfflineClip = ?, OfflineFrameOffset = ? WHERE Sm2Timeline_id = ?').run(refId, frameOffset, tl.id);
    const after = db.prepare('SELECT OfflineClip, OfflineFrameOffset FROM Sm2Timeline WHERE Sm2Timeline_id = ?').get(tl.id);
    return {
      backend: 'sqlite',
      projectDb: dbPath,
      backup: bak,
      timeline: { id: tl.id, name: tl.Name },
      linkedTo: refId,
      frameOffset,
      verified: after.OfflineClip === refId,
    };
  } finally {
    db.close();
  }
}

/** Remove the offline-reference link from a timeline — SQLite disk DB (project CLOSED). */
function unlinkInProjectSqlite(opts = {}) {
  if (!opts.iConfirmProjectClosed) {
    throw new Error('Refusing to write: close the project in Resolve first, then pass iConfirmProjectClosed: true.');
  }
  const dbPath = resolveDbPath(opts);
  const bak = backup(dbPath);
  const db = openDb(dbPath, true);
  try {
    const tl = selectTimeline(db, opts);
    db.prepare('UPDATE Sm2Timeline SET OfflineClip = NULL WHERE Sm2Timeline_id = ?').run(tl.id);
    const after = db.prepare('SELECT OfflineClip FROM Sm2Timeline WHERE Sm2Timeline_id = ?').get(tl.id);
    return { backend: 'sqlite', projectDb: dbPath, backup: bak, timeline: { id: tl.id, name: tl.Name }, verified: after.OfflineClip === null };
  } finally {
    db.close();
  }
}

// ───────────────────────────── PostgreSQL backend ─────────────────────────────
// Studio Resolve databases are Postgres, not a disk SQLite file. The logical
// schema is the same, but identifiers are CamelCase → every one must be quoted.

function loadPg() {
  try {
    return require('pg');
  } catch {
    throw new Error("offline_ref Postgres path needs the optional dep 'pg'. Install: npm i pg");
  }
}

/** Normalize caller connection params (accepts Resolve's IpAddress/DbName aliases). */
function pgConfig(pg = {}) {
  const cfg = {
    host: pg.host || pg.IpAddress,
    port: pg.port || 5432,
    user: pg.user || 'postgres',
    // NEVER hardcode the password. Caller passes it (Resolve default "DaVinci")
    // or it comes from the standard PGPASSWORD env. Undefined → pg uses.pgpass.
    password: pg.password != null ? pg.password : process.env.PGPASSWORD,
    database: pg.database || pg.DbName,
  };
  if (!cfg.host) throw new Error('postgres: provide host (or IpAddress)');
  if (!cfg.database) throw new Error('postgres: provide database (or DbName)');
  return cfg;
}

/** Connect (or use an injected client for tests via pg.__client). */
async function pgConnect(pg) {
  if (pg && pg.__client) return pg.__client;
  const { Client } = loadPg();
  const client = new Client(pgConfig(pg));
  await client.connect();
  return client;
}

async function pgEnd(client, pg) {
  if (pg && pg.__client) return; // injected client — caller owns its lifecycle
  try {
    await client.end();
  } catch {
    /* ignore */
  }
}

async function pgSchemaGuard(client) {
  const { rows } = await client.query("SELECT 1 FROM information_schema.columns WHERE table_name = 'Sm2Timeline' AND column_name = 'OfflineClip' LIMIT 1");
  if (!rows.length) {
    throw new Error('Sm2Timeline.OfflineClip column not found — unsupported Postgres schema/version; refusing to patch.');
  }
}

/** Walk Sm2MpFolder_Owner_id UP from any folder to the project's no-owner Master root. */
async function pgProjectMasterRoot(client, anyFolderId) {
  const { rows } = await client.query(
    `WITH RECURSIVE up AS (SELECT "Sm2MpFolder_id", "Sm2MpFolder_Owner_id" FROM "Sm2MpFolder" WHERE "Sm2MpFolder_id" = $1
 UNION ALL
 SELECT f."Sm2MpFolder_id", f."Sm2MpFolder_Owner_id" FROM "Sm2MpFolder" f JOIN up ON f."Sm2MpFolder_id" = up."Sm2MpFolder_Owner_id")
 SELECT "Sm2MpFolder_id" AS id FROM up WHERE "Sm2MpFolder_Owner_id" IS NULL LIMIT 1`,
    [anyFolderId],
  );
  if (!rows.length) throw new Error(`could not resolve a project Master root from folder ${anyFolderId}`);
  return rows[0].id;
}

/** All folder ids in the project (recursive subtree under the Master root). */
async function pgProjectFolderIds(client, masterRootId) {
  const { rows } = await client.query(
    `WITH RECURSIVE dn AS (SELECT "Sm2MpFolder_id" FROM "Sm2MpFolder" WHERE "Sm2MpFolder_id" = $1
 UNION ALL
 SELECT f."Sm2MpFolder_id" FROM "Sm2MpFolder" f JOIN dn ON f."Sm2MpFolder_Owner_id" = dn."Sm2MpFolder_id")
 SELECT "Sm2MpFolder_id" AS id FROM dn`,
    [masterRootId],
  );
  return rows.map((r) => r.id);
}

/**
 * Resolve a reference clip to its Sm2MpMedia uuid — PROJECT-SCOPED.
 *
 * A studio Postgres holds MANY projects; a bare `WHERE Name=…` returns clips from
 * OTHER projects, and linking OfflineClip to a cross-project clip silently fails to
 * bind (the live API reports it "Clip not found"). So:
 * - PREFER `referenceDbId` resolved via the project-scoped live MCP
 * (media_pool_item get_unique_id / get_clip_property verifies it resolves in the
 * current project). Passed through (verified to exist; and to be in-project when
 * a folder scope is given).
 * - `referenceName` is resolved ONLY within the target project: pass
 * `referenceFolderRoot` = ANY folder uuid in that project (e.g. the Sm2MpFolder_id
 * of a known current-project clip from the MCP). We walk up to the project Master
 * and match the name within its recursive subtree, refusing on multiple matches.
 * - `referenceName` with NO scope is refused — it cannot be made safe on a shared DB.
 */
async function pgResolveRefId(client, { referenceDbId, referenceName, referenceFolderRoot }) {
  // Project subtree (if a scope folder is given).
  let projectFolderIds = null;
  if (referenceFolderRoot) {
    const master = await pgProjectMasterRoot(client, referenceFolderRoot);
    projectFolderIds = await pgProjectFolderIds(client, master);
  }

  if (referenceDbId) {
    const { rows } = await client.query('SELECT "Sm2MpFolder_id" AS folder FROM "Sm2MpMedia" WHERE "Sm2MpMedia_id" = $1', [referenceDbId]);
    if (!rows.length) throw new Error(`referenceDbId ${referenceDbId} is not a media pool clip in this database`);
    if (projectFolderIds && !projectFolderIds.includes(rows[0].folder)) {
      throw new Error(`referenceDbId ${referenceDbId} is NOT in the target project (cross-project clip won't bind) — resolve it via the project-scoped MCP`);
    }
    return referenceDbId;
  }

  if (!referenceName) throw new Error('provide referenceDbId (MCP-verified) or referenceName + referenceFolderRoot');
  if (!projectFolderIds) {
    throw new Error(
      'referenceName on a shared Postgres DB is unreliable (cross-project name collisions) — pass referenceFolderRoot (any folder uuid in the target project) or an MCP-verified referenceDbId',
    );
  }
  const base = referenceName.split('/').pop();
  const { rows } = await client.query(
    'SELECT "Sm2MpMedia_id" AS id, "Name" FROM "Sm2MpMedia" WHERE ("Name" = $1 OR "Name" = $2) AND "Sm2MpFolder_id" = ANY($3::uuid[])',
    [referenceName, base, projectFolderIds],
  );
  if (!rows.length)
    throw new Error(`reference clip "${referenceName}" not found IN THIS PROJECT — import it into the project's media pool first, or pass referenceDbId`);
  if (rows.length > 1) {
    throw new Error(`multiple in-project clips named "${referenceName}" (${rows.map((r) => r.id).join(', ')}) — pass referenceDbId`);
  }
  return rows[0].id;
}

async function pgSelectTimeline(client, { timelineId, timelineName }) {
  if (timelineId) {
    const { rows } = await client.query('SELECT "Sm2Timeline_id" AS id, "Name", "OfflineClip" FROM "Sm2Timeline" WHERE "Sm2Timeline_id" = $1', [timelineId]);
    if (!rows.length) throw new Error(`no timeline with id ${timelineId}`);
    return rows[0];
  }
  if (timelineName) {
    const { rows } = await client.query('SELECT "Sm2Timeline_id" AS id, "Name", "OfflineClip" FROM "Sm2Timeline" WHERE "Name" = $1', [timelineName]);
    if (!rows.length) throw new Error(`no timeline named "${timelineName}"`);
    if (rows.length > 1) throw new Error(`multiple timelines named "${timelineName}" — pass timelineId`);
    return rows[0];
  }
  throw new Error('provide timelineId or timelineName');
}

/** Back up the Sm2Timeline table via pg_dump before a write (test hook: pg.__backupFn). */
function pgBackup(pg) {
  if (pg && typeof pg.__backupFn === 'function') return pg.__backupFn();
  const cfg = pgConfig(pg);
  const out = path.join(os.tmpdir(), `offline-ref-Sm2Timeline-backup-${cfg.database}.sql`);
  const dump = pg.pgDumpPath || 'pg_dump';
  const env = { ...process.env };
  if (cfg.password != null) env.PGPASSWORD = String(cfg.password);
  const r = require('node:child_process').spawnSync(
    dump,
    ['-h', String(cfg.host), '-p', String(cfg.port), '-U', String(cfg.user), '-d', String(cfg.database), '--data-only', '-t', '"Sm2Timeline"', '-w', '-f', out],
    { env, encoding: 'utf8' },
  );
  if (r.status !== 0) {
    throw new Error(
      `pg_dump backup failed (refusing to write without a backup): ${(r.stderr || r.error?.message || 'unknown').toString().slice(-300)}. Pass postgres.pgDumpPath if pg_dump isn't on PATH.`,
    );
  }
  return out;
}

// NOTE: a Postgres database holds EVERY project, so this lists all of their
// timelines (unlike a per-project SQLite Project.db). link/unlink stay correct
// regardless — they target a specific Sm2Timeline_id (or refuse an ambiguous name).
async function listInProjectPg(opts) {
  const pg = opts.postgres;
  const client = await pgConnect(pg);
  try {
    await pgSchemaGuard(client);
    const { rows } = await client.query('SELECT "Sm2Timeline_id" AS id, "Name", "OfflineClip", "OfflineFrameOffset" FROM "Sm2Timeline" ORDER BY "Name"');
    return { backend: 'postgres', database: pgConfig(pg).database, count: rows.length, linked: rows.filter((r) => r.OfflineClip).length, timelines: rows };
  } finally {
    await pgEnd(client, pg);
  }
}

async function linkInProjectPg(opts) {
  if (!opts.iConfirmProjectClosed) {
    throw new Error('Refusing to write: close the project in Resolve first (it oversaves on save), then pass iConfirmProjectClosed: true.');
  }
  const pg = opts.postgres;
  const client = await pgConnect(pg);
  try {
    await pgSchemaGuard(client);
    const tl = await pgSelectTimeline(client, opts);
    const refId = await pgResolveRefId(client, opts);
    const frameOffset = Number.isInteger(opts.frameOffset) ? opts.frameOffset : 0;
    const bak = pgBackup(pg); // back up BEFORE the write
    await client.query('UPDATE "Sm2Timeline" SET "OfflineClip" = $1, "OfflineFrameOffset" = $2 WHERE "Sm2Timeline_id" = $3', [refId, frameOffset, tl.id]);
    const { rows } = await client.query('SELECT "OfflineClip", "OfflineFrameOffset" FROM "Sm2Timeline" WHERE "Sm2Timeline_id" = $1', [tl.id]);
    return { backend: 'postgres', backup: bak, timeline: { id: tl.id, name: tl.Name }, linkedTo: refId, frameOffset, verified: rows[0].OfflineClip === refId };
  } finally {
    await pgEnd(client, pg);
  }
}

async function unlinkInProjectPg(opts) {
  if (!opts.iConfirmProjectClosed) {
    throw new Error('Refusing to write: close the project in Resolve first, then pass iConfirmProjectClosed: true.');
  }
  const pg = opts.postgres;
  const client = await pgConnect(pg);
  try {
    await pgSchemaGuard(client);
    const tl = await pgSelectTimeline(client, opts);
    const bak = pgBackup(pg);
    await client.query('UPDATE "Sm2Timeline" SET "OfflineClip" = NULL WHERE "Sm2Timeline_id" = $1', [tl.id]);
    const { rows } = await client.query('SELECT "OfflineClip" FROM "Sm2Timeline" WHERE "Sm2Timeline_id" = $1', [tl.id]);
    return { backend: 'postgres', backup: bak, timeline: { id: tl.id, name: tl.Name }, verified: rows[0].OfflineClip === null };
  } finally {
    await pgEnd(client, pg);
  }
}

// ───────────────────────── public async dispatchers ─────────────────────────
// Branch on whether a `postgres` connection object is supplied; otherwise the
// SQLite disk-DB path (default). Both are awaited so callers use one async API.

/** List timelines + their current offline-ref state (read-only). */
export async function listInProject(opts = {}) {
  return opts.postgres ? listInProjectPg(opts) : listInProjectSqlite(opts);
}

/** Link an offline reference clip to a timeline (project must be CLOSED). */
export async function linkInProject(opts = {}) {
  return opts.postgres ? linkInProjectPg(opts) : linkInProjectSqlite(opts);
}

/** Remove the offline-reference link from a timeline (project must be CLOSED). */
export async function unlinkInProject(opts = {}) {
  return opts.postgres ? unlinkInProjectPg(opts) : unlinkInProjectSqlite(opts);
}
