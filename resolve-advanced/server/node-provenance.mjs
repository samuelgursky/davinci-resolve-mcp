/**
 * node-labeling / provenance (Layer-3 capability) — what makes AUTO-APPLY safe.
 *
 * The apply model (cross-craft review, Sam's call) is: the tool auto-applies conservative
 * defaults, LABELS every node it creates, then the human reviews the whole PASS and gives
 * feedback that reshapes the next run. The label is the safety mechanism — it makes every
 * auto node VISIBLE, reversible, tweakable, deletable, and answers "why is this clip graded
 * this way." So every emitted matcher node carries: tool + version + source + a params gist.
 *
 * Convention (stamped into the DRX node label F6, which round-trips through generate→parse):
 *   AUTO:<tool> v<ver> → <source> | <gist>
 * e.g.  AUTO:skin_match v1 → hero:CU_02 | gain(1.08,1.02,0.97)
 *
 * This module is PURE (no Resolve, no DB): it builds the label + a structured provenance
 * record. The runner/pipeline persists records; grade_provenance (Cluster P) parses the
 * label back out of an applied grade. Deterministic — no timestamps baked into the label
 * (callers add time to the DB record, not the label, so DRX output stays reproducible).
 */

// Per-tool version — bump when a tool's math/output changes so a stale auto node is visible.
export const TOOL_VERSIONS = {
  exposure_level: 1,
  skin_match: 2, // v2 = skin-line angle/distance metric
  shot_match: 1,
  white_balance_match: 1,
  contrast_normalize: 1,
  match_to_reference: 1,
  saturation_match: 1,
  black_balance: 1,
  grade_transfer: 1,
  cdl_io: 1,
};

export const AUTO_PREFIX = 'AUTO:';

/** Compact numeric gist, e.g. gain(1.08,1.02,0.97). Deterministic, fixed precision. */
export function gist(kind, obj) {
  if (obj == null) return '';
  if (Array.isArray(obj)) return `${kind}(${obj.map((v) => Number(v).toFixed(2)).join(',')})`;
  const order = ['r', 'g', 'b', 'master'];
  const vals = order.filter((k) => obj[k] != null).map((k) => Number(obj[k]).toFixed(2));
  return vals.length ? `${kind}(${vals.join(',')})` : '';
}

/**
 * Build the AUTO provenance label a tool stamps onto every node it creates.
 * @param {string} tool tool id (keyed in TOOL_VERSIONS)
 * @param {{source?:string, gist?:string, version?:number}} info
 */
export function provenanceLabel(tool, info = {}) {
  const ver = info.version ?? TOOL_VERSIONS[tool] ?? 1;
  const parts = [`${AUTO_PREFIX}${tool} v${ver}`];
  if (info.source) parts.push(`→ ${info.source}`);
  const g = info.gist || '';
  return g ? `${parts.join(' ')} | ${g}` : parts.join(' ');
}

/**
 * Structured provenance record for the DB (tenant-ready: `actor` provenance, no global slug).
 * Keeps the params + source so "why graded this way" is answerable without re-deriving.
 * @param {object} p
 * @returns {object}
 */
export function provenanceRecord(p) {
  const { tool, source = null, params = null, clipId = null, group = null, drxPath = null, pass = null, actor = 'system', gate = 'review' } = p;
  return {
    tool,
    version: TOOL_VERSIONS[tool] ?? 1,
    source,
    params,
    clipId,
    group,
    drxPath,
    pass,
    actor,
    gate,
    label: provenanceLabel(tool, { source, gist: p.gist }),
  };
}

const LABEL_RE = new RegExp(`^${AUTO_PREFIX}(\\S+)\\s+v(\\d+)(?:\\s+→\\s+([^|]+?))?(?:\\s*\\|\\s*(.*))?$`);

/**
 * Parse an AUTO provenance label back into its parts (for grade_provenance / verify_grade).
 * Returns { auto:false } for a human/unknown label — never guesses.
 */
export function parseProvenanceLabel(label) {
  if (typeof label !== 'string' || !label.startsWith(AUTO_PREFIX)) return { auto: false, label: label ?? null };
  const m = LABEL_RE.exec(label.trim());
  if (!m) return { auto: true, tool: null, version: null, source: null, gist: null, label };
  return {
    auto: true,
    tool: m[1],
    version: Number(m[2]),
    source: m[3] ? m[3].trim() : null,
    gist: m[4] ? m[4].trim() : null,
    label,
  };
}

/** True if a node label is an AUTO provenance label this engine emitted. */
export const isAutoLabel = (label) => typeof label === 'string' && label.startsWith(AUTO_PREFIX);
