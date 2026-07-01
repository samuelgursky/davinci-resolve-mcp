/**
 * Canonical project DB (A1) — DB-as-truth for the pipeline.
 *
 * SQLite (same tech as the lineage / offline-ref / reverse-clip stores). Holds the
 * RESOLVED entity tree (intent), pipeline run history, provenance, decoded facts
 * (readback `actual`), and intent↔actual drift. YAML compiles INTO this (see
 * spec-compile.mjs); the runner reads resolved rows out (see runner.mjs); readback
 * writes `actual` back (see readback.mjs). The canonical DB wins; divergence is drift,
 * never silently lost.
 *
 * No Date.now() in this runtime — callers pass `now` (ISO string).
 */
import crypto from 'node:crypto';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
function loadSqlite() {
  try {
    return require('better-sqlite3');
  } catch {
    throw new Error("project DB needs the optional native dep 'better-sqlite3'. Install: npm i better-sqlite3");
  }
}

export const ENTITY_KINDS = ['type', 'series', 'episode', 'sequence', 'group', 'deliverable'];
const sha1 = (s) => crypto.createHash('sha1').update(s).digest('hex');
export const hashConfig = (obj) => sha1(JSON.stringify(obj ?? null));

const SCHEMA = `
CREATE TABLE IF NOT EXISTS entities (slug TEXT PRIMARY KEY, kind TEXT NOT NULL, parent_slug TEXT, resolve_ref TEXT,
 raw_json TEXT, resolved_json TEXT, content_hash TEXT, created_at TEXT);
CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities(kind);
CREATE INDEX IF NOT EXISTS idx_entities_parent ON entities(parent_slug);

CREATE TABLE IF NOT EXISTS pipeline_runs (run_id TEXT PRIMARY KEY, episode_slug TEXT NOT NULL, profile TEXT, status TEXT,
 spec_hash TEXT, created_at TEXT, updated_at TEXT);
CREATE INDEX IF NOT EXISTS idx_runs_episode ON pipeline_runs(episode_slug);

CREATE TABLE IF NOT EXISTS run_stages (run_id TEXT, stage_index INTEGER, stage TEXT, gate TEXT, status TEXT,
 tool TEXT, config_hash TEXT, result_json TEXT, ran_at TEXT,
 PRIMARY KEY (run_id, stage_index));

CREATE TABLE IF NOT EXISTS provenance_events (event_id TEXT PRIMARY KEY, run_id TEXT, episode_slug TEXT, stage TEXT, tool TEXT,
 config_hash TEXT, actor TEXT, result TEXT, target TEXT, at TEXT);
CREATE INDEX IF NOT EXISTS idx_prov_episode ON provenance_events(episode_slug);
CREATE INDEX IF NOT EXISTS idx_prov_run ON provenance_events(run_id);

CREATE TABLE IF NOT EXISTS decoded_facts (entity_slug TEXT, key TEXT, kind TEXT, value_json TEXT, source TEXT, at TEXT,
 PRIMARY KEY (entity_slug, key));

CREATE TABLE IF NOT EXISTS drift (entity_slug TEXT, field TEXT, intent_json TEXT, actual_json TEXT, status TEXT, detected_at TEXT,
 PRIMARY KEY (entity_slug, field));

`;

export function openProjectDb(dbPath) {
  const Database = loadSqlite();
  const db = new Database(dbPath);
  db.pragma('journal_mode = WAL');
  db.exec(SCHEMA);
  return db;
}

// ── entities ─────────────────────────────────────────────────────────────────
/** Upsert a resolved entity. `resolved` = inheritance-merged config; `raw` = authored. */
export function upsertEntity(db, { slug, kind, parentSlug = null, resolveRef = null, raw = null, resolved = null, now = null }) {
  if (!slug) throw new Error('entity slug required');
  if (!ENTITY_KINDS.includes(kind)) throw new Error(`unknown entity kind '${kind}' (${ENTITY_KINDS.join('|')})`);
  const content_hash = hashConfig(resolved ?? raw);
  db.prepare(
    `INSERT INTO entities (slug, kind, parent_slug, resolve_ref, raw_json, resolved_json, content_hash, created_at)
 VALUES (@slug,@kind,@parent_slug,@resolve_ref,@raw_json,@resolved_json,@content_hash,@created_at)
 ON CONFLICT(slug) DO UPDATE SET kind=@kind, parent_slug=@parent_slug, resolve_ref=@resolve_ref,
 raw_json=@raw_json, resolved_json=@resolved_json, content_hash=@content_hash`,
  ).run({
    slug,
    kind,
    parent_slug: parentSlug,
    resolve_ref: resolveRef,
    raw_json: raw == null ? null : JSON.stringify(raw),
    resolved_json: resolved == null ? null : JSON.stringify(resolved),
    content_hash,
    created_at: now,
  });
  return { slug, content_hash };
}

const hydrate = (row) =>
  row && { ...row, raw: row.raw_json ? JSON.parse(row.raw_json) : null, resolved: row.resolved_json ? JSON.parse(row.resolved_json) : null };

export function getEntity(db, slug) {
  return hydrate(db.prepare('SELECT * FROM entities WHERE slug = ?').get(slug)) || null;
}

export function listEntities(db, { kind, parentSlug } = {}) {
  let sql = 'SELECT * FROM entities',
    where = [],
    params = [];
  if (kind) {
    where.push('kind = ?');
    params.push(kind);
  }
  if (parentSlug !== undefined) {
    where.push('parent_slug IS ?');
    params.push(parentSlug);
  }
  if (where.length) sql += ' WHERE ' + where.join(' AND ');
  sql += ' ORDER BY kind, slug';
  return db
    .prepare(sql)
    .all(...params)
    .map(hydrate);
}

/** Walk parent_slug from an entity up to its root (self → … → type). */
export function ancestry(db, slug) {
  const chain = [];
  let cur = getEntity(db, slug);
  const seen = new Set();
  while (cur && !seen.has(cur.slug)) {
    seen.add(cur.slug);
    chain.push(cur);
    cur = cur.parent_slug ? getEntity(db, cur.parent_slug) : null;
  }
  return chain; // [self, parent, …, root]
}

// ── runs ─────────────────────────────────────────────────────────────────────
export function createRun(db, { episodeSlug, profile = null, specHash = null, now = null }) {
  const run_id = sha1(`${episodeSlug}:${profile ?? ''}:${specHash ?? ''}:${now ?? ''}`).slice(0, 20);
  db.prepare(
    `INSERT OR REPLACE INTO pipeline_runs (run_id, episode_slug, profile, status, spec_hash, created_at, updated_at)
 VALUES (?,?,?,?,?,?,?)`,
  ).run(run_id, episodeSlug, profile, 'planned', specHash, now, now);
  return run_id;
}

export function setRunStatus(db, runId, status, now = null) {
  db.prepare('UPDATE pipeline_runs SET status = ?, updated_at = ? WHERE run_id = ?').run(status, now, runId);
}

export function upsertRunStage(db, { runId, stageIndex, stage, gate = null, status, tool = null, config = null, result = null, now = null }) {
  db.prepare(
    `INSERT INTO run_stages (run_id, stage_index, stage, gate, status, tool, config_hash, result_json, ran_at)
 VALUES (@run_id,@stage_index,@stage,@gate,@status,@tool,@config_hash,@result_json,@ran_at)
 ON CONFLICT(run_id, stage_index) DO UPDATE SET stage=@stage, gate=@gate, status=@status, tool=@tool,
 config_hash=@config_hash, result_json=@result_json, ran_at=@ran_at`,
  ).run({
    run_id: runId,
    stage_index: stageIndex,
    stage,
    gate,
    status,
    tool,
    config_hash: config == null ? null : hashConfig(config),
    result_json: result == null ? null : JSON.stringify(result),
    ran_at: now,
  });
}

export function getRun(db, runId) {
  const run = db.prepare('SELECT * FROM pipeline_runs WHERE run_id = ?').get(runId);
  if (!run) return null;
  const stages = db
    .prepare('SELECT * FROM run_stages WHERE run_id = ? ORDER BY stage_index')
    .all(runId)
    .map((s) => ({ ...s, result: s.result_json ? JSON.parse(s.result_json) : null }));
  return { ...run, stages };
}

export function listRuns(db, episodeSlug) {
  return db.prepare('SELECT * FROM pipeline_runs WHERE episode_slug = ? ORDER BY created_at DESC').all(episodeSlug);
}

// ── provenance ───────────────────────────────────────────────────────────────
export function recordProvenance(db, { runId = null, episodeSlug, stage, tool, config = null, actor = 'system', result = null, target = null, now = null }) {
  const event_id = sha1(`${runId ?? ''}:${episodeSlug}:${stage}:${tool}:${target ?? ''}:${now ?? ''}:${Math.random()}`).slice(0, 24);
  db.prepare(
    `INSERT INTO provenance_events (event_id, run_id, episode_slug, stage, tool, config_hash, actor, result, target, at)
 VALUES (?,?,?,?,?,?,?,?,?,?)`,
  ).run(event_id, runId, episodeSlug, stage, tool, config == null ? null : hashConfig(config), actor, result, target, now);
  return event_id;
}

export function listProvenance(db, { episodeSlug, runId } = {}) {
  if (runId) return db.prepare('SELECT * FROM provenance_events WHERE run_id = ? ORDER BY at').all(runId);
  return db.prepare('SELECT * FROM provenance_events WHERE episode_slug = ? ORDER BY at').all(episodeSlug);
}

// ── decoded facts (readback `actual`) ─────────────────────────────────────────
export function recordFact(db, { entitySlug, key, kind = null, value, source = null, now = null }) {
  db.prepare(
    `INSERT INTO decoded_facts (entity_slug, key, kind, value_json, source, at)
 VALUES (@entity_slug,@key,@kind,@value_json,@source,@at)
 ON CONFLICT(entity_slug, key) DO UPDATE SET kind=@kind, value_json=@value_json, source=@source, at=@at`,
  ).run({ entity_slug: entitySlug, key, kind, value_json: JSON.stringify(value ?? null), source, at: now });
}

export function getFacts(db, entitySlug) {
  return db
    .prepare('SELECT * FROM decoded_facts WHERE entity_slug = ? ORDER BY key')
    .all(entitySlug)
    .map((f) => ({ ...f, value: f.value_json ? JSON.parse(f.value_json) : null }));
}

// ── drift ────────────────────────────────────────────────────────────────────
export function recordDrift(db, { entitySlug, field, intent, actual, status = 'open', now = null }) {
  db.prepare(
    `INSERT INTO drift (entity_slug, field, intent_json, actual_json, status, detected_at)
 VALUES (@entity_slug,@field,@intent_json,@actual_json,@status,@detected_at)
 ON CONFLICT(entity_slug, field) DO UPDATE SET intent_json=@intent_json, actual_json=@actual_json, status=@status, detected_at=@detected_at`,
  ).run({ entity_slug: entitySlug, field, intent_json: JSON.stringify(intent ?? null), actual_json: JSON.stringify(actual ?? null), status, detected_at: now });
}

export function listDrift(db, { entitySlug, status } = {}) {
  let sql = 'SELECT * FROM drift',
    where = [],
    params = [];
  if (entitySlug) {
    where.push('entity_slug = ?');
    params.push(entitySlug);
  }
  if (status) {
    where.push('status = ?');
    params.push(status);
  }
  if (where.length) sql += ' WHERE ' + where.join(' AND ');
  return db
    .prepare(sql)
    .all(...params)
    .map((d) => ({ ...d, intent: JSON.parse(d.intent_json), actual: JSON.parse(d.actual_json) }));
}

