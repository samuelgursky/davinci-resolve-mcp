/**
 * Shared safety framework for LIVE Project.db patches — the "beyond-the-API" tier.
 *
 * ⚠️ Unsanctioned territory (Blackmagic doesn't support direct DB edits). Every write
 * goes through: project-CLOSED gate → auto-backup → schema-version guard → read-back
 * verify. The schema map is Resolve 21 / ProjectVersion 17 (the design notes design notes);
 * the column guard refuses rather than corrupting if the schema differs.
 *
 * Uses optional better-sqlite3 or node:sqlite (lazy, compatible adapter).
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import childProcess from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
import { requireBetterSqlite3 } from './capabilities.mjs';

export const DISK_DB_ROOT = path.join(os.homedir(), 'Library/Application Support/Blackmagic Design/DaVinci Resolve/Resolve Disk Database/Resolve Projects');

/**
 * The other Studio layout. A stock modern Studio install on macOS keeps its
 * local library under "Resolve Project Library", not "Resolve Disk Database"
 * (issue #169, confirmed on Studio 21.0.4.5: every local project sits at
 * Resolve Project Library/Resolve Projects/Users/<dbuser>/Projects/<name>/).
 * The recursive walk already spans the Users/<dbuser>/Projects segment, so
 * listing the root is all that is needed. Which root exists depends on how
 * and when the library was created — search both, dedupe, never guess.
 */
export const PROJECT_LIBRARY_ROOT = path.join(os.homedir(), 'Library/Application Support/Blackmagic Design/DaVinci Resolve/Resolve Project Library/Resolve Projects');

/**
 * The FREE edition ships from the App Store and runs SANDBOXED, so its project
 * library is not under Application Support at all — it lives inside the app's
 * container, under a differently-named root ("Resolve Project Library", not
 * "Resolve Disk Database"). Confirmed on free 21.0.3.7, macOS.
 *
 * Without this, `project_db` resolved by projectName could never find a
 * free-edition project: it searched only the Studio root and reported "no
 * Project.db found", sending exactly the users the in-app bridge exists to serve
 * hunting for a path they have no reason to know.
 *
 * macOS-only: the sandbox container is an Apple construct. Windows/Linux
 * use the platform roots returned by projectLibraryRoots below.
 */
export const LITE_DB_ROOT = path.join(
  os.homedir(),
  'Library/Containers/com.blackmagic-design.DaVinciResolveLite/Data/Library/Application Support/Resolve Project Library/Resolve Projects',
);

/** Every root searched when resolving a project by name, Studio first. */
export function projectLibraryRoots(platform = process.platform, home = os.homedir(), env = process.env) {
  const join = platform === 'win32' ? path.win32.join : path.posix.join;
  const libraries = (base) => ['Resolve Project Library', 'Resolve Disk Database']
    .map((name) => join(base, name, 'Resolve Projects'));
  if (platform === 'win32') return libraries(join(env.APPDATA || join(home, 'AppData', 'Roaming'),
    'Blackmagic Design', 'DaVinci Resolve', 'Support'));
  if (platform === 'linux') return libraries(join(home, '.local', 'share', 'DaVinciResolve'));
  return [DISK_DB_ROOT, PROJECT_LIBRARY_ROOT, LITE_DB_ROOT];
}
export const DB_ROOTS = projectLibraryRoots();

/**
 * Filter roots to the ones that answer a readdir within `deadlineMs`.
 *
 * macOS can render a path UNRESPONSIVE at the filesystem level — measured
 * live 2026-08-30: `ls` on the Lite sandbox container hung indefinitely
 * (File-Provider/container materialization), which made every projectName
 * lookup and the test suite hang with it. A hung readdir cannot be
 * cancelled; the race abandons it (one leaked threadpool op) and reports the
 * root as skipped so the caller can say WHERE it could not look.
 * Returns { roots, skipped: [{root, reason}] }.
 */
export async function responsiveRoots(roots = DB_ROOTS, deadlineMs = 3000) {
  const fsp = require('node:fs/promises');
  const results = await Promise.all(
    roots.map(async (root) => {
      try {
        const answer = fsp
          .readdir(root)
          .then(() => 'ok', (err) => (err && err.code === 'ENOENT' ? 'absent' : 'error'));
        const timer = new Promise((resolve) => {
          const t = setTimeout(() => resolve('timeout'), deadlineMs);
          if (t.unref) t.unref();
        });
        const outcome = await Promise.race([answer, timer]);
        return { root, outcome };
      } catch {
        return { root, outcome: 'error' };
      }
    }),
  );
  return {
    roots: results.filter((r) => r.outcome === 'ok' || r.outcome === 'absent').map((r) => r.root),
    skipped: results
      .filter((r) => r.outcome === 'timeout')
      .map((r) => ({ root: r.root, reason: `unresponsive after ${deadlineMs}ms (hung filesystem path — skipped)` })),
  };
}

export function loadSqlite() {
  // A successful require alone doesn't detect a native ABI mismatch: the
  // bindings are loaded by the constructor. Probe before selecting a backend.
  try {
    const Database = requireBetterSqlite3('Project.db patching');
    const probe = new Database(':memory:');
    probe.close();
    return Database;
  } catch (nativeError) {
    try { require('node:sqlite'); } catch {
      throw new Error(`${nativeError.message} Alternatively use Node with node:sqlite (22.13+).`);
    }
    return BuiltinSqlite;
  }
}

// Small better-sqlite3-compatible surface used by Project.db consumers. Keep
// rows as ordinary objects and blobs as Buffers on either backend.
export class BuiltinSqlite {
  constructor(filename, { readonly = false } = {}) {
    const { DatabaseSync } = require('node:sqlite');
    this.db = new DatabaseSync(filename, { readOnly: readonly, enableForeignKeyConstraints: false });
  }
  exec(sql) { this.db.exec(sql); return this; }
  close() { this.db.close(); }
  prepare(sql) {
    const stmt = this.db.prepare(sql);
    const row = (r) => r && Object.fromEntries(Object.entries(r)
      .map(([k, v]) => [k, v instanceof Uint8Array ? Buffer.from(v) : v]));
    return { get: (...args) => row(stmt.get(...args)),
      all: (...args) => stmt.all(...args).map(row), run: (...args) => stmt.run(...args) };
  }
  transaction(fn) {
    return (...args) => {
      this.exec('BEGIN IMMEDIATE');
      try { const result = fn(...args); this.exec('COMMIT'); return result; }
      catch (error) { this.exec('ROLLBACK'); throw error; }
    };
  }
  backup(filename) { return require('node:sqlite').backup(this.db, filename); }
}

/** Verify the process is gone; a caller assertion alone is not sufficient. */
export function requireResolveQuit(opts) {
  requireClosed(opts);
  if (resolveRunning()) throw new Error('Fully QUIT Resolve before subtitle database writes (Resolve is running).');
}

function resolveRunning() {
  const win = process.platform === 'win32';
  const result = childProcess.spawnSync(win ? 'tasklist.exe' : 'ps',
    win ? ['/FO', 'CSV', '/NH'] : ['-A', '-o', 'comm='],
    { encoding: 'utf8', timeout: 5000, windowsHide: true });
  if (result.error || result.status !== 0) throw new Error('Cannot verify Resolve is quit; refusing database write.');
  return result.stdout.split(/\r?\n/).some((line) => win
    ? /^"Resolve\.exe",/i.test(line.trim())
    : /(^|\/)resolve(?:\.exe)?$/i.test(line.trim()));
}

// Asks the running Resolve which project is loaded. Same module/DLL bootstrap
// as src/server.py; RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB override defaults.
const LOADED_PROJECT_PY = String.raw`
import json, os, sys
api = os.environ.get('RESOLVE_SCRIPT_API') or {
    'win32': os.path.join(os.environ.get('PROGRAMDATA', ''), 'Blackmagic Design', 'DaVinci Resolve', 'Support', 'Developer', 'Scripting'),
    'darwin': '/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting',
}.get(sys.platform, '/opt/resolve/Developer/Scripting')
lib = os.environ.get('RESOLVE_SCRIPT_LIB') or {
    'win32': os.path.join(os.environ.get('PROGRAMFILES', r'C:\Program Files'), 'Blackmagic Design', 'DaVinci Resolve', 'fusionscript.dll'),
    'darwin': '/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so',
}.get(sys.platform, '/opt/resolve/libs/Fusion/fusionscript.so')
os.environ.setdefault('RESOLVE_SCRIPT_LIB', lib)
sys.path.append(os.path.join(api, 'Modules'))
if sys.platform == 'win32' and os.path.isdir(os.path.dirname(lib)):
    os.environ.setdefault('PYTHONHOME', sys.base_prefix)
    os.environ['PATH'] = os.path.dirname(lib) + os.pathsep + os.environ.get('PATH', '')
    os.add_dll_directory(os.path.dirname(lib))
import DaVinciResolveScript as dvr
resolve = dvr.scriptapp('Resolve')
project = resolve and resolve.GetProjectManager().GetCurrentProject()
if not project: sys.exit(3)
print(json.dumps({'project': project.GetName()}))
`;

/** Python used for the probe: RESOLVE_PYTHON, else the repo venv, else PATH. */
function resolvePython() {
  if (process.env.RESOLVE_PYTHON) return process.env.RESOLVE_PYTHON;
  const venv = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'venv',
    process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  return fs.existsSync(venv) ? venv : (process.platform === 'win32' ? 'python' : 'python3');
}

/** Name of the project loaded in the running Resolve; throws when scripting cannot say. */
export function loadedResolveProject() {
  const result = childProcess.spawnSync(resolvePython(), ['-c', LOADED_PROJECT_PY],
    { encoding: 'utf8', timeout: 20000, windowsHide: true, env: { ...process.env, PYTHONUTF8: '1' } });
  if (result.error || result.status !== 0) {
    throw new Error('Resolve is running but its loaded project cannot be read through scripting; refusing database write. Quit Resolve instead.');
  }
  try { return JSON.parse(result.stdout.trim().split(/\r?\n/).pop()).project; }
  catch { throw new Error('Unreadable answer from Resolve scripting; refusing database write.'); }
}

/**
 * Opt-in relaxation of requireResolveQuit. Resolve only oversaves the project it
 * has loaded, so with allowWhileRunningIfNotLoaded:true a running Resolve is
 * accepted when scripting reports a DIFFERENT loaded project than the folder
 * owning dbPath. Fails closed when the loaded project cannot be read.
 * Returns the loaded project name, or null when Resolve is quit.
 */
export function requireNotLoaded(opts, dbPath) {
  requireClosed(opts);
  if (!resolveRunning()) return null;
  if (!opts.allowWhileRunningIfNotLoaded) {
    throw new Error('Fully QUIT Resolve before subtitle database writes (Resolve is running). ' +
      'To write a project that is NOT loaded in Resolve, pass allowWhileRunningIfNotLoaded:true.');
  }
  const loaded = loadedResolveProject(), target = path.basename(path.dirname(dbPath));
  if (!loaded || loaded.toLowerCase() === target.toLowerCase()) {
    throw new Error(`Project "${target}" is loaded in Resolve; load another project (or quit Resolve) before writing it.`);
  }
  return loaded;
}

/** SQLite snapshot includes committed WAL pages; never overwrite an older backup. */
export async function snapshotBackup(dbPath) {
  const filename = `${dbPath}.subtitle-${Date.now()}-${randomUUID()}.bak`;
  const db = openGuarded(dbPath);
  try { await db.backup(filename); } finally { db.close(); }
  return filename;
}

/**
 * Recursively locate <projectName>/Project.db under a project-library root.
 * Called once per root by resolveDbPath; pass `root` to search just one.
 */
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

export function resolveDbPath({ projectDb, projectName, roots, skippedRoots = [] }) {
  if (projectDb) return projectDb;
  if (!projectName) throw new Error('provide projectDb (path) or projectName');
  const searchRoots = roots || DB_ROOTS;
  // Deduplicate: a project present under both roots must not read as ambiguous
  // just because the same file was found twice.
  const hits = [...new Set(searchRoots.flatMap((root) => findProjectDb(projectName, root)))];
  if (!hits.length) {
    throw new Error(
      `no Project.db found for project "${projectName}". Searched: ` +
      `${searchRoots.join(', ')}. ` +
      (skippedRoots.length
        ? `SKIPPED unresponsive root(s): ${skippedRoots.map((r) => r.root).join(', ')} — ` +
          'a hung filesystem path (File Provider / sandbox container); its projects ' +
          'are invisible until macOS unwedges it. '
        : '') +
      'If Resolve keeps its projects elsewhere — a relocated library, a network/Postgres ' +
      'database — pass projectDb with the full local SQLite path (Postgres is not a Project.db file).',
    );
  }
  if (hits.length > 1) {
    throw new Error(
      `multiple Project.db match "${projectName}" (${hits.join(', ')}): pass projectDb explicitly`,
    );
  }
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
