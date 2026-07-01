/**
 * ASC CDL import (C3 `cdl_io`).
 *
 * DITs and on-set colour ship looks as ASC CDL (.cc single,.ccc collection,.cdl) —
 * slope/offset/power + saturation. This brings those into the grade as per-clip.drx
 * so an on-set CDL can seed the look. The reverse (DRX → CDL) already exists as the
 * `export_cdl` action; this is the import direction.
 *
 * Pure composition of the validated codec: parseCDL → cdlToDRX → generateDRX, with a
 * round-trip non-empty assert (a non-identity CDL that decodes to an EMPTY grade is the
 * silent-drop bug — throw, don't ship a no-op). slope→gain, offset→offset, power→gamma
 * (model conversion, approximate by design — flagged), sat (0–2)→Resolve sat (0–100).
 * LOCAL & deterministic; no Resolve.
 */
import fs from 'node:fs';
import { drxCdl, drxGenerator, drxParser } from './libs.mjs';

const isIdentityCDL = (c) => {
  const s = c.slope || {},
    o = c.offset || {},
    p = c.power || {};
  const near = (v, t) => Math.abs((v ?? t) - t) < 1e-4;
  return (
    near(s.r, 1) &&
    near(s.g, 1) &&
    near(s.b, 1) &&
    near(o.r, 0) &&
    near(o.g, 0) &&
    near(o.b, 0) &&
    near(p.r, 1) &&
    near(p.g, 1) &&
    near(p.b, 1) &&
    near(c.saturation, 1)
  );
};

async function paramCount(content) {
  const parsed = await drxParser().parseDRXContent(content);
  return (parsed.nodes || []).flatMap((n) => (n.correctors || []).flatMap((cor) => cor.parameters || [])).length;
}

/**
 * @param {string} cdlContent — raw .cc/.ccc/.cdl XML
 * @param {{outDir:string}} opts
 * @returns {Promise<{grades:Array<{id,drxPath,identity:boolean}>, warnings:string[]}>}
 */
export async function importCDL(cdlContent, opts = {}) {
  if (!opts.outDir) throw new Error('opts.outDir required');
  const cdl = drxCdl();
  const corrections = cdl.parseCDL(cdlContent);
  if (!corrections.length) throw new Error('no <ColorCorrection> found — not a CDL/CCC/CC document');
  fs.mkdirSync(opts.outDir, { recursive: true });

  const grades = [];
  const warnings = [];
  let i = 0;
  for (const c of corrections) {
    const id = (c.id || `cc${i}`).replace(/[^\w.-]/g, '_');
    const values = c.cdlValues || c; // parseCDL nests under cdlValues
    const params = cdl.cdlToDRX(values);
    const out = await drxGenerator().generateDRX(params, { label: `CDL ${id}` });
    const content = typeof out === 'string' ? out : out?.content || out?.drxContent;
    const identity = isIdentityCDL(values);
    if (!identity && (await paramCount(content)) === 0) {
      throw new Error(`round-trip assert FAILED: CDL '${id}' is non-identity but generated an EMPTY grade (${JSON.stringify(values)})`);
    }
    const drxPath = `${opts.outDir}/${id}.drx`;
    fs.writeFileSync(drxPath, content);
    grades.push({ id, drxPath, identity });
    i++;
  }
  warnings.push(
    'power→gamma is a model conversion (Resolve gamma ≠ ASC power); the look is approximate by design, not a 1:1 transfer. Validate against the on-set reference.',
  );
  return { grades, warnings };
}
