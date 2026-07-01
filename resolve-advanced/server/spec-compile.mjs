/**
 * YAML → DB compile (A2).
 *
 * Takes authored entity specs (parsed objects — YAML-agnostic core; loadYamlDir does the
 * file edge), resolves the 4-layer inheritance (type → series → episode → deliverable),
 * validates, and writes FULLY-RESOLVED config into the canonical DB. The runner then never
 * merges at runtime — it reads resolved rows.
 *
 * Merge semantics: scalars override; maps deep-merge; lists REPLACE by default, or
 * APPEND via a `+key` sibling; deliverables may also `inherits: <sibling-slug>`.
 * Validation asserts the typed/required configs that previously failed SILENTLY.
 */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { upsertEntity, ENTITY_KINDS } from './project-db.mjs';

const require = createRequire(import.meta.url);
function loadYaml() {
  try {
    return require('js-yaml');
  } catch {
    throw new Error("spec compile (YAML loading) needs the optional dep 'js-yaml'. Install: npm i js-yaml");
  }
}

const isObj = (v) => v && typeof v === 'object' && !Array.isArray(v);

/**
 * Deep-merge `override` onto `base`. Maps deep-merge; scalars/arrays replace; a key
 * `+foo` in override APPENDS its array to base.foo (or replaces if base.foo absent).
 */
export function deepMerge(base, override) {
  if (!isObj(base)) return clone(override);
  if (!isObj(override)) return override === undefined ? clone(base) : override;
  const out = clone(base);
  for (const [k, v] of Object.entries(override)) {
    if (k.startsWith('+')) {
      const realKey = k.slice(1);
      const baseArr = Array.isArray(out[realKey]) ? out[realKey] : [];
      out[realKey] = baseArr.concat(Array.isArray(v) ? v : [v]);
    } else if (isObj(v) && isObj(out[k])) {
      out[k] = deepMerge(out[k], v);
    } else {
      out[k] = clone(v);
    }
  }
  return out;
}
const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));

/**
 * Resolve `inherits:` WITHIN a deliverables list — a list item may inherit a sibling by
 * its `id` (e.g. youtube_main inherits prores_master, then swaps codec/loudness). Merges
 * the referenced sibling under the item and drops the `inherits` key, so it's never an
 * inert no-op. Returns cfg with deliverables resolved (cfg unchanged if no list).
 */
export function resolveDeliverableInherits(cfg) {
  if (!isObj(cfg) || !Array.isArray(cfg.deliverables)) return cfg;
  const byId = new Map(cfg.deliverables.filter((d) => d && d.id).map((d) => [d.id, d]));
  const memo = new Map(),
    visiting = new Set();
  const resolveItem = (d) => {
    if (!d || !d.id) return d;
    if (memo.has(d.id)) return memo.get(d.id);
    if (!d.inherits) {
      memo.set(d.id, d);
      return d;
    }
    if (visiting.has(d.id)) throw new Error(`deliverable inherits cycle at '${d.id}'`);
    const parent = byId.get(d.inherits);
    if (!parent) throw new Error(`deliverable '${d.id}' inherits unknown '${d.inherits}'`);
    visiting.add(d.id);
    const { inherits, ...rest } = d;
    const merged = deepMerge(resolveItem(parent), rest);
    visiting.delete(d.id);
    memo.set(d.id, merged);
    return merged;
  };
  return { ...cfg, deliverables: cfg.deliverables.map(resolveItem) };
}

const KNOWN_SCIENCE = ['acescct', 'acescc', 'davinci_yrgb', 'davinci_wide_gamut', 'rec709', 'cineon'];
const KNOWN_STAGES = ['ingest', 'conform', 'offline_ref', 'color_groups', 'leveling', 'grade', 'audio_sync', 'qc', 'deliver'];

/**
 * Validate a RESOLVED entity config. Throws with a clear path on the failures we have
 * actually been bitten by (silent identity/empty). Lenient elsewhere (specs evolve).
 */
export function validateResolved(kind, slug, cfg) {
  const err = (msg) => {
    throw new Error(`spec invalid [${kind}:${slug}]: ${msg}`);
  };
  // Color science lives under grade.color_science (real authoring schema) or color.science
  // (the roadmap's illustrative form) — accept either.
  const science = cfg?.grade?.color_science ?? cfg?.color?.science;
  if (science && !KNOWN_SCIENCE.includes(String(science).toLowerCase())) {
    err(`color science '${science}' unknown (${KNOWN_SCIENCE.join('|')})`);
  }
  if (kind === 'deliverable') {
    if (!cfg?.video?.codec) err('deliverable requires video.codec');
  }
  // Deliverables authored as a config list (the common form) — each needs video.codec.
  if (Array.isArray(cfg?.deliverables)) {
    for (const d of cfg.deliverables) {
      if (!d?.video?.codec) err(`deliverable '${d?.id ?? '?'}' requires video.codec`);
    }
  }
  if (Array.isArray(cfg?.pipeline)) {
    for (const st of cfg.pipeline) {
      const name = typeof st === 'string' ? st : st?.stage;
      if (!name) err(`pipeline entry missing a stage name (${JSON.stringify(st)})`);
      if (!KNOWN_STAGES.includes(name)) err(`pipeline stage '${name}' unknown (${KNOWN_STAGES.join('|')})`);
      if (isObj(st) && st.gate && !['review', 'pass'].includes(st.gate)) err(`stage '${name}' gate '${st.gate}' unknown (review|pass)`);
    }
  }
  return true;
}

/**
 * Compile authored specs into the DB with inheritance resolved.
 * @param {object} db
 * @param {Array<{slug, kind, parent?, resolveRef?, config?, inherits?}>} specs
 * @param {{now?: string}} [opts]
 * @returns {{compiled: string[], order: string[]}}
 */
export function compileSpecs(db, specs, opts = {}) {
  const now = opts.now ?? null;
  const bySlug = new Map();
  for (const s of specs) {
    if (!s.slug) throw new Error('every spec needs a slug');
    if (!ENTITY_KINDS.includes(s.kind)) throw new Error(`spec '${s.slug}': unknown kind '${s.kind}'`);
    if (bySlug.has(s.slug)) throw new Error(`duplicate slug '${s.slug}'`);
    bySlug.set(s.slug, s);
  }
  // Topological order: parents (and `inherits` siblings) before dependents.
  const resolved = new Map();
  const visiting = new Set();
  const order = [];
  function resolve(slug) {
    if (resolved.has(slug)) return resolved.get(slug);
    if (visiting.has(slug)) throw new Error(`inheritance cycle at '${slug}'`);
    const s = bySlug.get(slug);
    if (!s) throw new Error(`spec references missing entity '${slug}'`);
    visiting.add(slug);
    let base = {};
    if (s.parent) base = deepMerge(base, resolve(s.parent));
    if (s.inherits) base = deepMerge(base, resolve(s.inherits)); // deliverable sibling reuse
    const cfg = resolveDeliverableInherits(deepMerge(base, s.config || {}));
    validateResolved(s.kind, s.slug, cfg);
    resolved.set(slug, cfg);
    visiting.delete(slug);
    order.push(slug);
    return cfg;
  }
  for (const s of specs) resolve(s.slug);

  for (const slug of order) {
    const s = bySlug.get(slug);
    upsertEntity(db, {
      slug,
      kind: s.kind,
      parentSlug: s.parent || null,
      resolveRef: s.resolveRef || null,
      raw: s.config || {},
      resolved: resolved.get(slug),
      now,
    });
  }
  return { compiled: order, order };
}

/**
 * Load entity specs from a directory of YAML files (the authoring surface). Each file is
 * a spec object with identity keys `slug`, `kind`, optional `parent`/`inherits`/`resolve_ref`
 * at the top level; everything else is its config. Subdir `_types/` files default to kind=type.
 * Deliverables can also be authored inline under an episode's `deliverables:` list.
 * @returns {Array} specs ready for compileSpecs
 */
export function loadYamlDir(dir) {
  const yaml = loadYaml();
  const specs = [];
  const files = [];
  const walk = (d) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.ya?ml$/.test(e.name)) files.push(p);
    }
  };
  walk(dir);
  for (const file of files) {
    const doc = yaml.load(fs.readFileSync(file, 'utf8'));
    if (!isObj(doc)) continue;
    // Note: `deliverables:` stays IN config (a list that flows through inheritance and is
    // read by the deliver stage) — not extracted to separate entities.
    const { slug, kind, parent, inherits, resolve_ref, ...config } = doc;
    // kind: explicit wins; files under _types/ default to 'type'. Non-type files need an
    // explicit `kind:` (series vs episode isn't inferable by location) → otherwise skipped.
    const inferredKind = kind || (file.includes(`${path.sep}_types${path.sep}`) ? 'type' : null);
    if (!inferredKind) continue; // not a compilable spec (e.g. a notes file)
    // slug: explicit wins; else honor the existing authoring convention — a type file's
    // identity is its `type:` field, a series file's is its `series:` field; else filename.
    const slugVal =
      slug || (inferredKind === 'type' ? config.type : inferredKind === 'series' ? config.series : null) || path.basename(file).replace(/\.ya?ml$/, '');
    const parentVal = parent || (inferredKind !== 'type' ? config.type : undefined); // episodes/series inherit their `type:`
    specs.push({
      slug: String(slugVal).toLowerCase(),
      kind: inferredKind,
      parent: parentVal ? String(parentVal).toLowerCase() : undefined,
      inherits,
      resolveRef: resolve_ref,
      config,
    });
  }
  return specs;
}
