'use strict';

/**
 * roles/ — finishing-media resolution (spec §10). Pure contracts + algorithms.
 *
 * Two mechanisms (decided): a per-version `editorialRole`, and a cross-asset
 * `MediaRelationship` (the load-bearing proxy↔scan link with a frameOffset).
 * The Prisma fields are thin bindings to these contracts; the resolution ORDER
 * and ingest heuristic live here and are fully verifiable without a DB.
 */

const EDITORIAL_ROLES = Object.freeze(['offline', 'proxy', 'online', 'finishing', 'reference', 'other']);
const MEDIA_RELATIONSHIP_KINDS = Object.freeze(['proxy_of', 'scan_of', 'vfx_of', 'upscale_of', 'regrade_of']);
// Relationship kinds that point from a working asset TO its finishing media.
const FINISHING_KINDS = Object.freeze(['scan_of', 'upscale_of', 'vfx_of', 'regrade_of']);

function isValidRole(r) {
  return EDITORIAL_ROLES.includes(r);
}

function makeMediaRelationship({ fromAssetId, toAssetId, kind, frameOffset = 0, notes = '' }) {
  if (!fromAssetId || !toAssetId) throw new Error('MediaRelationship: fromAssetId + toAssetId required');
  if (!MEDIA_RELATIONSHIP_KINDS.includes(kind)) throw new Error(`MediaRelationship: kind must be one of ${MEDIA_RELATIONSHIP_KINDS.join('|')}`);
  return { type: 'MediaRelationship', fromAssetId, toAssetId, kind, frameOffset, notes };
}

/** In-memory store (the Prisma table is a thin binding to this). */
class MediaRelationshipStore {
  constructor(seed = []) {
    this.rels = seed.map((r) => (r.type === 'MediaRelationship' ? r : makeMediaRelationship(r)));
  }

  add(rel) {
    const r = rel.type === 'MediaRelationship' ? rel : makeMediaRelationship(rel);
    this.rels.push(r);
    return r;
  }

  forAsset(assetId) {
    return this.rels.filter((r) => r.fromAssetId === assetId || r.toAssetId === assetId);
  }
}

/**
 * Resolution order (§10): which media does this reference conform to?
 *   explicit MediaRelationship → project override → version editorialRole
 *   (finishing→online) → naming convention (4K-2K→4K) → highest-resolution version.
 * @returns { assetId?, path?, via, frameOffset? }
 */
function resolveMedia(ref, ctx = {}) {
  const versions = ref.versions || [];

  // 1. explicit MediaRelationship to a finishing asset.
  if (ctx.relationships) {
    const rel = ctx.relationships.forAsset(ref.assetId).find((r) => r.fromAssetId === ref.assetId && FINISHING_KINDS.includes(r.kind));
    if (rel) {
      const p = ctx.resolveAssetPath ? ctx.resolveAssetPath(rel.toAssetId) : null;
      return { assetId: rel.toAssetId, path: p, via: 'relationship', frameOffset: rel.frameOffset };
    }
  }
  // 2. project override map.
  if (ctx.projectOverride && ctx.projectOverride[ref.assetId] != null) {
    return { path: ctx.projectOverride[ref.assetId], via: 'project-override' };
  }
  // 3. version editorialRole (finishing preferred, then online).
  const byRole = versions.find((v) => v.role === 'finishing') || versions.find((v) => v.role === 'online');
  if (byRole) return { path: byRole.path, via: 'role', role: byRole.role };
  // 4. naming convention: a "4K" version (not the "4K-2K" proxy).
  const scan = versions.find((v) => /\b4k\b/i.test(v.name || '') && !/4k-2k/i.test(v.name || ''));
  if (scan) return { path: scan.path, via: 'naming' };
  // 5. highest-resolution version.
  const top = versions.reduce((best, v) => (best == null || (v.width || 0) > (best.width || 0) ? v : best), null);
  return top ? { path: top.path, via: 'highest-res' } : { path: null, via: 'none' };
}

/**
 * Ingest heuristic (§10): seed a default role/relationship from res/codec/name.
 * Returns { role, relationship? } suggestions (user corrects via the UI picker).
 */
function ingestHeuristic(asset, opts = {}) {
  const name = (asset.name || '').toLowerCase();
  const w = asset.width || 0;
  let role = 'other';
  if (/proxy|4k-2k/.test(name) || (w > 0 && w <= 1024)) role = 'proxy';
  else if (/\b4k\b/.test(name) || w >= 3600) role = 'finishing';
  else if (/online|finish/.test(name)) role = 'online';
  else if (/offline/.test(name)) role = 'offline';
  const out = { role };
  // If a sibling finishing asset is offered, seed the proxy↔scan relationship.
  if (role === 'proxy' && opts.finishingAssetId) {
    out.relationship = makeMediaRelationship({ fromAssetId: asset.id, toAssetId: opts.finishingAssetId, kind: 'scan_of', frameOffset: opts.frameOffset || 0, notes: 'ingest heuristic' });
  }
  return out;
}

module.exports = { EDITORIAL_ROLES, MEDIA_RELATIONSHIP_KINDS, isValidRole, makeMediaRelationship, MediaRelationshipStore, resolveMedia, ingestHeuristic };
