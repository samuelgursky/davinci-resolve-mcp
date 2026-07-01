/** node-meta-db — DB-write path for node label/color, tested against a temp Project.db (no live Resolve).
 * Builds the minimal timeline→clip→LmVersion join with a REAL grade Body blob, then exercises the full
 * writer: project-closed gate → schema guard → join → surgical patch → UPDATE → read-back verify. This is
 * the offline proof of step 2's mechanism; the live close→patch→reopen on calibration is separate. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { setNodeLabelColorInProject, loadSqlite } from '../server/node-meta-db.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const HEX = fs.readFileSync(path.join(here, 'fixtures', 'color-warper.drx'), 'utf8').match(/<Body>([0-9a-f]+)<\/Body>/)[1];
let Database;
try {
  Database = loadSqlite();
} catch {
  /* better-sqlite3 absent */
}

function buildDb(p) {
  const db = new Database(p);
  db.exec(`
 CREATE TABLE Sm2Timeline (Sm2Timeline_id INTEGER, Name TEXT);
 CREATE TABLE Sm2Sequence (Sm2Sequence_id INTEGER, Sm2Timeline_id INTEGER);
 CREATE TABLE Sm2TiTrack (Sm2TiTrack_id INTEGER, Sequence INTEGER, Type INTEGER);
 CREATE TABLE Sm2TiItem (Name TEXT, Sm2TiTrack_id INTEGER, Start INTEGER, pLmVerTable INTEGER);
 CREATE TABLE "ListMgt::LmVersion" ("ListMgt::LmVersionTable_id" INTEGER, HasCorrection TEXT, Body BLOB);
 INSERT INTO Sm2Timeline VALUES (1,'T');
 INSERT INTO Sm2Sequence VALUES (10,1);
 INSERT INTO Sm2TiTrack VALUES (100,10,0);
 INSERT INTO Sm2TiItem VALUES ('Clip A',100,0,500);
 INSERT INTO "ListMgt::LmVersion" VALUES (500,'1', X'${HEX}');
 `);
  db.close();
}

test('DB write: set label+color → read-back verifies', { skip: !Database && 'no better-sqlite3' }, async () => {
  const p = path.join(os.tmpdir(), `nmdb-set-${Date.now()}.db`);
  buildDb(p);
  const r = await setNodeLabelColorInProject({ projectDb: p, timeline: 'T', label: 'Balance', color: 'Blue', iConfirmProjectClosed: true, backup: false });
  assert.equal(r.verified, true);
  assert.equal(r.after.label, 'Balance');
  assert.equal(r.after.color, 'Blue');
  assert.equal(r.clip, 'Clip A');
  fs.rmSync(p, { force: true });
});

test('DB write: clear removes label+color', { skip: !Database && 'no better-sqlite3' }, async () => {
  const p = path.join(os.tmpdir(), `nmdb-clr-${Date.now()}.db`);
  buildDb(p);
  await setNodeLabelColorInProject({ projectDb: p, timeline: 'T', label: 'X', color: 'Blue', iConfirmProjectClosed: true, backup: false });
  const r = await setNodeLabelColorInProject({ projectDb: p, timeline: 'T', label: null, color: null, iConfirmProjectClosed: true, backup: false });
  assert.equal(r.verified, true);
  assert.equal(r.after.color, null);
  assert.ok(!r.after.label);
  fs.rmSync(p, { force: true });
});

test('DB write: refuses when project-closed not confirmed', { skip: !Database && 'no better-sqlite3' }, async () => {
  const p = path.join(os.tmpdir(), `nmdb-gate-${Date.now()}.db`);
  buildDb(p);
  await assert.rejects(() => setNodeLabelColorInProject({ projectDb: p, timeline: 'T', color: 'Blue' }), /close the project/i);
  fs.rmSync(p, { force: true });
});
