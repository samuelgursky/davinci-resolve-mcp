/**
 * node-meta-db — set/clear a graded node's LABEL (F6) + COLOR (F15) directly in a live Project.db,
 * via the surgical grade-Body patcher (no UI, no lossy generator). Node-convention/provenance spec.
 *
 * Mirrors offline-ref-db.mjs: project-CLOSED gate → auto-backup → schema guard → UPDATE → read-back verify.
 * Resolve oversaves an open project, so the project MUST be closed in Resolve before patching.
 *
 * Join (RE'd 2026-06-22): Sm2TiItem.pLmVerTable → "ListMgt::LmVersion"(HasCorrection='1').Body, scoped to a
 * timeline via Sm2TiTrack.Sequence → Sm2Sequence.Sm2Timeline_id → Sm2Timeline.Name. Body is a BLOB.
 */

import { loadSqlite, resolveDbPath, openGuarded, backup as backupDb, requireClosed } from './db-patch.mjs';
import { patchGradeBody, readNodeMeta } from './grade-body-patch.mjs';

const FIND_GRADE_SQL = `
 SELECT v.rowid AS vid, lower(hex(v.Body)) AS body, i.Name AS clip
 FROM Sm2TiItem i
 JOIN Sm2TiTrack t ON i.Sm2TiTrack_id = t.Sm2TiTrack_id
 JOIN Sm2Sequence s ON t.Sequence = s.Sm2Sequence_id
 JOIN Sm2Timeline tl ON s.Sm2Timeline_id = tl.Sm2Timeline_id
 JOIN "ListMgt::LmVersion" v ON v."ListMgt::LmVersionTable_id" = i.pLmVerTable AND v.HasCorrection = '1'
 WHERE tl.Name = ? AND t.Type = 0
 ORDER BY i.Start ASC`;

/**
 * Set/clear a graded node's label/color in a project's timeline.
 * @param {object} opts
 * @param {string} [opts.projectDb] absolute Project.db path (or use projectName)
 * @param {string} [opts.projectName] disk-DB project name (resolved to its Project.db)
 * @param {string} opts.timeline timeline name
 * @param {number} [opts.nodeIndex=0] node to edit
 * @param {string|null} [opts.label] undefined=leave · null=clear · string=set
 * @param {string|null} [opts.color] undefined=leave · null=clear · string=set (e.g. "Blue")
 * @param {boolean} opts.iConfirmProjectClosed REQUIRED true — Resolve oversaves an open project
 * @param {boolean} [opts.backup=true]
 */
export async function setNodeLabelColorInProject(opts) {
  const { timeline, nodeIndex = 0, label, color, backup = true } = opts;
  requireClosed(opts);
  if (label === undefined && color === undefined) throw new Error('nothing to do: provide label and/or color');
  const dbPath = resolveDbPath(opts);
  const bak = backup ? backupDb(dbPath) : null;
  const db = openGuarded(dbPath, { writable: true, table: 'ListMgt::LmVersion', column: 'Body' });
  try {
    const rows = db.prepare(FIND_GRADE_SQL).all(timeline);
    if (!rows.length) throw new Error(`no graded clip (HasCorrection=1) on timeline "${timeline}" — apply a grade first`);
    const target = rows[0];
    const before = readNodeMeta(target.body, nodeIndex);
    const newHex = await patchGradeBody(target.body, nodeIndex, { label, color });
    db.prepare('UPDATE "ListMgt::LmVersion" SET Body = ? WHERE rowid = ?').run(Buffer.from(newHex, 'hex'), target.vid);
    // read-back verify
    const after = db.prepare('SELECT lower(hex(Body)) AS body FROM "ListMgt::LmVersion" WHERE rowid = ?').get(target.vid);
    const meta = readNodeMeta(after.body, nodeIndex);
    const want = (v, got) => (v === undefined ? true : v === null ? got == null : got === v);
    const verified = want(label, meta.label) && want(color, meta.color);
    return { projectDb: dbPath, backup: bak, clip: target.clip, version: target.vid, nodeIndex, before, after: meta, verified };
  } finally {
    db.close();
  }
}

export { loadSqlite };
