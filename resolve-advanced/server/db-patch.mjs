/**
 * Shared safety framework for LIVE Project.db patches — the "beyond-the-API" tier.
 *
 * ⚠️ Unsanctioned territory (Blackmagic doesn't support direct DB edits). Every write
 * goes through: project-CLOSED gate → auto-backup → schema-version guard → read-back
 * verify. The schema map is Resolve 21 / ProjectVersion 17 (the design notes design notes);
 * the column guard refuses rather than corrupting if the schema differs.
 *
 * Needs the optional native dep `better-sqlite3` (lazy).
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

export const DISK_DB_ROOT = path.join(os.homedir(), 'Library/Application Support/Blackmagic Design/DaVinci Resolve/Resolve Disk Database/Resolve Projects');

export function loadSqlite() {
  try {
    return require('better-sqlite3');
  } catch {
    throw new Error("Project.db patching needs the optional native dep 'better-sqlite3'. Install: npm i better-sqlite3");
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
      if (!e.isDirectory()) continue;
      const full = path.join(dir, e.name);
      if (e.name === projectName && fs.existsSync(path.join(full, 'Project.db'))) hits.push(path.join(full, 'Project.db'));
      walk(full, depth + 1);
    }
  };
  if (fs.existsSync(root)) walk(root, 0);
  return hits;
}

export function resolveDbPath({ projectDb, projectName }) {
  if (projectDb) return projectDb;
  if (!projectName) throw new Error('provide projectDb (path) or projectName');
  const hits = findProjectDb(projectName);
  if (!hits.length) throw new Error(`no Project.db found for project "${projectName}" under the Resolve Disk Database`);
  if (hits.length > 1) throw new Error(`multiple Project.db match "${projectName}": pass projectDb explicitly`);
  return hits[0];
}

/** Open a Project.db, refusing if a required (table, column) guard is absent (version safety). */
export function openGuarded(dbPath, { writable = false, table, column } = {}) {
  const Database = loadSqlite();
  if (!fs.existsSync(dbPath)) throw new Error(`Project.db not found: ${dbPath}`);
  const db = new Database(dbPath, { readonly: !writable });
  if (table && column) {
    // Quote the table identifier — Resolve tables like "ListMgt::LmVersion" contain "::" which is an
    // illegal token unquoted (the PRAGMA would fail with "unrecognized token: :").
    const cols = db
      .prepare(`PRAGMA table_info("${String(table).replace(/"/g, '""')}")`)
      .all()
      .map((c) => c.name);
    if (!cols.includes(column)) {
      db.close();
      throw new Error(`${table}.${column} not found — unsupported Project.db schema/version; refusing to patch.`);
    }
  }
  return db;
}

export function backup(dbPath) {
  const bak = `${dbPath}.bak`;
  fs.copyFileSync(dbPath, bak);
  return bak;
}

/** Gate every write: the project must be closed (Resolve oversaves an open project). */
export function requireClosed(opts) {
  if (!opts.iConfirmProjectClosed) {
    throw new Error('Refusing to write: close the project in Resolve first (it oversaves on save), then pass iConfirmProjectClosed: true.');
  }
}
