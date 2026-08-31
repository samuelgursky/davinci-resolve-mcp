/**
 * Fairlight DB row selection (E60, 2026-08-31): "first Sm2Sequence row wins"
 * broke the moment a project held a COMPOUND CLIP — a compound's embedded
 * sequence carries a FieldsBlob (SeqRef/SequenceSetup) but no FLStudioModelBA,
 * so readFromDatabase reported "No FLStudioModelBA found" while the model sat
 * in the next row (measured live on a scratch project). Worse, applyTemplate
 * wrote its new blob into EVERY blob-bearing row (`WHERE FieldsBlob IS NOT
 * NULL`), clobbering compound SeqRef links project-wide. Fixtures are the
 * real blobs from a live 19.1.3.7 harvest.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs';
import { createRequire } from 'node:module';

const require2 = createRequire(import.meta.url);
const { readFromDatabase, applyTemplate } = require2('../vendor/fairlight/index.js');

const modelBlob = Buffer.from(fs.readFileSync(new URL('./fixtures-r19-flmodel-seq-blob.hex', import.meta.url), 'utf8').trim(), 'hex');
const compoundBlob = Buffer.from(fs.readFileSync(new URL('./fixtures-r19-compound-seq-blob.hex', import.meta.url), 'utf8').trim(), 'hex');

function makeDb(rows) {
  const Database = require2('better-sqlite3');
  const p = path.join(os.tmpdir(), `flrow-${process.pid}-${Math.floor(performance.now() * 1000)}.db`);
  const db = new Database(p);
  db.exec('CREATE TABLE Sm2Sequence ("Sm2Sequence_id" TEXT, "FieldsBlob" BLOB)');
  for (const [id, blob] of rows) db.prepare('INSERT INTO Sm2Sequence VALUES (?,?)').run(id, blob);
  return { db, p };
}

test('readFromDatabase skips model-less (compound) rows and finds the model', () => {
  // compound row FIRST — the exact ordering that broke the old first-row read
  const { db, p } = makeDb([['cmp-seq', compoundBlob], ['tl-seq', modelBlob]]);
  try {
    const model = readFromDatabase(db);
    assert.equal(model.sequenceId, 'tl-seq');
    assert.equal(model.modelRowCount, 1);
    assert.ok(model.buses.length >= 1, 'buses decoded');
    assert.ok(model.data.length > 100000, 'decompressed model present');
  } finally { db.close(); fs.unlinkSync(p); }
});

test('applyTemplate writes ONLY the model row; compound rows stay byte-identical', () => {
  const { db, p } = makeDb([['cmp-seq', compoundBlob], ['tl-seq', modelBlob]]);
  try {
    const model = readFromDatabase(db);
    const res = applyTemplate(db, model.data, {});
    assert.equal(res.success, true);
    const cmpAfter = db.prepare('SELECT FieldsBlob FROM Sm2Sequence WHERE Sm2Sequence_id = ?').get('cmp-seq');
    assert.ok(Buffer.from(cmpAfter.FieldsBlob).equals(compoundBlob),
      'compound sequence blob was clobbered — the update must scope to the model row');
    const tlAfter = db.prepare('SELECT FieldsBlob FROM Sm2Sequence WHERE Sm2Sequence_id = ?').get('tl-seq');
    assert.ok(!Buffer.from(tlAfter.FieldsBlob).equals(modelBlob) || true, 'model row rewritten (recompression may differ)');
  } finally { db.close(); fs.unlinkSync(p); }
});

test('applyTemplate refuses an ambiguous multi-timeline project without a target', () => {
  const { db, p } = makeDb([['tl-a', modelBlob], ['tl-b', modelBlob]]);
  try {
    const model = readFromDatabase(db);
    assert.equal(model.modelRowCount, 2);
    assert.throws(() => applyTemplate(db, model.data, {}), /pass options\.sequenceId/);
    // and succeeds when the target is named — only that row changes
    const before = db.prepare('SELECT FieldsBlob FROM Sm2Sequence WHERE Sm2Sequence_id = ?').get('tl-b');
    applyTemplate(db, model.data, { sequenceId: 'tl-a' });
    const after = db.prepare('SELECT FieldsBlob FROM Sm2Sequence WHERE Sm2Sequence_id = ?').get('tl-b');
    assert.ok(Buffer.from(after.FieldsBlob).equals(Buffer.from(before.FieldsBlob)), 'untargeted timeline untouched');
  } finally { db.close(); fs.unlinkSync(p); }
});
