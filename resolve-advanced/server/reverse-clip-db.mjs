/**
 * Reversed timeline-clip repair — LIVE PROJECT DB patch path.
 *
 * Importing a conform (XML/DRT) into Resolve drops a reversed subclip's retime AND
 * mangles its source frame. This restores both at the DB level (validated live on
 * Resolve 19.1.3 / PostgreSQL):
 *
 * 1. Restore reverse: copy a GENERIC reverse `Sm2TiItem.MediaTimemapBA` blob from
 * any reversed clip of the SAME media. The blob is a full-media reverse curve
 * (nothing clip-specific) and — unlike transform `EffectFiltersBA` blobs — it
 * SURVIVES a cold close/reopen.
 * 2. Set the source frame via `Sm2TiItem."In"` (varchar). For a reversed clip the
 * displayed `get_source_start_frame` is the MIRROR of In: `displayed = K - In`.
 * Calibrate K from one readback (set a probe In, reopen, read displayed →
 * `K = probeIn + displayed`), then `In = K - targetFrame`.
 *
 * Scoping: the reversed item is found timeline-scoped via
 * Sm2Timeline.Sequence → Sm2TiTrack.Sequence → Sm2TiItem.Sm2TiTrack_id.
 * The generic reverse blob source can be ANY clip of that media (blob is generic).
 *
 * ⚠️ SAFETY: patch ONLY with the project CLOSED (Resolve oversaves on save); the
 * row is backed up first (In + MediaTimemapBA hex); caller passes iConfirmProjectClosed.
 *
 * Two backends (mirrors offline-ref-db.mjs): SQLite disk DB (better-sqlite3) and
 * PostgreSQL studio DB (pg) — pass a `postgres` connection object for the latter.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

function loadSqlite() {
  try {
    return require('better-sqlite3');
  } catch {
    throw new Error("reverse-clip DB path needs the optional native dep 'better-sqlite3'. Install: npm i better-sqlite3");
  }
}
function loadPg() {
  try {
    return require('pg');
  } catch {
    throw new Error("reverse-clip Postgres path needs the optional dep 'pg'. Install: npm i pg");
  }
}

// ---- SQLite backend ----
function openSqlite(dbPath, writable) {
  const Database = loadSqlite();
  if (!fs.existsSync(dbPath)) throw new Error(`Project.db not found: ${dbPath}`);
  const db = new Database(dbPath, { readonly: !writable });
  const cols = db
    .prepare('PRAGMA table_info(Sm2TiItem)')
    .all()
    .map((c) => c.name);
  for (const need of ['In', 'MediaTimemapBA', 'Sm2TiTrack_id', 'MediaFilePath']) {
    if (!cols.includes(need)) {
      db.close();
      throw new Error(`Sm2TiItem.${need} not found — unsupported schema; refusing to patch.`);
    }
  }
  return db;
}

function sqliteLocate(db, { timelineId, timelineName, mediaPathContains }) {
  const where = timelineId ? 'tl."Sm2Timeline_id" = ?' : 'tl."Name" = ?';
  const arg = timelineId || timelineName;
  const rows = db
    .prepare(
      `SELECT i."Sm2TiItem_id" AS id, i."In" AS inv, i."Start" AS start, LENGTH(i."MediaTimemapBA") AS tmlen, i."MediaFilePath" AS path
 FROM "Sm2TiItem" i
 JOIN "Sm2TiTrack" tr ON i."Sm2TiTrack_id" = tr."Sm2TiTrack_id"
 JOIN "Sm2Timeline" tl ON tr."Sequence" = tl."Sequence"
 WHERE ${where} AND i."MediaFilePath" LIKE ?`,
    )
    .all(arg, `%${mediaPathContains}%`);
  return rows;
}
function sqliteBlobSource(db, { mediaPathContains, minBlobLen }) {
  return db
    .prepare(
      `SELECT "Sm2TiItem_id" AS id, LENGTH("MediaTimemapBA") AS tmlen FROM "Sm2TiItem"
 WHERE "MediaFilePath" LIKE ? AND LENGTH("MediaTimemapBA") >= ? ORDER BY tmlen DESC LIMIT 1`,
    )
    .get(`%${mediaPathContains}%`, minBlobLen);
}

// ---- PostgreSQL backend ----
function pgConfig(pg = {}) {
  const cfg = {
    host: pg.host || pg.IpAddress,
    port: pg.port || 5432,
    user: pg.user || 'postgres',
    password: pg.password != null ? pg.password : process.env.PGPASSWORD,
    database: pg.database || pg.DbName,
  };
  if (!cfg.host) throw new Error('postgres: provide host (or IpAddress)');
  if (!cfg.database) throw new Error('postgres: provide database (or DbName)');
  return cfg;
}
async function pgConnect(pg) {
  if (pg && pg.__client) return pg.__client;
  const { Client } = loadPg();
  const client = new Client(pgConfig(pg));
  await client.connect();
  return client;
}
async function pgEnd(client, pg) {
  if (pg && pg.__client) return;
  try {
    await client.end();
  } catch {
    /* ignore */
  }
}
async function pgGuard(client) {
  const { rows } = await client.query(
    "SELECT column_name FROM information_schema.columns WHERE table_name='Sm2TiItem' AND column_name IN ('In','MediaTimemapBA','Sm2TiTrack_id','MediaFilePath')",
  );
  const have = new Set(rows.map((r) => r.column_name));
  for (const need of ['In', 'MediaTimemapBA', 'Sm2TiTrack_id', 'MediaFilePath']) {
    if (!have.has(need)) throw new Error(`Sm2TiItem.${need} not found — unsupported Postgres schema; refusing to patch.`);
  }
}
async function pgLocate(client, { timelineId, timelineName, mediaPathContains }) {
  const where = timelineId ? 'tl."Sm2Timeline_id" = $1' : 'tl."Name" = $1';
  const { rows } = await client.query(
    `SELECT i."Sm2TiItem_id" AS id, i."In" AS inv, i."Start"::text AS start, LENGTH(i."MediaTimemapBA") AS tmlen, i."MediaFilePath" AS path
 FROM "Sm2TiItem" i
 JOIN "Sm2TiTrack" tr ON i."Sm2TiTrack_id" = tr."Sm2TiTrack_id"
 JOIN "Sm2Timeline" tl ON tr."Sequence" = tl."Sequence"
 WHERE ${where} AND i."MediaFilePath" LIKE $2`,
    [timelineId || timelineName, `%${mediaPathContains}%`],
  );
  return rows;
}
async function pgBlobSource(client, { mediaPathContains, minBlobLen }) {
  const { rows } = await client.query(
    `SELECT "Sm2TiItem_id" AS id, LENGTH("MediaTimemapBA") AS tmlen FROM "Sm2TiItem"
 WHERE "MediaFilePath" LIKE $1 AND LENGTH("MediaTimemapBA") >= $2 ORDER BY tmlen DESC LIMIT 1`,
    [`%${mediaPathContains}%`, minBlobLen],
  );
  return rows[0] || null;
}

// ---- public dispatchers ----
function isPg(opts) {
  return !!opts.postgres;
}
const DEFAULT_MIN_BLOB = 100; // default no-retime timemap is ~9 bytes; reverse curve is hundreds

/** Locate reversed-clip candidates (timeline-scoped) + a generic reverse-blob source. Read-only. */
export async function locateReverseClip(opts = {}) {
  if (!opts.mediaPathContains) throw new Error('provide mediaPathContains (e.g. a source-name fragment)');
  const minBlob = opts.minBlobLen || DEFAULT_MIN_BLOB;
  if (isPg(opts)) {
    const client = await pgConnect(opts.postgres);
    try {
      await pgGuard(client);
      const candidates = await pgLocate(client, opts);
      const blobSource = await pgBlobSource(client, { mediaPathContains: opts.mediaPathContains, minBlobLen: minBlob });
      return { backend: 'postgres', candidates, blobSource };
    } finally {
      await pgEnd(client, opts.postgres);
    }
  }
  const dbPath = sqliteDbPath(opts);
  const db = openSqlite(dbPath, false);
  try {
    return {
      backend: 'sqlite',
      projectDb: dbPath,
      candidates: sqliteLocate(db, opts),
      blobSource: sqliteBlobSource(db, { mediaPathContains: opts.mediaPathContains, minBlobLen: minBlob }) || null,
    };
  } finally {
    db.close();
  }
}

/**
 * Write the fix to one reversed Sm2TiItem (project must be CLOSED):
 * - back up the row (In + MediaTimemapBA hex) to a temp file
 * - optionally copy MediaTimemapBA from `restoreBlobFromItemId` (restore reverse)
 * - set "In" = `setIn`
 * Returns { backup, before, after }. Caller reopens + reads get_source_start to verify.
 */
export async function writeReverseClip(opts = {}) {
  if (!opts.iConfirmProjectClosed) {
    throw new Error('Refusing to write: close the project in Resolve first (it oversaves on save), then pass iConfirmProjectClosed: true.');
  }
  if (!opts.itemId) throw new Error('provide itemId (from locateReverseClip)');
  if (opts.setIn == null) throw new Error('provide setIn (the "In" value to write)');
  const setIn = String(opts.setIn);
  if (isPg(opts)) {
    const client = await pgConnect(opts.postgres);
    try {
      await pgGuard(client);
      const before = (await client.query('SELECT "In" AS inv, LENGTH("MediaTimemapBA") AS tmlen FROM "Sm2TiItem" WHERE "Sm2TiItem_id"=$1', [opts.itemId]))
        .rows[0];
      if (!before) throw new Error(`no Sm2TiItem with id ${opts.itemId}`);
      const backup = pgBackupRow(opts.postgres, client, opts.itemId);
      const bak = await backup;
      if (opts.restoreBlobFromItemId) {
        await client.query(
          'UPDATE "Sm2TiItem" t SET "MediaTimemapBA"=s."MediaTimemapBA" FROM "Sm2TiItem" s WHERE t."Sm2TiItem_id"=$1 AND s."Sm2TiItem_id"=$2',
          [opts.itemId, opts.restoreBlobFromItemId],
        );
      }
      await client.query('UPDATE "Sm2TiItem" SET "In"=$1 WHERE "Sm2TiItem_id"=$2', [setIn, opts.itemId]);
      const after = (await client.query('SELECT "In" AS inv, LENGTH("MediaTimemapBA") AS tmlen FROM "Sm2TiItem" WHERE "Sm2TiItem_id"=$1', [opts.itemId]))
        .rows[0];
      return { backend: 'postgres', backup: bak, before, after };
    } finally {
      await pgEnd(client, opts.postgres);
    }
  }
  const dbPath = sqliteDbPath(opts);
  const db = openSqlite(dbPath, true);
  try {
    const before = db.prepare('SELECT "In" AS inv, LENGTH("MediaTimemapBA") AS tmlen FROM "Sm2TiItem" WHERE "Sm2TiItem_id"=?').get(opts.itemId);
    if (!before) throw new Error(`no Sm2TiItem with id ${opts.itemId}`);
    const bak = sqliteBackupRow(db, dbPath, opts.itemId);
    if (opts.restoreBlobFromItemId) {
      db.prepare('UPDATE "Sm2TiItem" SET "MediaTimemapBA"=(SELECT "MediaTimemapBA" FROM "Sm2TiItem" WHERE "Sm2TiItem_id"=?) WHERE "Sm2TiItem_id"=?').run(
        opts.restoreBlobFromItemId,
        opts.itemId,
      );
    }
    db.prepare('UPDATE "Sm2TiItem" SET "In"=? WHERE "Sm2TiItem_id"=?').run(setIn, opts.itemId);
    const after = db.prepare('SELECT "In" AS inv, LENGTH("MediaTimemapBA") AS tmlen FROM "Sm2TiItem" WHERE "Sm2TiItem_id"=?').get(opts.itemId);
    return { backend: 'sqlite', projectDb: dbPath, backup: bak, before, after };
  } finally {
    db.close();
  }
}

/** displayed = K - In ⟹ K = probeIn + displayed (calibrate from one readback). */
export function calibrateK(probeIn, displayedAtProbe) {
  return Number(probeIn) + Number(displayedAtProbe);
}
/** In to write so the reversed clip displays `targetFrame`. */
export function inForTarget(K, targetFrame) {
  return K - targetFrame;
}

// ---- helpers ----
function sqliteDbPath(opts) {
  if (opts.projectDb) return opts.projectDb;
  throw new Error('provide projectDb (path) for the SQLite backend, or a postgres connection object');
}
function sqliteBackupRow(db, dbPath, itemId) {
  const row = db.prepare('SELECT "In" AS inv, "MediaTimemapBA" AS blob FROM "Sm2TiItem" WHERE "Sm2TiItem_id"=?').get(itemId);
  const hex = row && row.blob ? Buffer.from(row.blob).toString('hex') : '';
  const out = path.join(os.tmpdir(), `reverse-clip-backup-${itemId}.txt`);
  fs.writeFileSync(out, `${row ? row.inv : ''}~~${hex}`);
  return out;
}
async function pgBackupRow(pg, client, itemId) {
  const { rows } = await client.query('SELECT "In" AS inv, COALESCE(encode("MediaTimemapBA",\'hex\'),\'\') AS hex FROM "Sm2TiItem" WHERE "Sm2TiItem_id"=$1', [
    itemId,
  ]);
  const r = rows[0] || { inv: '', hex: '' };
  const out = path.join(os.tmpdir(), `reverse-clip-backup-${itemId}.txt`);
  fs.writeFileSync(out, `${r.inv}~~${r.hex}`);
  return out;
}
