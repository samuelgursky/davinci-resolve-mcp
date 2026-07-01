/**
 * grade_transfer season-look AUTHORING / versioning (the recurring PRODUCT) — carry the APPROVED
 * host/season look forward across episodes with lineage. Wraps the existing lossless grade_transfer
 * (Route A Body copy) with a versioned, hashed, provenance-stamped LOOK MANIFEST + a carry PLAN.
 *
 *   authorLook — decode a source group/DRX → apply-ready DRX + a versioned look manifest
 *                {name, version, approvedBy, sourceHash, drxPath, nodeCount}
 *   carryLook  — plan applying a versioned look onto target groups (per-target apply plan)
 *
 * PURE + deterministic (hash of the decoded body = the look's identity; no timestamps baked in).
 * No Resolve — carryLook emits a PLAN the live server applies (safe_apply_drx at group scope).
 */
import crypto from 'node:crypto';
import { transferGrade } from './grade-transfer.mjs';
import { drxTool } from './tools/drx.mjs';
import { provenanceLabel } from './node-provenance.mjs';

/**
 * Canonical, UUID-independent identity of a grade: sorted per-node numeric params. The DRX
 * wrapper embeds a fresh UUID per write, so hashing raw content is NOT stable — this hashes the
 * decoded GRADE VALUES so the same look re-authored yields the same identity.
 */
async function gradeIdentityHash(content) {
  const parsed = await drxTool.handler({ action: 'parse', args: { content } });
  const canon = (parsed.nodes || []).map((n) =>
    (n.correctors || [])
      .map((c) =>
        (c.parameters || [])
          .filter((p) => typeof p.value === 'number')
          .map((p) => `${p.name}=${p.value.toFixed(6)}`)
          .sort()
          .join(','),
      )
      .join('|'),
  );
  return crypto.createHash('sha256').update(JSON.stringify(canon)).digest('hex').slice(0, 16);
}

/**
 * Author a versioned season/host look from a source group/DRX.
 * @param {object} source { drpPath, group, which } OR { drxPath } OR { content } (as grade_transfer)
 * @param {{name:string, version:number, approvedBy?:string, outPath:string}} meta
 */
export async function authorLook(source, meta = {}) {
  if (!meta.name) throw new Error('authorLook: meta.name required (the look identity)');
  if (meta.version == null) throw new Error('authorLook: meta.version required');
  if (!meta.outPath) throw new Error('authorLook: meta.outPath required');
  const label = provenanceLabel('grade_transfer', { source: `look:${meta.name} v${meta.version}`, version: meta.version });
  const r = await transferGrade(source, { outPath: meta.outPath, label });
  // The look's IDENTITY = a hash of its decoded grade VALUES (deterministic; survives re-authoring
  // despite the wrapper's per-write UUID).
  const sourceHash = await gradeIdentityHash(r.content || '');
  return {
    manifest: {
      name: meta.name,
      version: meta.version,
      approvedBy: meta.approvedBy || null,
      sourceHash,
      drxPath: r.outPath,
      nodeCount: r.nodeCount,
      bodyBytes: r.bodyBytes,
      label,
    },
    outPath: r.outPath,
  };
}

/**
 * Plan carrying a versioned look onto target groups. Emits the apply plan (Node can't apply).
 * @param {object} lookManifest an authorLook() manifest
 * @param {Array<string|{group:string, episode?:string}>} targets group names (or {group, episode})
 * @param {{gradeMode?:string}} [opts]
 */
export function carryLook(lookManifest, targets = [], opts = {}) {
  if (!lookManifest || !lookManifest.drxPath) throw new Error('carryLook: a look manifest with drxPath is required');
  const gradeMode = opts.gradeMode || 'group';
  const plan = targets.map((t) => {
    const group = typeof t === 'string' ? t : t.group;
    return {
      action: 'timeline_item_color.safe_apply_drx',
      args: {
        drxPath: lookManifest.drxPath,
        group,
        gradeMode,
        episode: typeof t === 'object' ? t.episode || null : null,
        provenance: `${lookManifest.name} v${lookManifest.version} (${lookManifest.sourceHash})`,
      },
    };
  });
  return {
    look: { name: lookManifest.name, version: lookManifest.version, sourceHash: lookManifest.sourceHash },
    targetCount: plan.length,
    plan,
    gate: 'review',
  };
}
