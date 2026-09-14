/**
 * Whole-.drp "Cleanup Node Graph" — every node graph an exported project carries,
 * scoped by anything the .drp can name, relaid out to Resolve's clean row with the
 * grade content byte-preserved.
 *
 * Where node graphs live in a .drp (measured on Resolve 19.1.3 exports, DbPrjVer 14):
 *
 *   SeqContainer/<uuid>.xml   VideoTrackVec → Sm2TiTrack(Type 0, Sequence=SEQ) → Items →
 *                              Sm2TiVideoClip → pLmVerTable → Locals → LmVersion   [kind local]
 *                              (one Element per LOCAL VERSION — a clip with three
 *                              versions carries three graphs; pActive names the live one)
 *   MediaPool/**\/MpFolder.xml Sm2MpVideoClip → pLmVerTable (VerType 1)            [kind remote]
 *                              Sm2Timeline → Name + Sm2Sequence(DbId=SEQ) → pLmVerTable [kind sequence]
 *   project.xml               Sm2GroupList → Sm2Group → Name + pLmVerTable
 *                              ("Pre Clip Grade" / "Post Clip Grade" versions)      [kind group]
 *
 * Every LmVersion has a UUID DbId, so a rewrite targets `<ListMgt::LmVersion DbId="…">`
 * and replaces only the `<Body>` inside it. HasCorrection is left exactly as found
 * (relayout is not a grade change), unlike inject-grades which flips it on purpose.
 *
 * The position rewrite itself is node-layout.js (the same bytes Resolve's own Cleanup
 * Node Graph writes — see that module). This file is the inventory + scope + zip
 * plumbing + read-back verification around it.
 */

import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import JSZip from 'jszip';

const require = createRequire(import.meta.url);
const layout = () => require('../vendor/drx-codec/node-layout.js');
const drxParser = () => require('../vendor/drx-codec/drx-parser.js');

export const GRAPH_KINDS = ['local', 'remote', 'group', 'sequence'];

// ── tiny XML helpers (Resolve's serializer is regular enough for regex) ─────

const scalar = (xml, tag) => {
  const m = xml.match(new RegExp(`<${tag}>([^<]*)</${tag}>`));
  return m ? m[1].trim() : null;
};
const escapeRegex = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** Elements `<Tag DbId="…">…</Tag>` — Resolve never nests a tag inside itself. */
function elements(xml, tag) {
  const re = new RegExp(`<${tag} DbId="([^"]+)">([\\s\\S]*?)</${tag}>`, 'g');
  const out = [];
  for (const m of xml.matchAll(re)) out.push({ id: m[1], inner: m[2], start: m.index, end: m.index + m[0].length });
  return out;
}

/** Versions of one `<pLmVerTable>` block: [{id, name, hasCorrection, verType, bodyHex, active}]. */
function versionsOf(ownerXml) {
  const vt = ownerXml.match(/<pLmVerTable>([\s\S]*?)<\/pLmVerTable>/);
  if (!vt) return { versions: [], active: null, linkedGroup: null, tableVerType: null };
  const tbl = vt[1];
  const active = scalar(tbl, 'pActive');
  const linkedGroup = scalar(tbl, 'LinkedGroup');
  const tableVerType = scalar(tbl, 'VerType');
  const versions = elements(tbl, 'ListMgt::LmVersion').map((v) => {
    const body = (v.inner.match(/<Body>([0-9a-fA-F\s]*)<\/Body>/) || [null, ''])[1];
    return {
      id: v.id,
      name: scalar(v.inner, 'Name') || '',
      hasCorrection: /<HasCorrection>true<\/HasCorrection>/.test(v.inner),
      verType: Number(scalar(v.inner, 'VerType') ?? tableVerType ?? 0),
      bodyHex: body ? body.replace(/[^0-9a-fA-F]/g, '').toLowerCase() : '',
      active: v.id === active,
    };
  });
  return { versions, active, linkedGroup, tableVerType };
}

function globToRegExp(glob) {
  const esc = String(glob).replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.');
  return new RegExp(`^${esc}$`, 'i');
}
function matchesAny(value, globs) {
  if (globs === undefined || globs === null) return true;
  const list = Array.isArray(globs) ? globs : [globs];
  if (list.length === 0) return true;
  const v = String(value ?? '');
  return list.some((g) => globToRegExp(g).test(v));
}
const asList = (v) => (v === undefined || v === null ? [] : Array.isArray(v) ? v : [v]);

// ── zip plumbing ────────────────────────────────────────────────────────────

const isSeqContainer = (p) => /(^|\/)SeqContainer(\d*\.xml|\/[^/]+\.xml)$/.test(p);
const isMpFolder = (p) => /(^|\/)MpFolder\.xml$/.test(p);
const isProjectXml = (p) => /(^|\/)project\.xml$/.test(p);

async function loadZip(drpPath) {
  const buf = await fs.readFile(drpPath);
  const zip = await JSZip.loadAsync(buf);
  const entries = {};
  const names = [];
  zip.forEach((p, e) => {
    if (!e.dir) names.push(p);
  });
  for (const p of names.sort()) {
    if (isSeqContainer(p) || isMpFolder(p) || isProjectXml(p)) entries[p] = await zip.file(p).async('string');
  }
  return { zip, entries };
}

// ── inventory ───────────────────────────────────────────────────────────────

/**
 * Index every node graph in the .drp.
 * @returns {{ graphs: Graph[], timelines: [{name, sequenceId}], groups: [{id, name}], projectName }}
 */
export function indexNodeGraphs(entries) {
  const mpXmls = Object.entries(entries).filter(([p]) => isMpFolder(p));
  const seqXmls = Object.entries(entries).filter(([p]) => isSeqContainer(p));
  const projEntry = Object.entries(entries).find(([p]) => isProjectXml(p));
  const projectXml = projEntry ? projEntry[1] : '';
  const projectName = scalar(projectXml, 'ProjectName') || scalar(projectXml, 'Name') || null;

  // Groups: id → name (project.xml). Their pre/post graphs are versions of the group.
  const groups = [];
  const graphs = [];
  const groupList = projectXml.match(/<GroupListObj>([\s\S]*?)<\/GroupListObj>/);
  if (groupList) {
    for (const g of elements(groupList[1], 'Sm2Group')) {
      const name = scalar(g.inner, 'Name') || g.id;
      groups.push({ id: g.id, name });
      const { versions } = versionsOf(g.inner);
      for (const v of versions) {
        graphs.push({
          kind: 'group',
          entry: projEntry[0],
          versionId: v.id,
          versionName: v.name,
          active: true,
          hasCorrection: v.hasCorrection,
          bodyHex: v.bodyHex,
          group: name,
          slot: /pre/i.test(v.name) ? 'pre' : /post/i.test(v.name) ? 'post' : null,
          label: `${name} · ${v.name}`,
        });
      }
    }
  }
  const groupNameById = new Map(groups.map((g) => [g.id, g.name]));

  // Timelines: sequence id → name (media pool). Sequence-level graphs ride along.
  const timelines = [];
  const timelineBySeq = new Map();
  for (const [entry, xml] of mpXmls) {
    for (const t of elements(xml, 'Sm2Timeline')) {
      const name = scalar(t.inner, 'Name') || t.id;
      const seq = t.inner.match(/<Sm2Sequence DbId="([^"]+)">([\s\S]*?)<\/Sm2Sequence>/);
      const sequenceId = seq ? seq[1] : null;
      timelines.push({ name, timelineId: t.id, sequenceId });
      if (sequenceId) timelineBySeq.set(sequenceId, name);
      if (seq) {
        const { versions } = versionsOf(seq[2]);
        for (const v of versions) {
          graphs.push({
            kind: 'sequence',
            entry,
            versionId: v.id,
            versionName: v.name,
            active: v.active,
            hasCorrection: v.hasCorrection,
            bodyHex: v.bodyHex,
            timeline: name,
            label: `${name} · ${v.name}`,
          });
        }
      }
    }
    // Remote versions sit on the media-pool clip itself.
    for (const c of elements(xml, 'Sm2MpVideoClip')) {
      const { versions } = versionsOf(c.inner);
      if (!versions.length) continue;
      const mediaPath = scalar(c.inner, 'MediaFilePath') || '';
      const clipName = scalar(c.inner, 'Name') || path.basename(mediaPath) || c.id;
      for (const v of versions) {
        graphs.push({
          kind: 'remote',
          entry,
          versionId: v.id,
          versionName: v.name,
          active: v.active,
          hasCorrection: v.hasCorrection,
          bodyHex: v.bodyHex,
          mediaPoolClipId: c.id,
          clipName,
          mediaPath,
          mediaName: path.basename(mediaPath),
          label: `${clipName} · ${v.name} (remote)`,
        });
      }
    }
  }

  // Local versions: per timeline clip, in track/item order.
  for (const [entry, xml] of seqXmls) {
    const vec = xml.match(/<VideoTrackVec>([\s\S]*?)<\/VideoTrackVec>/);
    if (!vec) continue;
    // Track numbers count per SEQUENCE (V1, V2, … as the timeline shows them) —
    // Resolve writes one container per timeline, but never assume it.
    const trackNoBySeq = new Map();
    for (const t of elements(vec[1], 'Sm2TiTrack')) {
      if (Number(scalar(t.inner, 'Type') ?? 0) !== 0) continue; // video tracks only
      const sequenceId = scalar(t.inner, 'Sequence');
      const trackNo = (trackNoBySeq.get(sequenceId) || 0) + 1;
      trackNoBySeq.set(sequenceId, trackNo);
      const timeline = timelineBySeq.get(sequenceId) || sequenceId || '(unknown timeline)';
      let clipNo = 0;
      for (const c of elements(t.inner, 'Sm2TiVideoClip')) {
        clipNo += 1;
        const start = Number(scalar(c.inner, 'Start'));
        const duration = Number(scalar(c.inner, 'Duration'));
        const mediaPath = scalar(c.inner, 'MediaFilePath') || '';
        const clipName = scalar(c.inner, 'Name') || path.basename(mediaPath) || c.id;
        const { versions, linkedGroup } = versionsOf(c.inner);
        const group = linkedGroup ? groupNameById.get(linkedGroup) || null : null;
        for (const v of versions) {
          graphs.push({
            kind: 'local',
            entry,
            versionId: v.id,
            versionName: v.name,
            active: v.active,
            hasCorrection: v.hasCorrection,
            bodyHex: v.bodyHex,
            clipId: c.id,
            clipName,
            timeline,
            track: trackNo,
            clipIndex: clipNo,
            start: Number.isFinite(start) ? start : null,
            end: Number.isFinite(start) && Number.isFinite(duration) ? start + duration - 1 : null,
            duration: Number.isFinite(duration) ? duration : null,
            mediaPath,
            mediaName: path.basename(mediaPath),
            group,
            versionCount: versions.length,
            label: `${timeline} V${trackNo} #${clipNo} ${clipName}${versions.length > 1 ? ` · ${v.name}` : ''}`,
          });
        }
      }
    }
  }

  return { graphs, timelines, groups, projectName };
}

// ── scope ───────────────────────────────────────────────────────────────────

/**
 * Does one graph fall inside one scope object? All present selectors AND.
 * Selectors that only make sense for clip graphs (timelines, tracks, frames, …)
 * exclude the other kinds when set — a scope naming a timeline never sweeps
 * group graphs along by accident.
 */
export function graphInScope(g, s, decoded) {
  if (!s) return true;
  const kinds = asList(s.kinds);
  if (kinds.length && !kinds.includes(g.kind)) return false;
  const clipish = g.kind === 'local';
  const clipOnly = (cond) => (clipish ? cond() : false);

  if (s.timelines !== undefined && asList(s.timelines).length && !(asList(s.timelines).includes('*'))) {
    if (g.kind === 'group' || g.kind === 'remote') return false;
    if (!matchesAny(g.timeline, s.timelines)) return false;
  }
  if (asList(s.tracks).length && !clipOnly(() => asList(s.tracks).map(Number).includes(g.track))) return false;
  if (asList(s.clipIds).length && !clipOnly(() => asList(s.clipIds).includes(g.clipId))) return false;
  if (asList(s.excludeClipIds).length && clipish && asList(s.excludeClipIds).includes(g.clipId)) return false;
  if (asList(s.names).length && !clipOnly(() => matchesAny(g.clipName, s.names))) return false;
  if (asList(s.media).length) {
    if (g.kind !== 'local' && g.kind !== 'remote') return false;
    if (!(matchesAny(g.mediaName, s.media) || matchesAny(g.mediaPath, s.media))) return false;
  }
  if (Array.isArray(s.frames) && s.frames.length === 2) {
    const [a, b] = s.frames.map(Number);
    if (!clipOnly(() => g.start !== null && g.end !== null && g.end >= a && g.start <= b)) return false;
  }
  if (Array.isArray(s.clipRange) && s.clipRange.length === 2) {
    const [a, b] = s.clipRange.map(Number);
    if (!clipOnly(() => g.clipIndex >= a && g.clipIndex <= b)) return false;
  }
  if (asList(s.groups).length) {
    if (g.kind === 'local') {
      if (!g.group || !asList(s.groups).some((x) => globToRegExp(x).test(g.group))) return false;
    } else if (g.kind === 'group') {
      if (!asList(s.groups).some((x) => globToRegExp(x).test(g.group))) return false;
    } else return false;
  }
  if (asList(s.excludeGroups).length && (g.kind === 'local' || g.kind === 'group') && g.group) {
    if (asList(s.excludeGroups).some((x) => globToRegExp(x).test(g.group))) return false;
  }
  if (s.versions === 'active' && !g.active) return false;
  if (asList(s.versionNames).length && !matchesAny(g.versionName, s.versionNames)) return false;
  if (s.gradedOnly !== false) {
    // "graded" = Resolve's own flag OR a graph that visibly has more than the one default node.
    if (!g.hasCorrection && !(decoded && decoded.nodeCount >= 2)) return false;
  }
  if (s.minNodes !== undefined && !(decoded && decoded.nodeCount >= Number(s.minNodes))) return false;
  if (s.maxNodes !== undefined && !(decoded && decoded.nodeCount <= Number(s.maxNodes))) return false;
  if (asList(s.nodeLabels).length) {
    const labels = (decoded && decoded.labels) || [];
    if (!labels.some((l) => matchesAny(l, s.nodeLabels))) return false;
  }
  return true;
}

// ── decode helpers ──────────────────────────────────────────────────────────

const DRX_ENVELOPE = (hex) =>
  `<?xml version="1.0" encoding="UTF-8"?>\n<Resolve_Color_Exchange>\n <Label>x</Label>\n <Width>1920</Width>\n <Height>1080</Height>\n <Body>${hex}</Body>\n</Resolve_Color_Exchange>\n`;

async function decodeGraph(g, { labels, layoutOpts }) {
  if (!g.bodyHex) return { error: 'no <Body>' };
  const body = Buffer.from(g.bodyHex, 'hex');
  let topo;
  try {
    topo = await layout().readTopology(body, layoutOpts);
  } catch (e) {
    return { error: e.message };
  }
  const positions = topo.nodes.map((n) => [n.x, n.y]);
  const out = { nodeCount: positions.length, positions, planned: topo.planned, meta: topo.meta, edges: topo.edges.length };
  if (labels) {
    try {
      const parsed = await drxParser().parseDRXContent(DRX_ENVELOPE(g.bodyHex));
      out.labels = (parsed.nodes || []).map((n) => String(n.label || ''));
    } catch {
      out.labels = [];
    }
  }
  return out;
}

const within = (a, b, tol) => a != null && b != null && Math.abs(a - b) <= tol;
function isClean(before, target, tol = 2) {
  return (
    before.length === target.length &&
    before.every(([bx, by], i) => within(bx, target[i][0], tol) && within(by, target[i][1], tol))
  );
}

// ── the sweep ───────────────────────────────────────────────────────────────

/**
 * @param {string} drpPath
 * @param {object} opts
 * @param {string} [opts.outputPath]  required unless dryRun
 * @param {boolean} [opts.dryRun]
 * @param {object|object[]} [opts.scope]  one scope object, or several (rows union)
 * @param {{originX?,originY?,spacingX?}} [opts.layout]
 * @param {boolean} [opts.includeLabels]  decode node labels into the report (slower)
 * @param {number} [opts.itemLimit]  cap on `items` in the report (default 2000)
 */
export async function relayoutDrpNodeGraphs(drpPath, opts = {}) {
  const dryRun = opts.dryRun === undefined ? !opts.outputPath : Boolean(opts.dryRun);
  if (!dryRun && !opts.outputPath) throw new Error('outputPath is required unless dryRun');
  if (!dryRun && path.resolve(opts.outputPath) === path.resolve(drpPath)) {
    throw new Error('refusing to overwrite the source .drp — write to a new outputPath');
  }
  const scopes = asList(opts.scope).length ? asList(opts.scope) : [{}];
  const layoutOpts = {
    originX: opts.layout?.originX,
    originY: opts.layout?.originY,
    spacingX: opts.layout?.spacingX,
    spacingY: opts.layout?.spacingY,
    layout: opts.layout?.mode,
  };
  const wantLabels = Boolean(opts.includeLabels) || scopes.some((s) => asList(s.nodeLabels).length);

  const { zip, entries } = await loadZip(drpPath);
  const index = indexNodeGraphs(entries);
  const lay = layout();

  const items = [];
  const skipped = [];
  const changes = []; // {entry, versionId, bodyHex(new)}
  const totals = { graphs: index.graphs.length, matched: 0, relaid: 0, alreadyClean: 0, skipped: 0, empty: 0, excluded: 0 };
  const byKind = {};
  const bump = (kind, key) => {
    byKind[kind] = byKind[kind] || { graphs: 0, matched: 0, relaid: 0, alreadyClean: 0, skipped: 0, empty: 0 };
    byKind[kind][key] += 1;
  };
  const versionNames = new Set();
  let stacked = 0;
  const nodeCountByTimeline = {};

  for (const g of index.graphs) {
    bump(g.kind, 'graphs');
    versionNames.add(g.versionName);
    if (g.kind === 'local') {
      const t = (nodeCountByTimeline[g.timeline] = nodeCountByTimeline[g.timeline] || { graphs: 0, graded: 0, tracks: 0, clips: new Set() });
      t.graphs += 1;
      if (g.hasCorrection) t.graded += 1;
      t.tracks = Math.max(t.tracks, g.track);
      t.clips.add(g.clipId);
    }
    const decoded = await decodeGraph(g, { labels: wantLabels, layoutOpts });
    if (decoded.error) {
      // Undecodable bodies are reported, never rewritten — and never fail the sweep.
      skipped.push({ key: g.versionId, kind: g.kind, label: g.label, reason: decoded.error });
      totals.skipped += 1;
      bump(g.kind, 'skipped');
      continue;
    }
    if (decoded.nodeCount === 0) {
      // Resolve's default body carries NO node message (the node is created lazily
      // in the UI) — nothing to lay out, and not an error.
      totals.empty += 1;
      bump(g.kind, 'empty');
      continue;
    }
    const inScope = scopes.some((s) => graphInScope(g, s, decoded));
    if (!inScope) {
      totals.excluded += 1;
      continue;
    }
    totals.matched += 1;
    bump(g.kind, 'matched');
    if ((decoded.meta.lanes || 1) > 1) stacked += 1;
    const target = decoded.planned;
    const clean = isClean(decoded.positions, target);
    const item = {
      key: g.versionId,
      kind: g.kind,
      label: g.label,
      timeline: g.timeline ?? null,
      track: g.track ?? null,
      clipIndex: g.clipIndex ?? null,
      clipId: g.clipId ?? g.mediaPoolClipId ?? null,
      clipName: g.clipName ?? null,
      start: g.start ?? null,
      end: g.end ?? null,
      mediaName: g.mediaName ?? null,
      group: g.group ?? null,
      versionId: g.versionId,
      versionName: g.versionName,
      active: g.active,
      hasCorrection: g.hasCorrection,
      nodes: decoded.nodeCount,
      layout: decoded.meta,
      ...(decoded.labels ? { nodeLabels: decoded.labels } : {}),
      before: decoded.positions,
      after: target,
      status: clean ? 'clean' : dryRun ? 'would-relayout' : 'relaid',
    };
    if (clean) {
      totals.alreadyClean += 1;
      bump(g.kind, 'alreadyClean');
    } else {
      totals.relaid += 1;
      bump(g.kind, 'relaid');
      if (!dryRun) {
        const r = await lay.relayoutBody(Buffer.from(g.bodyHex, 'hex'), layoutOpts);
        if (r.nodeCount !== decoded.nodeCount) throw new Error(`node count changed while relaying ${g.label}: ${decoded.nodeCount} → ${r.nodeCount}`);
        changes.push({ entry: g.entry, versionId: g.versionId, bodyHex: r.body.toString('hex'), positions: r.positions });
      }
    }
    items.push(item);
  }

  const context = {
    project: index.projectName,
    timelines: index.timelines.map((t) => ({
      name: t.name,
      sequenceId: t.sequenceId,
      tracks: nodeCountByTimeline[t.name]?.tracks || 0,
      clips: nodeCountByTimeline[t.name]?.clips.size || 0,
      graphs: nodeCountByTimeline[t.name]?.graphs || 0,
      graded: nodeCountByTimeline[t.name]?.graded || 0,
    })),
    groups: index.groups.map((g) => ({
      name: g.name,
      clips: new Set(index.graphs.filter((x) => x.kind === 'local' && x.group === g.name).map((x) => x.clipId)).size,
    })),
    versionNames: [...versionNames].sort(),
    kinds: Object.fromEntries(GRAPH_KINDS.map((k) => [k, byKind[k]?.graphs || 0])),
    multiVersionClips: new Set(index.graphs.filter((x) => x.kind === 'local' && x.versionCount > 1).map((x) => x.clipId)).size,
    stackedGraphs: stacked,
  };

  const limit = opts.itemLimit ?? 2000;
  const report = {
    dryRun,
    drpPath,
    outputPath: dryRun ? null : opts.outputPath,
    layout: {
      originX: layoutOpts.originX ?? 290,
      originY: layoutOpts.originY ?? 428,
      spacingX: layoutOpts.spacingX ?? 495,
      spacingY: layoutOpts.spacingY ?? 178,
      mode: layoutOpts.layout ?? 'topology',
    },
    scope: scopes,
    totals: {
      graphs: totals.graphs,
      matched: totals.matched,
      [dryRun ? 'wouldRelayout' : 'relaid']: totals.relaid,
      alreadyClean: totals.alreadyClean,
      skipped: totals.skipped,
      empty: totals.empty,
      excluded: totals.excluded,
    },
    byKind,
    context,
    items: items.slice(0, limit),
    itemsTruncated: Math.max(0, items.length - limit),
    skipped,
  };
  if (dryRun) return report;

  // ── write: replace each changed version's <Body> by its DbId ───────────────
  const touched = new Map(); // entry → xml
  for (const ch of changes) {
    const xml = touched.get(ch.entry) ?? entries[ch.entry];
    const re = new RegExp(`(<ListMgt::LmVersion DbId="${escapeRegex(ch.versionId)}">[\\s\\S]*?<Body>)[0-9a-fA-F\\s]*(</Body>[\\s\\S]*?</ListMgt::LmVersion>)`);
    if (!re.test(xml)) throw new Error(`version ${ch.versionId} not found in ${ch.entry} at write time`);
    touched.set(ch.entry, xml.replace(re, `$1${ch.bodyHex}$2`));
  }
  for (const [entry, xml] of touched) zip.file(entry, xml);
  const outBuf = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE', compressionOptions: { level: 6 } });
  await fs.mkdir(path.dirname(opts.outputPath), { recursive: true });
  await fs.writeFile(opts.outputPath, outBuf);

  // ── read-back verify: the file on disk, re-indexed from scratch ───────────
  const back = await loadZip(opts.outputPath);
  const backIndex = indexNodeGraphs(back.entries);
  const byId = new Map(backIndex.graphs.map((g) => [g.versionId, g]));
  const problems = [];
  if (backIndex.graphs.length !== index.graphs.length) {
    problems.push(`graph count ${index.graphs.length} → ${backIndex.graphs.length}`);
  }
  const changedIds = new Set(changes.map((c) => c.versionId));
  for (const g of index.graphs) {
    const b = byId.get(g.versionId);
    if (!b) {
      problems.push(`${g.label}: missing after write`);
      continue;
    }
    if (b.hasCorrection !== g.hasCorrection) problems.push(`${g.label}: HasCorrection changed`);
    if (!changedIds.has(g.versionId)) {
      if (b.bodyHex !== g.bodyHex) problems.push(`${g.label}: untouched body changed`);
      continue;
    }
    const ch = changes.find((c) => c.versionId === g.versionId);
    let pos;
    try {
      pos = await lay.readNodePositions(Buffer.from(b.bodyHex, 'hex'));
    } catch (e) {
      problems.push(`${g.label}: undecodable after write (${e.message})`);
      continue;
    }
    if (JSON.stringify(pos) !== JSON.stringify(ch.positions)) problems.push(`${g.label}: positions ${JSON.stringify(pos)} ≠ ${JSON.stringify(ch.positions)}`);
  }
  report.verify = { ok: problems.length === 0, checked: index.graphs.length, rewritten: changes.length, bytes: outBuf.length, problems: problems.slice(0, 50) };
  if (problems.length) {
    // Never hand back a file that failed its own read-back.
    await fs.rm(opts.outputPath, { force: true });
    throw new Error(`relayout read-back verify failed (${problems.length}): ${problems.slice(0, 3).join(' | ')} — output deleted`);
  }
  return report;
}
