/**
 * fairlight tool — Fairlight audio BUS ROUTING (the thing the scripting API
 * cannot do). Patches the reverse-engineered FLStudioModelBA blob.
 *
 * Two surfaces:
 * - codec (offline, pure Node): decode/read a FLStudioModelBA blob you already have.
 * - DB path (validated, case-study 007): operate on a live Resolve project SQLite
 * DB. Requires the OPTIONAL native dep `better-sqlite3` — lazy-loaded so the
 * core server never depends on it.
 *
 * NOTE: the offline .drp-ZIP path (extract Sm2Sequence FieldsBlob → patch → re-zip)
 * is the remaining net-new adapter (A0 spike confirmed the surface exists; needs a
 * Fairlight-configured .drp fixture to validate). DB path is wired here meanwhile.
 */

import { z } from 'zod';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const patcher = require('../../vendor/fairlight/index.js');

function openDb(dbPath, writable) {
  let Database;
  try {
    Database = require('better-sqlite3');
  } catch {
    throw new Error("Fairlight DB path needs the optional native dependency 'better-sqlite3'. Install it: npm i better-sqlite3");
  }
  return new Database(dbPath, { readonly: !writable });
}

const readBlobSchema = z.object({ blobHex: z.string().describe('Hex of a FLStudioModelBA blob to decode + read buses from') });
const dbReadSchema = z.object({ dbPath: z.string().describe('Path to the Resolve project SQLite DB') });
const expandSchema = z.object({
  dbPath: z.string(),
  sourceTimeline: z.string(),
  targetTimeline: z.string(),
  targetBuses: z.array(z.object({}).passthrough()).describe('Bus specs: [{ name, format: "stereo"|"5.1"|"7.1"|... }]'),
});

export const fairlightTool = {
  name: 'fairlight',
  description:
    'Fairlight audio bus routing — patches the FLStudioModelBA blob (no scripting API exists for buses). Actions: read_buses_from_blob (offline codec); read_buses_from_db, expand_buses, export_template, import_template, backup, restore (DB path; needs optional better-sqlite3). The .drp-zip offline path is in progress.',
  async handler({ action, args }) {
    if (action === 'read_buses_from_blob') {
      const p = readBlobSchema.parse(args);
      const raw = Buffer.from(p.blobHex, 'hex');
      const data = patcher.decompressFLModel(raw);
      return { buses: patcher.readBusConfig(data) };
    }
    if (action === 'read_buses_from_db') {
      const p = dbReadSchema.parse(args);
      const db = openDb(p.dbPath, false);
      try {
        return patcher.readFromDatabase(db);
      } finally {
        db.close();
      }
    }
    if (action === 'expand_buses') {
      const p = expandSchema.parse(args);
      const db = openDb(p.dbPath, true);
      try {
        return patcher.applyBusExpansion(db, p.sourceTimeline, p.targetTimeline, p.targetBuses);
      } finally {
        db.close();
      }
    }
    if (action === 'export_template') {
      const p = dbReadSchema.parse(args);
      const db = openDb(p.dbPath, false);
      try {
        return patcher.exportTemplate(db);
      } finally {
        db.close();
      }
    }
    if (action === 'import_template') {
      const p = z.object({ dbPath: z.string(), template: z.object({}).passthrough() }).parse(args);
      const db = openDb(p.dbPath, true);
      try {
        return patcher.importTemplate(db, p.template);
      } finally {
        db.close();
      }
    }
    if (action === 'backup') {
      const p = z.object({ dbPath: z.string(), timeline: z.string() }).parse(args);
      const db = openDb(p.dbPath, false);
      try {
        return { backupPath: patcher.backupFieldsBlob(db, p.timeline) };
      } finally {
        db.close();
      }
    }
    if (action === 'restore') {
      const p = z.object({ dbPath: z.string(), backupPath: z.string(), timeline: z.string() }).parse(args);
      const db = openDb(p.dbPath, true);
      try {
        return patcher.restoreFieldsBlob(db, p.backupPath, p.timeline);
      } finally {
        db.close();
      }
    }
    throw new Error(`Unknown fairlight action: ${action}`);
  },
};
