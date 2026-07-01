/**
 * Sequence lineage store (Phase 1) — content-hashed parsed-geometry snapshots of a
 * sequence as it evolves (OG editorial XML → conform XML → live versions), so any two
 * versions can be diffed and a prior one rolled back to. SQLite sidecar (mirrors the
 * offline-ref / reverse-clip DB pattern). Frame-QC verdicts (later phases) attach to a
 * snapshot's cuts in `qc_verdicts`.
 *
 * Phase 1: schema + ingest of an XMEML (editorial or conform) → snapshot + per-cut
 * geometry (oracle source frame + corrected scale when derivable), with per-cut and
 * per-snapshot content hashes for dedup + change detection.
 */

import fs from 'node:fs';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const V = '../vendor/conform-qc';
const parse = require(`${V}/parse/index.js`);
const resolveTarget = require(`${V}/oracle/resolve.js`);

const TICKS_PER_SEC = 254016000000;

function loadSqlite() {
  try {
    return require('better-sqlite3');
  } catch {
    throw new Error("lineage store needs the optional native dep 'better-sqlite3'. Install: npm i better-sqlite3");
  }
}

const SCHEMA = `
CREATE TABLE IF NOT EXISTS snapshots (snapshot_id TEXT PRIMARY KEY, reel TEXT, kind TEXT, source_ref TEXT, label TEXT,
 parent_id TEXT, content_hash TEXT, seq_w INTEGER, seq_h INTEGER, fps REAL,
 cut_count INTEGER, created_at TEXT, provenance TEXT);
CREATE TABLE IF NOT EXISTS cuts (snapshot_id TEXT, cut_index INTEGER, record_start INTEGER, record_end INTEGER,
 source_basename TEXT, source_path TEXT, xml_in INTEGER, xml_out INTEGER,
 ppro_ticks_in INTEGER, oracle_source_frame INTEGER, is_subclip INTEGER,
 subclip_startoffset INTEGER, subclip_endoffset INTEGER, reverse INTEGER,
 scale_corrected REAL, pan_h REAL, pan_v REAL, rotation REAL, transition TEXT,
 cut_hash TEXT, PRIMARY KEY (snapshot_id, cut_index));
CREATE TABLE IF NOT EXISTS qc_verdicts (snapshot_id TEXT, cut_index INTEGER, reference_ref TEXT, reference_frame INTEGER,
 verdict TEXT, category TEXT, structure REAL, psnr REAL, dx INTEGER, dy INTEGER,
 scale_residual REAL, ran_at TEXT, PRIMARY KEY (snapshot_id, cut_index, reference_ref));
CREATE INDEX IF NOT EXISTS idx_snapshots_reel ON snapshots(reel);
CREATE INDEX IF NOT EXISTS idx_snapshots_hash ON snapshots(content_hash);
`;

export function openStore(dbPath) {
  const Database = loadSqlite();
  const db = new Database(dbPath);
  db.pragma('journal_mode = WAL');
  db.exec(SCHEMA);
  return db;
}

const sha1 = (s) => crypto.createHash('sha1').update(s).digest('hex');

// Geometry fields that define a cut's identity (drive cut_hash + diff).
const CUT_GEOMETRY = [
  'record_start',
  'record_end',
  'source_basename',
  'xml_in',
  'xml_out',
  'ppro_ticks_in',
  'oracle_source_frame',
  'is_subclip',
  'subclip_startoffset',
  'subclip_endoffset',
  'reverse',
  'scale_corrected',
  'pan_h',
  'pan_v',
  'rotation',
  'transition',
];

function cutHash(cut) {
  return sha1(JSON.stringify(CUT_GEOMETRY.map((k) => cut[k] ?? null)));
}

function buildCuts(xml, mediaFrames) {
  const g = parse.parseGeometry(xml);
  const seqW = g.sequence.width || null;
  const seqH = g.sequence.height || null;
  const fps = g.sequence.fps || 24;
  const ticksPerFrame = TICKS_PER_SEC / fps;
  const cuts = g.clips.map((c, i) => {
    const ctx = { ticksPerFrame, sequenceWidth: seqW, sequenceHeight: seqH, masterFrames: mediaFrames[c.source_basename] };
    let oracleFrame = null;
    let scaleCorrected = null;
    try {
      oracleFrame = resolveTarget.deriveSourceFrame(c, ctx);
    } catch {
      /* reverse w/o frame count, etc. */
    }
    try {
      scaleCorrected = resolveTarget.deriveScaleCorrected(c, ctx);
    } catch {
      /* missing dims */
    }
    const cut = {
      cut_index: i,
      record_start: c.seqstart ?? null,
      record_end: c.seqend ?? null,
      source_basename: c.source_basename ?? null,
      source_path: c.source_path ?? null,
      xml_in: c.xml_in ?? null,
      xml_out: c.xml_out ?? null,
      ppro_ticks_in: c.pproTicksIn ?? null,
      oracle_source_frame: oracleFrame,
      is_subclip: c.is_subclip ? 1 : 0,
      subclip_startoffset: c.subclip_startoffset ?? null,
      subclip_endoffset: c.subclip_endoffset ?? null,
      reverse: c.reverse ? 1 : 0,
      scale_corrected: scaleCorrected != null ? +scaleCorrected.toFixed(5) : null,
      pan_h: c.center ? c.center.h : null,
      pan_v: c.center ? c.center.v : null,
      rotation: c.rotation ?? null,
      transition: null,
    };
    cut.cut_hash = cutHash(cut);
    return cut;
  });
  return { cuts, seqW, seqH, fps, transitions: g.transitions };
}

// Write a built cut list as a snapshot (dedup on (reel, content_hash)). Shared by
// XML and live ingest so OG and live versions land in ONE schema.
function writeSnapshot(dbPath, cuts, meta) {
  const contentHash = sha1(cuts.map((c) => c.cut_hash).join(''));
  const db = openStore(dbPath);
  try {
    const existing = db.prepare('SELECT snapshot_id FROM snapshots WHERE reel IS ? AND content_hash = ?').get(meta.reel ?? null, contentHash);
    if (existing) return { snapshotId: existing.snapshot_id, contentHash, cutCount: cuts.length, deduped: true };
    const snapshotId = sha1(`${meta.reel ?? ''}:${contentHash}:${meta.label ?? ''}:${meta.now ?? ''}`).slice(0, 24);
    const insertSnap = db.prepare(`INSERT INTO snapshots
 (snapshot_id, reel, kind, source_ref, label, parent_id, content_hash, seq_w, seq_h, fps, cut_count, created_at, provenance)
 VALUES (@snapshot_id,@reel,@kind,@source_ref,@label,@parent_id,@content_hash,@seq_w,@seq_h,@fps,@cut_count,@created_at,@provenance)`);
    const insertCut = db.prepare(`INSERT INTO cuts
 (snapshot_id, cut_index, record_start, record_end, source_basename, source_path, xml_in, xml_out, ppro_ticks_in, oracle_source_frame, is_subclip, subclip_startoffset, subclip_endoffset, reverse, scale_corrected, pan_h, pan_v, rotation, transition, cut_hash)
 VALUES (@snapshot_id,@cut_index,@record_start,@record_end,@source_basename,@source_path,@xml_in,@xml_out,@ppro_ticks_in,@oracle_source_frame,@is_subclip,@subclip_startoffset,@subclip_endoffset,@reverse,@scale_corrected,@pan_h,@pan_v,@rotation,@transition,@cut_hash)`);
    db.transaction(() => {
      insertSnap.run({
        snapshot_id: snapshotId,
        reel: meta.reel ?? null,
        kind: meta.kind,
        source_ref: meta.source_ref ?? null,
        label: meta.label ?? null,
        parent_id: meta.parentId ?? null,
        content_hash: contentHash,
        seq_w: meta.seqW ?? null,
        seq_h: meta.seqH ?? null,
        fps: meta.fps ?? null,
        cut_count: cuts.length,
        created_at: meta.now ?? null,
        provenance: meta.provenance ?? null,
      });
      for (const c of cuts) insertCut.run({ snapshot_id: snapshotId, ...c });
    })();
    return { snapshotId, contentHash, cutCount: cuts.length, deduped: false };
  } finally {
    db.close();
  }
}

/**
 * Ingest an XMEML (editorial or conform) into the lineage store.
 * opts: { kind:'editorial_xml'|'conform_xml', label, reel, parentId, provenance,
 * mediaFrames:{basename:frameCount} (optional; enables reverse oracle frames),
 * now (ISO string — no Date.now in this runtime) }
 */
export function ingestXml(dbPath, xmlPath, opts = {}) {
  const xml = fs.readFileSync(xmlPath, 'utf8');
  const { cuts, seqW, seqH, fps } = buildCuts(xml, opts.mediaFrames || {});
  return writeSnapshot(dbPath, cuts, {
    ...opts,
    kind: opts.kind ?? 'conform_xml',
    source_ref: xmlPath,
    seqW,
    seqH,
    fps,
    provenance: opts.provenance ?? 'ingestXml',
  });
}

function loadPg() {
  try {
    return require('pg');
  } catch {
    throw new Error("live ingest Postgres path needs the optional dep 'pg'. Install: npm i pg");
  }
}
const numOrNull = (v) => {
  const n = Number(v);
  return Number.isFinite(n) ? Math.round(n) : null;
};

// Read a live timeline's cuts from the project DB (Sm2Timeline→Sm2TiTrack→Sm2TiItem).
async function readLiveCuts(opts) {
  const SQL = (ph) => `SELECT CAST(i."Start" AS INTEGER) AS rec, i."In" AS inv, LENGTH(i."MediaTimemapBA") AS tmlen, i."MediaFilePath" AS path
 FROM "Sm2TiItem" i JOIN "Sm2TiTrack" tr ON i."Sm2TiTrack_id" = tr."Sm2TiTrack_id"
 JOIN "Sm2Timeline" tl ON tr."Sequence" = tl."Sequence"
 WHERE tl."Sm2Timeline_id" = ${ph} ORDER BY rec`;
  if (opts.postgres) {
    const pg = opts.postgres;
    const client =
      pg.__client ||
      (await (async () => {
        const { Client } = loadPg();
        const c = new Client({
          host: pg.host || pg.IpAddress,
          port: pg.port || 5432,
          user: pg.user || 'postgres',
          password: pg.password != null ? pg.password : process.env.PGPASSWORD,
          database: pg.database || pg.DbName,
        });
        await c.connect();
        return c;
      })());
    try {
      return (await client.query(SQL('$1'), [opts.timelineId])).rows;
    } finally {
      if (!pg.__client) await client.end();
    }
  }
  if (!opts.projectDb) throw new Error('live ingest: provide projectDb (SQLite) or postgres');
  const db = new (loadSqlite())(opts.projectDb, { readonly: true });
  try {
    return db.prepare(SQL('?')).all(opts.timelineId);
  } finally {
    db.close();
  }
}

/**
 * Snapshot a LIVE Resolve timeline into the lineage store (same schema as XML).
 * Reads structural geometry (record, source, stored In, reverse via timemap length) from
 * the project DB. For accurate diffs vs an XML baseline — especially REVERSE clips whose
 * stored In is mirrored — pass API readbacks:
 * opts.sourceFrames:{ recordStart: get_source_start_frame } (preferred for oracle_source_frame)
 * opts.transforms:{ recordStart: {scale_corrected, pan_h, pan_v, rotation} }
 * opts: { lineage scope: projectDb|postgres, timelineId, reel, label, parentId, now, seqW, seqH, fps }
 */
export async function ingestLiveTimeline(dbPath, opts = {}) {
  const raw = await readLiveCuts(opts);
  const sourceFrames = opts.sourceFrames || {};
  const transforms = opts.transforms || {};
  const revThresh = opts.reverseTimemapLen || 100;
  const cuts = raw.map((r, i) => {
    const rec = r.rec;
    const t = transforms[rec] || {};
    const cut = {
      cut_index: i,
      record_start: rec,
      record_end: raw[i + 1] ? raw[i + 1].rec : null,
      source_basename: r.path ? r.path.split('/').pop() : null,
      source_path: r.path || null,
      xml_in: numOrNull(r.inv),
      xml_out: null,
      ppro_ticks_in: null,
      oracle_source_frame: rec in sourceFrames ? sourceFrames[rec] : numOrNull(r.inv),
      is_subclip: null,
      subclip_startoffset: null,
      subclip_endoffset: null,
      reverse: (r.tmlen || 0) > revThresh ? 1 : 0,
      scale_corrected: t.scale_corrected ?? null,
      pan_h: t.pan_h ?? null,
      pan_v: t.pan_v ?? null,
      rotation: t.rotation ?? null,
      transition: null,
    };
    cut.cut_hash = cutHash(cut);
    return cut;
  });
  return writeSnapshot(dbPath, cuts, { ...opts, kind: 'live_timeline', source_ref: opts.timelineId, provenance: opts.provenance ?? 'ingestLiveTimeline' });
}

/** Store a frame-QC verdict for a snapshot's cut (one per reference). */
export function writeVerdict(dbPath, v) {
  const db = openStore(dbPath);
  try {
    db.prepare(
      `INSERT OR REPLACE INTO qc_verdicts
 (snapshot_id, cut_index, reference_ref, reference_frame, verdict, category, structure, psnr, dx, dy, scale_residual, ran_at)
 VALUES (@snapshot_id,@cut_index,@reference_ref,@reference_frame,@verdict,@category,@structure,@psnr,@dx,@dy,@scale_residual,@ran_at)`,
    ).run({ reference_frame: null, structure: null, psnr: null, dx: null, dy: null, scale_residual: null, ran_at: null, ...v });
  } finally {
    db.close();
  }
}

export function getVerdict(dbPath, snapshotId, cutIndex, referenceRef) {
  const db = openStore(dbPath);
  try {
    return db.prepare('SELECT * FROM qc_verdicts WHERE snapshot_id=? AND cut_index=? AND reference_ref=?').get(snapshotId, cutIndex, referenceRef) || null;
  } finally {
    db.close();
  }
}

export function listVerdicts(dbPath, snapshotId, referenceRef) {
  const db = openStore(dbPath);
  try {
    return referenceRef
      ? db.prepare('SELECT * FROM qc_verdicts WHERE snapshot_id=? AND reference_ref=? ORDER BY cut_index').all(snapshotId, referenceRef)
      : db.prepare('SELECT * FROM qc_verdicts WHERE snapshot_id=? ORDER BY cut_index').all(snapshotId);
  } finally {
    db.close();
  }
}

export function listSnapshots(dbPath, { reel } = {}) {
  const db = openStore(dbPath);
  try {
    const rows = reel
      ? db.prepare('SELECT * FROM snapshots WHERE reel = ? ORDER BY created_at, label').all(reel)
      : db.prepare('SELECT * FROM snapshots ORDER BY reel, created_at, label').all();
    return rows;
  } finally {
    db.close();
  }
}

export function getSnapshot(dbPath, snapshotId) {
  const db = openStore(dbPath);
  try {
    const snap = db.prepare('SELECT * FROM snapshots WHERE snapshot_id = ?').get(snapshotId);
    if (!snap) return null;
    const cuts = db.prepare('SELECT * FROM cuts WHERE snapshot_id = ? ORDER BY cut_index').all(snapshotId);
    return { ...snap, cuts };
  } finally {
    db.close();
  }
}

// Canonical fields for DIFF — the derived "what plays + how it's framed", comparable
// ACROSS snapshot kinds (XML vs live). Raw XML-parse inputs (xml_in/out, ppro ticks,
// subclip offsets) are excluded: they're oracle inputs, present only on XML snapshots,
// and would make every XML-vs-live cut read as changed.
const CANONICAL_FIELDS = [
  'record_start',
  'record_end',
  'source_basename',
  'oracle_source_frame',
  'reverse',
  'scale_corrected',
  'pan_h',
  'pan_v',
  'rotation',
  'transition',
];

function fieldDeltas(a, b) {
  const deltas = {};
  for (const k of CANONICAL_FIELDS) {
    if ((a[k] ?? null) !== (b[k] ?? null)) deltas[k] = { from: a[k] ?? null, to: b[k] ?? null };
  }
  return deltas;
}
// Bucket a change for QC routing (which cuts to re-pixel-verify, and why).
function changeKind(deltas) {
  const kinds = [];
  if ('oracle_source_frame' in deltas) kinds.push('source_frame');
  if ('scale_corrected' in deltas || 'pan_h' in deltas || 'pan_v' in deltas || 'rotation' in deltas) kinds.push('transform');
  if ('reverse' in deltas) kinds.push('reverse');
  if ('transition' in deltas) kinds.push('transition');
  if ('source_basename' in deltas) kinds.push('source');
  if ('record_start' in deltas || 'record_end' in deltas) kinds.push('timing');
  return kinds;
}

/**
 * Diff two snapshots → per-cut deltas. Cuts align by record_start; an A-only vs B-only
 * pair sharing (source_basename, xml_in) is reported as MOVED. The `changed` list (with
 * its `kinds`) is the incremental frame-QC worklist — only these cuts need re-comparing.
 */
export function diffSnapshots(dbPath, aId, bId) {
  const A = getSnapshot(dbPath, aId);
  const B = getSnapshot(dbPath, bId);
  if (!A) throw new Error(`no snapshot ${aId}`);
  if (!B) throw new Error(`no snapshot ${bId}`);
  const byRec = (cuts) => {
    const m = new Map();
    for (const c of cuts) {
      const k = c.record_start;
      (m.get(k) || m.set(k, []).get(k)).push(c);
    }
    return m;
  };
  const aMap = byRec(A.cuts);
  const bMap = byRec(B.cuts);
  const changed = [];
  const unchanged = [];
  const removed = [];
  const added = [];
  const seenB = new Set();
  for (const [rec, aCuts] of aMap) {
    const bCuts = bMap.get(rec) || [];
    aCuts.forEach((a, i) => {
      const b = bCuts[i];
      if (!b) {
        removed.push(a);
        return;
      }
      seenB.add(`${rec}#${i}`);
      const deltas = fieldDeltas(a, b); // canonical — robust across XML/live kinds
      if (Object.keys(deltas).length === 0) {
        unchanged.push(rec);
        return;
      }
      changed.push({ record_start: rec, cut_index: b.cut_index, kinds: changeKind(deltas), deltas });
    });
  }
  for (const [rec, bCuts] of bMap)
    bCuts.forEach((b, i) => {
      if (!seenB.has(`${rec}#${i}`)) added.push(b);
    });
  // pair removed↔added on (source_basename, xml_in) → moved
  const moved = [];
  for (let r = removed.length - 1; r >= 0; r--) {
    const a = removed[r];
    const ai = added.findIndex((b) => b.source_basename === a.source_basename && b.xml_in === a.xml_in);
    if (ai >= 0) {
      moved.push({ source_basename: a.source_basename, from: a.record_start, to: added[ai].record_start });
      removed.splice(r, 1);
      added.splice(ai, 1);
    }
  }
  return {
    a: { id: aId, label: A.label, cutCount: A.cut_count },
    b: { id: bId, label: B.label, cutCount: B.cut_count },
    identical: A.content_hash === B.content_hash,
    summary: { unchanged: unchanged.length, changed: changed.length, added: added.length, removed: removed.length, moved: moved.length },
    changed,
    added,
    removed,
    moved,
  };
}

/**
 * Rollback plan: how to get the CURRENT state (currentId) back to a TARGET snapshot
 * (targetId — a known-good prior version or the OG editorial intent). It's the diff plus
 * the target's per-cut values + the suggested tool per changed cut. The agent executes
 * (DB-patch / API) — Node can't drive Resolve. scale_corrected is a PERCENT (ZoomX = /100).
 */
export function rollbackPlan(dbPath, currentId, targetId) {
  const d = diffSnapshots(dbPath, currentId, targetId);
  const target = getSnapshot(dbPath, targetId);
  const byRec = new Map(target.cuts.map((c) => [c.record_start, c]));
  const changes = d.changed.map((ch) => {
    const t = byRec.get(ch.record_start) || {};
    const actions = [];
    if (ch.kinds.includes('source_frame') || ch.kinds.includes('reverse')) {
      actions.push({ tool: 'conform.fix_reverse_clip', for: 'source frame / reverse', targetFrame: t.oracle_source_frame, reverse: !!t.reverse });
    }
    if (ch.kinds.includes('transform')) {
      const zoom = t.scale_corrected != null ? +(t.scale_corrected / 100).toFixed(5) : null;
      actions.push({ tool: 'timeline_item.set_transform', set: { ZoomX: zoom, ZoomY: zoom, Pan: t.pan_h, Tilt: t.pan_v, RotationAngle: t.rotation } });
    }
    return {
      record_start: ch.record_start,
      source_basename: t.source_basename,
      kinds: ch.kinds,
      target: {
        oracle_source_frame: t.oracle_source_frame,
        reverse: t.reverse,
        scale_corrected: t.scale_corrected,
        pan_h: t.pan_h,
        pan_v: t.pan_v,
        rotation: t.rotation,
      },
      suggestedActions: actions,
    };
  });
  return { fromSnapshot: currentId, toSnapshot: targetId, changeCount: changes.length, changes, added: d.added, removed: d.removed, moved: d.moved };
}
