/**
 * verify_grade (Layer-3 / Phase-2a) — the QC that turns "we GENERATED a grade" into "the
 * grade is PROVABLY on the clip." Decodes an INTENDED `.drx` and an APPLIED grade (the
 * readback the live Python server captured — a `.drx` from the group/clip via Route A) and
 * compares them node-by-node → a structured drift verdict.
 *
 * Verdict taxonomy:
 *   landed        — every comparable param matches within tolerance
 *   drifted       — lists per-node param deltas beyond tolerance
 *   missing       — applied has no grade / fewer nodes than intended
 *   unverifiable  — OFX / keyframed / uncalibrated params — FLAGGED per valueFidelity, NOT
 *                   judged (reuses the codec's existing keyframed/valueFidelity markers)
 *
 * Tolerance: calibrated native params (primaries, log wheels, curves) compare within
 * UI-scaled rounding (~1e-3). Keyframed nodes and non-numeric/plugin params decode
 * unverifiable — flagged, never silently "landed" (that would be the silent-lie class).
 *
 * PURE: parses two decoded grades and compares. No Resolve. The live capture of the applied
 * grade is the caller's job (Python live server) — this module judges what it's handed.
 */
import fs from 'node:fs/promises';
import { drxTool } from './tools/drx.mjs';

// A param's unity/default when it's absent from a grade (the codec only writes non-default
// params). Multiplicative controls default to 1; additive controls to 0.
function defaultFor(name) {
  return /^(gain|gamma|contrast)\b/i.test(name) ? 1 : 0;
}

/** Flatten a parsed node's correctors → { numeric:{name:value}, nonNumericNames:[...] }. */
function flattenParams(node) {
  const numeric = {};
  const nonNumeric = [];
  for (const cor of node.correctors || []) {
    for (const p of cor.parameters || []) {
      if (typeof p.value === 'number' && Number.isFinite(p.value)) numeric[p.name] = p.value;
      else nonNumeric.push(p.name);
    }
  }
  return { numeric, nonNumeric };
}

async function parseGrade(g) {
  if (g && Array.isArray(g.nodes)) return g; // already parsed
  const content = g.content != null ? g.content : await fs.readFile(g.drxPath, 'utf8');
  return drxTool.handler({ action: 'parse', args: { content } });
}

/**
 * @param {{intended:{drxPath?,content?,nodes?}, applied:{drxPath?,content?,nodes?}}} inp
 * @param {{tol?:number}} [opts]
 * @returns {Promise<{verdict:string, nodes:Array, counts:object, warnings:string[]}>}
 */
export async function verifyGrade(inp, opts = {}) {
  const tol = opts.tol ?? 1e-3;
  const intended = await parseGrade(inp.intended);
  const applied = await parseGrade(inp.applied);
  const iNodes = intended.nodes || [];
  const aNodes = applied.nodes || [];
  const warnings = [];

  const nodes = [];
  for (let i = 0; i < iNodes.length; i++) {
    const iN = iNodes[i];
    const aN = aNodes[i];
    if (!aN) {
      nodes.push({ index: i, status: 'missing', reason: 'applied grade has no node at this index' });
      continue;
    }
    // Keyframed / animated grades relocate values out of the static param lists — can't judge statically.
    if (iN.keyframed || aN.keyframed) {
      nodes.push({ index: i, status: 'unverifiable', reason: 'keyframed/animated node — static compare not valid' });
      continue;
    }
    const iP = flattenParams(iN);
    const aP = flattenParams(aN);
    const names = new Set([...Object.keys(iP.numeric), ...Object.keys(aP.numeric)]);
    const deltas = [];
    for (const name of names) {
      const iv = iP.numeric[name] ?? defaultFor(name);
      const av = aP.numeric[name] ?? defaultFor(name);
      const d = Math.abs(iv - av);
      if (d > tol) deltas.push({ param: name, intended: +iv.toFixed(5), applied: +av.toFixed(5), delta: +d.toFixed(5) });
    }
    const nonNumeric = [...new Set([...iP.nonNumeric, ...aP.nonNumeric])];
    const node = { index: i, status: deltas.length ? 'drifted' : 'landed' };
    if (deltas.length) node.deltas = deltas;
    if (nonNumeric.length) {
      node.unverifiableParams = nonNumeric;
      node.note = 'non-numeric/plugin params present (OFX/qualifier/window) — not judged; use live scopes';
    }
    nodes.push(node);
  }
  // Extra applied nodes beyond intended are reported but don't fail the verdict (an added trim).
  for (let i = iNodes.length; i < aNodes.length; i++) nodes.push({ index: i, status: 'extra', reason: 'applied has a node not in the intended grade' });

  const counts = { landed: 0, drifted: 0, missing: 0, unverifiable: 0, extra: 0 };
  for (const n of nodes) counts[n.status] = (counts[n.status] || 0) + 1;

  // Overall verdict, worst-of the meaningful statuses.
  let verdict;
  if (!iNodes.length) verdict = 'unverifiable';
  else if (counts.missing > 0) verdict = 'missing';
  else if (counts.drifted > 0) verdict = 'drifted';
  else if (counts.landed > 0) verdict = 'landed';
  else verdict = 'unverifiable';

  if (verdict === 'drifted') warnings.push(`${counts.drifted} node(s) drifted beyond tol ${tol} — review the deltas before signing off.`);
  if (verdict === 'missing') warnings.push(`${counts.missing} intended node(s) missing from the applied grade — apply may not have landed.`);
  if (counts.unverifiable > 0) warnings.push(`${counts.unverifiable} node(s) unverifiable (keyframed/plugin) — confirm on live scopes, not decoded values.`);

  return { verdict, nodes, counts, tol, warnings, valueFidelity: intended.valueFidelity || applied.valueFidelity };
}
