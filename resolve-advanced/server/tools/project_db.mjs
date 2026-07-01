/**
 * project_db tool — "beyond-the-API" LIVE Project.db patches (Tier-1 plain columns).
 *
 * Closes documented scripting-API gaps by direct SQLite UPDATE. Every write is gated:
 * project must be CLOSED + auto-backup + schema guard + read-back verify (db-patch.mjs).
 * Needs optional `better-sqlite3`. See the design notes design notes.
 *
 * list_folders — read media-pool folders (name + color + lock)
 * rename_folder — Sm2MpFolder.Name (API has NO RenameSubFolder)
 * set_folder_color — Sm2MpFolder.ColorTag (enum, e.g. FOLDER_COLOR_BLUE)
 * list_clips — read media-pool clips (name + mark in/out)
 * set_clip_marks — Sm2MpMedia.MarkIn/MarkOut (set clip in/out points)
 * relayout_node_graphs — rewrite node x/y in every graded ListMgt::LmVersion Body
 *   (whole-project "Cleanup Node Graph"; the UI command has NO scripting API)
 */

import { z } from 'zod';
import { createRequire } from 'node:module';
import { resolveDbPath, openGuarded, backup, requireClosed } from '../db-patch.mjs';

const require = createRequire(import.meta.url);

const dbTarget = {
  projectDb: z.string().optional().describe('Path to Project.db (else resolved from projectName)'),
  projectName: z.string().optional().describe('Project name — auto-found under the Resolve Disk Database'),
};
const confirm = z.boolean().optional().describe('Required true — project must be CLOSED in Resolve before patching');

const listFoldersSchema = z.object({ ...dbTarget });
const renameFolderSchema = z.object({ ...dbTarget, folder: z.string().describe('Current folder name'), newName: z.string(), iConfirmProjectClosed: confirm });
const folderColorSchema = z.object({
  ...dbTarget,
  folder: z.string(),
  color: z.string().describe('e.g. FOLDER_COLOR_BLUE / FOLDER_COLOR_NONE'),
  iConfirmProjectClosed: confirm,
});
const listClipsSchema = z.object({ ...dbTarget });
const clipMarksSchema = z.object({
  ...dbTarget,
  clip: z.string().describe('Media-pool clip name'),
  markIn: z.number().int().optional(),
  markOut: z.number().int().optional(),
  iConfirmProjectClosed: confirm,
});

const relayoutSchema = z.object({
  ...dbTarget,
  dryRun: z.boolean().optional().describe('Report what would change without writing'),
  originX: z.number().int().optional().describe('Clean-row start x (default 290 — matches native Cleanup Node Graph)'),
  originY: z.number().int().optional().describe('Clean-row y (default 428)'),
  spacingX: z.number().int().optional().describe('Clean-row x spacing (default 495)'),
  iConfirmProjectClosed: confirm,
});

function selectOne(db, table, col, value) {
  const rows = db.prepare(`SELECT rowid AS rid, Name FROM ${table} WHERE Name = ?`).all(value);
  if (!rows.length) throw new Error(`no ${table} named "${value}"`);
  if (rows.length > 1) throw new Error(`multiple ${table} named "${value}" (${rows.length}) — ambiguous`);
  return rows[0];
}

export const projectDbTool = {
  name: 'project_db',
  description:
    'Beyond-the-API live Project.db patches (plain columns) — closes gaps the scripting API cannot. Project must be CLOSED (auto-backup + schema guard + verify). Actions: list_folders, rename_folder (no RenameSubFolder API), set_folder_color, list_clips, set_clip_marks, relayout_node_graphs (whole-project Cleanup Node Graph — rewrites node x/y in every graded version Body; grade content untouched; REQUIRES full Resolve quit+relaunch after patching, it caches open projects in memory). Needs optional better-sqlite3.',
  async handler({ action, args }) {
    if (action === 'list_folders') {
      const p = listFoldersSchema.parse(args);
      const db = openGuarded(resolveDbPath(p), { table: 'Sm2MpFolder', column: 'Name' });
      try {
        return { folders: db.prepare('SELECT Name, ColorTag FROM Sm2MpFolder ORDER BY Name').all() };
      } finally {
        db.close();
      }
    }
    if (action === 'rename_folder') {
      const p = renameFolderSchema.parse(args);
      requireClosed(p);
      const dbPath = resolveDbPath(p);
      const bak = backup(dbPath);
      const db = openGuarded(dbPath, { writable: true, table: 'Sm2MpFolder', column: 'Name' });
      try {
        const row = selectOne(db, 'Sm2MpFolder', 'Name', p.folder);
        db.prepare('UPDATE Sm2MpFolder SET Name = ? WHERE rowid = ?').run(p.newName, row.rid);
        const after = db.prepare('SELECT Name FROM Sm2MpFolder WHERE rowid = ?').get(row.rid);
        return { backup: bak, from: p.folder, to: p.newName, verified: after.Name === p.newName };
      } finally {
        db.close();
      }
    }
    if (action === 'set_folder_color') {
      const p = folderColorSchema.parse(args);
      requireClosed(p);
      const dbPath = resolveDbPath(p);
      const bak = backup(dbPath);
      const db = openGuarded(dbPath, { writable: true, table: 'Sm2MpFolder', column: 'ColorTag' });
      try {
        const row = selectOne(db, 'Sm2MpFolder', 'Name', p.folder);
        db.prepare('UPDATE Sm2MpFolder SET ColorTag = ? WHERE rowid = ?').run(p.color, row.rid);
        const after = db.prepare('SELECT ColorTag FROM Sm2MpFolder WHERE rowid = ?').get(row.rid);
        return { backup: bak, folder: p.folder, color: p.color, verified: after.ColorTag === p.color };
      } finally {
        db.close();
      }
    }
    if (action === 'list_clips') {
      const p = listClipsSchema.parse(args);
      const db = openGuarded(resolveDbPath(p), { table: 'Sm2MpMedia', column: 'MarkIn' });
      try {
        return { clips: db.prepare('SELECT Name, MarkIn, MarkOut FROM Sm2MpMedia ORDER BY Name LIMIT 500').all() };
      } finally {
        db.close();
      }
    }
    if (action === 'set_clip_marks') {
      const p = clipMarksSchema.parse(args);
      requireClosed(p);
      if (p.markIn == null && p.markOut == null) throw new Error('provide markIn and/or markOut');
      const dbPath = resolveDbPath(p);
      const bak = backup(dbPath);
      const db = openGuarded(dbPath, { writable: true, table: 'Sm2MpMedia', column: 'MarkIn' });
      try {
        const row = selectOne(db, 'Sm2MpMedia', 'Name', p.clip);
        if (p.markIn != null) db.prepare('UPDATE Sm2MpMedia SET MarkIn = ? WHERE rowid = ?').run(p.markIn, row.rid);
        if (p.markOut != null) db.prepare('UPDATE Sm2MpMedia SET MarkOut = ? WHERE rowid = ?').run(p.markOut, row.rid);
        const after = db.prepare('SELECT MarkIn, MarkOut FROM Sm2MpMedia WHERE rowid = ?').get(row.rid);
        return { backup: bak, clip: p.clip, markIn: after.MarkIn, markOut: after.MarkOut, verified: true };
      } finally {
        db.close();
      }
    }
    if (action === 'relayout_node_graphs') {
      const p = relayoutSchema.parse(args);
      const layout = require('../../vendor/drx-codec/node-layout.js');
      const layoutOpts = { originX: p.originX, originY: p.originY, spacingX: p.spacingX };
      const dbPath = resolveDbPath(p);
      const write = !p.dryRun;
      if (write) requireClosed(p);
      const bak = write ? backup(dbPath) : null;
      const db = openGuarded(dbPath, { writable: write, table: 'ListMgt::LmVersion', column: 'HasCorrection' });
      try {
        const rows = db
          .prepare('SELECT "ListMgt::LmVersion_id" AS id, Body FROM "ListMgt::LmVersion" WHERE HasCorrection = 1 AND Body IS NOT NULL')
          .all();
        const update = write ? db.prepare('UPDATE "ListMgt::LmVersion" SET Body = ? WHERE "ListMgt::LmVersion_id" = ?') : null;
        let relaid = 0;
        let alreadyClean = 0;
        const changed = [];
        const skipped = [];
        for (const row of rows) {
          let r;
          try {
            r = await layout.relayoutBody(Buffer.from(row.Body), layoutOpts);
          } catch (e) {
            // Not every HasCorrection row is a rewritable graph (e.g. odd still bodies) —
            // skip and REPORT rather than corrupting or failing the whole sweep.
            skipped.push({ id: row.id, reason: e.message });
            continue;
          }
          const before = await layout.readNodePositions(Buffer.from(row.Body));
          // ≤2px tolerance: native Cleanup rounds spacing slightly differently
          // (786 vs our even 785) — don't churn rows that are already clean.
          const clean =
            before.length === r.positions.length &&
            before.every(([bx, by], i) => bx != null && Math.abs(bx - r.positions[i][0]) <= 2 && Math.abs(by - r.positions[i][1]) <= 2);
          if (clean) {
            alreadyClean++;
            continue;
          }
          if (write) {
            update.run(r.body, row.id);
            // Read-back verify: the stored blob must decode to the new positions.
            const back = db.prepare('SELECT Body FROM "ListMgt::LmVersion" WHERE "ListMgt::LmVersion_id" = ?').get(row.id);
            const verify = await layout.readNodePositions(Buffer.from(back.Body));
            if (JSON.stringify(verify) !== JSON.stringify(r.positions)) {
              throw new Error(`read-back verify failed on row ${row.id} — restore from backup ${bak}`);
            }
          }
          relaid++;
          if (changed.length < 50) changed.push({ id: row.id, nodes: r.nodeCount, before, after: r.positions });
        }
        return {
          dryRun: !write,
          backup: bak,
          gradedVersions: rows.length,
          [write ? 'relaidOut' : 'wouldRelayout']: relaid,
          alreadyClean,
          skipped,
          changed,
          note: write
            ? 'Resolve caches open projects IN MEMORY: fully QUIT Resolve and relaunch before reopening this project, or the patched layout will not be visible (and an oversave could revert it).'
            : 'Dry run — nothing written. Re-run with dryRun:false + iConfirmProjectClosed:true (project CLOSED in Resolve).',
        };
      } finally {
        db.close();
      }
    }
    throw new Error(`Unknown project_db action: ${action}`);
  },
};
