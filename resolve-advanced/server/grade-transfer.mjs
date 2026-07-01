/**
 * Lossless grade transfer — Route A copy (C3 `grade_transfer`).
 *
 * Carry an EXACT grade from a source onto an apply-ready .drx, WITHOUT decoding and
 * re-encoding (decode→re-encode is lossy for OFX/ResolveFX and the uncalibrated tail).
 * We copy the raw <Body> blob verbatim and re-wrap it in the Gallery::GyStill envelope
 * Resolve's ApplyGradeFromDRX actually applies — so the transfer is byte-faithful.
 *
 * Sources:
 * { drpPath, group, which?:'post'|'pre' } — a colour-group look from an exported .drp
 * (the Route A workflow: read the season host look, transfer to this episode).
 * { drxPath } | { content } — re-wrap an existing .drx's grade body.
 *
 * GUARD: the wrapped body is parsed and must decode to ≥1 node — a transfer that yields
 * an empty grade is refused, not shipped (the silent-no-op bug class).
 * LOCAL & deterministic; emits the .drx. APPLY (ApplyGradeFromDRX) is the caller's job.
 */
import fs from 'node:fs';
import { readProjectXml, groupSegment, groupBodies } from './group-grade-read.mjs';
import { drxEnvelope } from './tools/color_trace.mjs';
import { drxTool } from './tools/drx.mjs';

/** Count nodes a raw body decodes to, via the parse-safe Resolve_Color_Exchange envelope. */
async function bodyNodeCount(bodyHex) {
  const content = `<?xml version="1.0" encoding="UTF-8"?>\n<Resolve_Color_Exchange><Label>assert</Label><Width>1920</Width><Height>1080</Height><Body>${bodyHex}</Body></Resolve_Color_Exchange>`;
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  return (r.nodes || []).length;
}

/**
 * @param {{drpPath?:string, group?:string, which?:'post'|'pre', drxPath?:string, content?:string}} source
 * @param {{outPath?:string, label?:string}} opts
 * @returns {Promise<{outPath?:string, content:string, nodeCount:number, bodyBytes:number, label:string, source:string}>}
 */
export async function transferGrade(source = {}, opts = {}) {
  let bodyHex, srcLabel, srcKind;
  if (source.drpPath) {
    if (!source.group) throw new Error('source.group required with drpPath');
    const xml = readProjectXml(source.drpPath);
    const seg = groupSegment(xml, source.group);
    if (!seg) throw new Error(`group '${source.group}' not found in ${source.drpPath}`);
    const bodies = groupBodies(seg);
    if (!bodies.length) throw new Error(`group '${source.group}' has no grade <Body>`);
    const which = source.which || 'post';
    bodyHex = which === 'pre' ? bodies[0] : bodies[bodies.length - 1];
    srcLabel = `${source.group} ${which}`;
    srcKind = `drp:${source.group}:${which}`;
  } else if (source.drxPath || source.content) {
    const xml = source.content || fs.readFileSync(source.drxPath, 'utf8');
    const m = xml.match(/<Body>([0-9a-fA-F]+)<\/Body>/);
    if (!m) throw new Error('no <Body> blob in source.drx');
    bodyHex = m[1];
    srcLabel = source.drxPath ? source.drxPath.split('/').pop() : 'drx';
    srcKind = `drx:${srcLabel}`;
  } else {
    throw new Error('provide source.drpPath+group, or source.drxPath/content');
  }

  const nodeCount = await bodyNodeCount(bodyHex);
  if (nodeCount === 0) throw new Error(`grade_transfer refused: source '${srcKind}' decodes to 0 nodes (empty grade)`);

  const label = opts.label || srcLabel;
  const content = drxEnvelope(label, bodyHex);
  if (opts.outPath) fs.writeFileSync(opts.outPath, content);
  return { outPath: opts.outPath, content, nodeCount, bodyBytes: bodyHex.length / 2, label, source: srcKind };
}
