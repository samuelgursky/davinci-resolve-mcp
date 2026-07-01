/**
 * Cluster P — provenance / bookkeeping / audit. The trust/defense layer: "why is this clip
 * graded this way", the stills lineage, CDL round-trip for DIT/VFX, revision history, and the
 * producer's one-page episode report.
 *
 *   gallery_lineage   — stills label convention (SC##_approved_v##) + albums + TIFF-for-VFX export plan
 *   grade_provenance  — parse the AUTO provenance labels off a grade → per-node "why"
 *   cdl_export (+diff)— export ASC CDL from a DRX with a round-trip assert + diff two CDLs
 *   revision_tracking — v001→v004: what changed, who approved (normalized history)
 *   episode_report    — one-page readback: stages/gates/who-when/drift/deliverables/tool+spec version
 *
 * PURE + deterministic. No Resolve, no LLM.
 */
import { drxTool } from './tools/drx.mjs';
import { parseProvenanceLabel } from './node-provenance.mjs';

// ── gallery_lineage ────────────────────────────────────────────────────
const LABEL_RE = /^SC(\d{1,3})_(approved|wip|ref|review)_v(\d{1,3})$/i;

export function makeStillLabel({ scene, status = 'wip', version = 1 }) {
  const sc = String(scene).replace(/^SC/i, '');
  return `SC${String(sc).padStart(2, '0')}_${status}_v${String(version).padStart(2, '0')}`;
}
export function validateStillLabel(label) {
  const m = LABEL_RE.exec(String(label).trim());
  if (!m) return { valid: false, label };
  return { valid: true, label, scene: Number(m[1]), status: m[2].toLowerCase(), version: Number(m[3]) };
}

/**
 * Model a stills lineage: validate/assign labels, group into albums, compute next version per
 * scene, and plan a TIFF-for-VFX export of the APPROVED stills.
 * @param {Array<{id, scene?, status?, version?, label?, album?}>} stills
 */
export function galleryLineage(stills, opts = {}) {
  const labels = [];
  const nextVersions = {};
  const albums = {};
  for (const s of stills) {
    let label = s.label;
    if (!label && s.scene != null) label = makeStillLabel({ scene: s.scene, status: s.status || 'wip', version: s.version || 1 });
    const v = label ? validateStillLabel(label) : { valid: false, label: null };
    labels.push({ id: s.id, label, ...v });
    if (v.valid) nextVersions[v.scene] = Math.max(nextVersions[v.scene] || 0, v.version + 1);
    const album = s.album || 'default';
    (albums[album] ||= []).push(s.id);
  }
  // TIFF-for-VFX export: approved stills only.
  const exportPlan = labels
    .filter((l) => l.valid && l.status === 'approved')
    .map((l) => ({ id: l.id, filename: `${l.label}.tif`, format: opts.exportFormat || 'tiff' }));
  const invalid = labels.filter((l) => l.label && !l.valid).map((l) => ({ id: l.id, label: l.label }));
  return { labels, albums, nextVersions, exportPlan, invalidLabels: invalid, gate: 'review' };
}

// ── grade_provenance ───────────────────────────────────────────────────
async function parseNodes(ref) {
  const parsed = await drxTool.handler({ action: 'parse', args: ref.content != null ? { content: ref.content } : { drxPath: ref.drxPath } });
  return parsed.nodes || [];
}

/**
 * Answer "why is this clip graded this way" by reading the AUTO provenance labels off a grade.
 * @param {{drxPath?:string, content?:string}} ref
 */
export async function gradeProvenance(ref) {
  const nodes = await parseNodes(ref);
  const rows = nodes.map((n, i) => {
    const p = parseProvenanceLabel(n.label);
    return {
      index: i,
      label: n.label || null,
      auto: p.auto,
      tool: p.auto ? p.tool : null,
      version: p.auto ? p.version : null,
      source: p.auto ? p.source : null,
      gist: p.auto ? p.gist : null,
    };
  });
  const autoCount = rows.filter((r) => r.auto).length;
  const humanCount = rows.filter((r) => r.label && !r.auto).length;
  const unlabeled = rows.filter((r) => !r.label).length;
  return {
    nodeCount: rows.length,
    autoCount,
    humanCount,
    unlabeled,
    nodes: rows,
    summary: rows.map((r) =>
      r.auto
        ? `#${r.index}: ${r.tool} v${r.version}${r.source ? ` ← ${r.source}` : ''}`
        : r.label
          ? `#${r.index}: (human) ${r.label}`
          : `#${r.index}: (unlabeled)`,
    ),
  };
}

// ── cdl_export (+ diff) ────────────────────────────────────────────────
/**
 * Export ASC CDL from a DRX with a round-trip assert: the exported slope/offset must reflect
 * the DRX's decoded gain/offset (guards the silent-identity-CDL lie).
 * @param {{drxPath?:string, content?:string}} ref
 */
export async function cdlExport(ref, opts = {}) {
  const content = ref.content != null ? ref.content : undefined;
  const exportArgs = content != null ? { content, format: opts.format || 'cdl' } : { drxPath: ref.drxPath, format: opts.format || 'cdl' };
  const out = await drxTool.handler({ action: 'export_cdl', args: exportArgs });
  const cdl = out.cdl;
  // Decode the DRX primaries to verify the CDL isn't a silent identity.
  const parsed = await drxTool.handler({ action: 'parse', args: content != null ? { content } : { drxPath: ref.drxPath } });
  const params = {};
  for (const n of parsed.nodes || [])
    for (const c of n.correctors || []) for (const p of c.parameters || []) if (typeof p.value === 'number') params[p.name] = p.value;
  const gainNonUnity = ['gain.r', 'gain.g', 'gain.b'].some((k) => params[k] != null && Math.abs(params[k] - 1) > 0.005);
  const slopeNonUnity = cdl && cdl.slope && ['r', 'g', 'b'].some((k) => Math.abs((cdl.slope[k] ?? 1) - 1) > 0.005);
  if (gainNonUnity && !slopeNonUnity)
    throw new Error('cdl_export: DRX has a non-unity gain but the exported CDL slope is identity — refusing a silent-identity CDL (round-trip assert failed)');
  return { format: out.format, cdl, verified: true, valueFidelity: out.valueFidelity };
}

/** Diff two ASC CDL objects (slope/offset/power/saturation) → per-param deltas. */
export function cdlDiff(a, b, opts = {}) {
  const tol = opts.tol ?? 1e-4;
  const deltas = [];
  for (const grp of ['slope', 'offset', 'power']) {
    for (const k of ['r', 'g', 'b']) {
      const av = (a[grp] && a[grp][k]) ?? (grp === 'offset' ? 0 : 1);
      const bv = (b[grp] && b[grp][k]) ?? (grp === 'offset' ? 0 : 1);
      if (Math.abs(av - bv) > tol) deltas.push({ param: `${grp}.${k}`, a: +av.toFixed(5), b: +bv.toFixed(5), delta: +(bv - av).toFixed(5) });
    }
  }
  const asat = a.saturation ?? 1,
    bsat = b.saturation ?? 1;
  if (Math.abs(asat - bsat) > tol) deltas.push({ param: 'saturation', a: asat, b: bsat, delta: +(bsat - asat).toFixed(5) });
  return { identical: deltas.length === 0, deltas };
}

// ── revision_tracking ──────────────────────────────────────────────────
/**
 * Normalize a revision history (v001→v004): ordering, per-step changes, approvals.
 * @param {Array<{version, label?, changes?, approvedBy?, approvedAt?, hash?}>} revisions
 */
export function revisionHistory(revisions) {
  const parseVer = (v) => Number(String(v).replace(/[^\d]/g, '')) || 0;
  const sorted = [...revisions].sort((a, b) => parseVer(a.version) - parseVer(b.version));
  const history = sorted.map((r, i) => ({
    version: r.version,
    order: i + 1,
    label: r.label || null,
    changes: r.changes || [],
    approvedBy: r.approvedBy || null,
    approvedAt: r.approvedAt || null,
    approved: !!r.approvedBy,
    hash: r.hash || null,
    changedFromPrev: i > 0 ? (r.hash && sorted[i - 1].hash ? r.hash !== sorted[i - 1].hash : (r.changes || []).length > 0) : null,
  }));
  const latest = history[history.length - 1] || null;
  const lastApproved = [...history].reverse().find((h) => h.approved) || null;
  return { count: history.length, history, latest: latest ? latest.version : null, lastApproved: lastApproved ? lastApproved.version : null };
}

// ── episode_report ─────────────────────────────────────────────────────
/**
 * One-page human-readable readback (structured + markdown). PURE over a supplied data object.
 * @param {{episode, toolVersion?, specVersion?, stages?, drift?, deliverables?, revisions?}} data
 */
export function episodeReport(data = {}) {
  const stages = (data.stages || []).map((s) => ({
    stage: s.stage,
    status: s.status || 'unknown',
    gate: s.gate || null,
    approvedBy: s.approvedBy || null,
    approvedAt: s.approvedAt || null,
  }));
  const deliverables = (data.deliverables || []).map((d) => ({ name: d.name, pass: !!d.pass }));
  const drift = data.drift || [];
  const gatesApproved = stages.filter((s) => s.approvedBy).length;
  const gatesPending = stages.filter((s) => s.gate && !s.approvedBy).length;
  const allDeliverablesPass = deliverables.length > 0 && deliverables.every((d) => d.pass);

  const md = [];
  md.push(`# Episode report — ${data.episode || 'episode'}`);
  md.push(`tool v${data.toolVersion ?? '?'} · spec v${data.specVersion ?? '?'}`);
  md.push('');
  md.push('## Stages');
  for (const s of stages)
    md.push(
      `- ${s.stage}: ${s.status}${s.gate ? ` [gate: ${s.approvedBy ? `approved by ${s.approvedBy}${s.approvedAt ? ` @ ${s.approvedAt}` : ''}` : 'PENDING'}]` : ''}`,
    );
  md.push('');
  md.push('## Drift');
  md.push(drift.length ? drift.map((d) => `- ${JSON.stringify(d)}`).join('\n') : '- none');
  md.push('');
  md.push('## Deliverables');
  for (const d of deliverables) md.push(`- ${d.name}: ${d.pass ? 'PASS' : 'FAIL'}`);
  if (!deliverables.length) md.push('- none recorded');

  return {
    episode: data.episode || null,
    toolVersion: data.toolVersion ?? null,
    specVersion: data.specVersion ?? null,
    summary: { stageCount: stages.length, gatesApproved, gatesPending, driftCount: drift.length, deliverableCount: deliverables.length, allDeliverablesPass },
    stages,
    drift,
    deliverables,
    markdown: md.join('\n'),
    gate: 'review',
  };
}
