/**
 * Readback loop (A3) — pull Resolve `actual` state up into the canonical DB and detect
 * drift vs intent. Formalizes the write we already do by hand (Route A look decode, clip
 * counts, render hashes): record as decoded_facts, then compare push-fields (intent →
 * Resolve) against the recorded actual and flag divergence as DRIFT. Design,,.
 *
 * No Resolve calls here — callers feed already-read values (group-grade-read output,
 * clip counts, render results). This module is the deterministic record+compare core.
 */
import { recordFact, getFacts, getEntity, recordDrift, listDrift } from './project-db.mjs';

/** obj.a.b.c via 'a.b.c'. */
export function getByPath(obj, dotPath) {
  return String(dotPath)
    .split('.')
    .reduce((o, k) => (o == null ? undefined : o[k]), obj);
}
const eq = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

/**
 * Record a batch of actual facts for an entity. facts = { key: value,... }.
 * @returns {string[]} keys written
 */
export function recordReadback(db, entitySlug, facts, { source = null, kindByKey = {}, now = null } = {}) {
  if (!getEntity(db, entitySlug)) throw new Error(`readback: unknown entity '${entitySlug}'`);
  const keys = [];
  for (const [key, value] of Object.entries(facts || {})) {
    recordFact(db, { entitySlug, key, kind: kindByKey[key] ?? null, value, source, now });
    keys.push(key);
  }
  return keys;
}

/**
 * Compare push-fields against recorded actual facts and write drift rows.
 * @param {Array<{field:string, factKey?:string}>} fields — intent path in resolved config,
 * and the fact key holding actual (defaults to the same string).
 * @returns {{drift:Array, matched:string[]}}
 */
export function detectDrift(db, entitySlug, fields, { now = null } = {}) {
  const entity = getEntity(db, entitySlug);
  if (!entity) throw new Error(`detectDrift: unknown entity '${entitySlug}'`);
  const factMap = new Map(getFacts(db, entitySlug).map((f) => [f.key, f.value]));
  const drift = [],
    matched = [];
  for (const f of fields) {
    const factKey = f.factKey ?? f.field;
    const intent = getByPath(entity.resolved, f.field);
    if (intent === undefined) continue; // nothing authored to enforce
    if (!factMap.has(factKey)) continue; // not read back yet
    const actual = factMap.get(factKey);
    if (eq(intent, actual)) {
      recordDrift(db, { entitySlug, field: f.field, intent, actual, status: 'resolved', now });
      matched.push(f.field);
    } else {
      recordDrift(db, { entitySlug, field: f.field, intent, actual, status: 'open', now });
      drift.push({ field: f.field, intent, actual });
    }
  }
  return { drift, matched };
}

/**
 * One-shot reconcile: record actual facts, then detect drift on the given push-fields.
 * @returns {{written:string[], drift:Array, matched:string[]}}
 */
export function reconcile(db, entitySlug, { facts, pushFields = [], source = null, now = null }) {
  const written = recordReadback(db, entitySlug, facts, { source, now });
  const { drift, matched } = detectDrift(db, entitySlug, pushFields, { now });
  return { written, drift, matched };
}

/** Open-drift summary across the DB (or one entity) — the "what diverged" worklist. */
export function driftReport(db, entitySlug) {
  const open = listDrift(db, { entitySlug, status: 'open' });
  return { openCount: open.length, drift: open };
}
