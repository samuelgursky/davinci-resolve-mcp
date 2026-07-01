/** Node-graph LAYOUT relayout — the programmatic "Cleanup Node Graph" (2026-07-02).
 *
 * Resolve's Cleanup Node Graph is UI-only (no scripting API). A before/after Project.db
 * diff proved it rewrites ONLY the F4(x)/F5(y) varints of each F7 node message in the
 * clip's active ListMgt::LmVersion Body — its clean layout is an evenly spaced row
 * (measured x 290/786/1280 at y 428 for 3 nodes). Direct injection of rewritten
 * positions was live-verified: the patched Body renders in Resolve with the grade
 * intact (full app quit+relaunch required — Resolve caches open projects in memory).
 *
 * Two productized paths locked here:
 *  • drx.relayout — lossless single-.drx rewrite. Live recipe: grab → relayout →
 *    reset_all_grades → ApplyGradeFromDRX (the reset is required: a same-structure
 *    apply keeps the existing layout — Resolve matches nodes by id and ignores the
 *    .drx positions; see api_truth "ApplyGradeFromDRX (node layout preserved)")
 *  • project_db.relayout_node_graphs — closed-project bulk sweep over every graded
 *    version row (dry-run, backup, read-back verify, ≤2px already-clean tolerance)
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { drxTool } from '../server/tools/drx.mjs';
import { projectDbTool } from '../server/tools/project_db.mjs';

const require = createRequire(import.meta.url);
const layout = require('../vendor/drx-codec/node-layout.js');

const call = (action, args) => drxTool.handler({ action, args });

/** A 3-node scattered grade to relayout (distinct params so losslessness is checkable). */
async function scatteredDrx() {
  const g = await call('merge', {
    baseContent: (await call('generate', { gradeParams: { saturation: 60, label: 'Node A' } })).content,
    newNodes: [
      { label: 'Node B', params: { contrast: 1.2 } },
      { label: 'Node C', params: { hueRotate: 0.1 } },
    ],
  });
  return g.content || g.drxContent;
}

const bodyHex = (xml) => xml.match(/<Body>([0-9a-fA-F]+)<\/Body>/)[1];

test('cleanRowPositions matches the measured native Cleanup layout', () => {
  assert.deepEqual(layout.cleanRowPositions(3), [
    [290, 428],
    [785, 428], // native wrote 786 — even spacing, 1px rounding difference
    [1280, 428],
  ]);
  assert.deepEqual(layout.cleanRowPositions(2, { originX: 100, originY: 50, spacingX: 200 }), [
    [100, 50],
    [300, 50],
  ]);
});

test('relayoutBody rewrites positions and preserves the grade byte-for-byte in params', async () => {
  const xml = await scatteredDrx();
  const body = Buffer.from(bodyHex(xml), 'hex');
  const r = await layout.relayoutBody(body, { positions: [[500, 300], [770, 40], [1040, 460]] });
  assert.equal(r.nodeCount, 3);
  assert.deepEqual(await layout.readNodePositions(r.body), [
    [500, 300],
    [770, 40],
    [1040, 460],
  ]);
  // Lossless outside layout: decoded node params identical before/after.
  const parse = (hex) =>
    call('parse', {
      content: `<?xml version="1.0" encoding="UTF-8"?>\n<Resolve_Color_Exchange><Label>t</Label><Width>1920</Width><Height>1080</Height><Body>${hex}</Body></Resolve_Color_Exchange>`,
    });
  const a = await parse(bodyHex(xml));
  const b = await parse(r.body.toString('hex'));
  assert.deepEqual(
    b.nodes.map((n) => n.params),
    a.nodes.map((n) => n.params),
  );
  assert.deepEqual(
    b.nodes.map((n) => n.label),
    a.nodes.map((n) => n.label),
  );
});

test('relayoutBody guards: bad magic, zero-size positions list, non-integer positions', async () => {
  await assert.rejects(() => layout.relayoutBody(Buffer.from([0x00, 0x01])), /0x81 magic/);
  const body = Buffer.from(bodyHex(await scatteredDrx()), 'hex');
  await assert.rejects(() => layout.relayoutBody(body, { positions: [[1, 1]] }), /positions has 1/);
  await assert.rejects(() => layout.relayoutBody(body, { positions: [[1.5, 1], [2, 2], [3, 3]] }), /non-negative integers/);
});

test('drx.relayout: clean-row default, original envelope preserved, node-count guard', async () => {
  const xml = await scatteredDrx();
  const scattered = await call('relayout', { content: xml, positions: [[500, 300], [770, 40], [1040, 460]] });
  assert.equal(scattered.nodeCount, 3);

  const r = await call('relayout', { content: scattered.content });
  assert.equal(r.nodeCount, 3);
  assert.deepEqual(r.positionsBefore, [
    [500, 300],
    [770, 40],
    [1040, 460],
  ]);
  assert.deepEqual(r.positions, [
    [290, 428],
    [785, 428],
    [1280, 428],
  ]);
  // Envelope outside <Body> passes through verbatim.
  const stripBody = (s) => s.replace(/<Body>[0-9a-fA-F]+<\/Body>/, '<Body/>');
  assert.equal(stripBody(r.content), stripBody(scattered.content));
});

test('drx.relayout writes outPath', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'relayout-'));
  const out = path.join(dir, 'clean.drx');
  const r = await call('relayout', { content: await scatteredDrx(), outPath: out });
  assert.equal(r.outPath, out);
  assert.match(fs.readFileSync(out, 'utf8'), /<Body>[0-9a-fA-F]+<\/Body>/);
  fs.rmSync(dir, { recursive: true, force: true });
});

// ---- project_db.relayout_node_graphs against a synthetic Project.db ----

function makeDb(dbPath, bodies) {
  let Database;
  try {
    Database = require('better-sqlite3');
  } catch {
    return null; // optional native dep absent — DB tests skip
  }
  const db = new Database(dbPath);
  db.exec(
    'CREATE TABLE "ListMgt::LmVersion" ("ListMgt::LmVersion_id" TEXT PRIMARY KEY, Name TEXT, HasCorrection INTEGER, Body BLOB)',
  );
  const ins = db.prepare('INSERT INTO "ListMgt::LmVersion" VALUES (?, ?, ?, ?)');
  for (const [id, hasCorrection, body] of bodies) ins.run(id, 'Version 1', hasCorrection, body);
  db.close();
  return dbPath;
}

test('project_db.relayout_node_graphs: dry-run, write, verify, idempotence, skip-not-corrupt', async (t) => {
  const xml = await scatteredDrx();
  const scattered = (
    await call('relayout', { content: xml, positions: [[500, 300], [770, 40], [1040, 460]] })
  ).content;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'relayout-db-'));
  const dbPath = makeDb(path.join(dir, 'Project.db'), [
    ['row-scattered', 1, Buffer.from(bodyHex(scattered), 'hex')],
    ['row-ungraded', 0, Buffer.from(bodyHex(scattered), 'hex')], // HasCorrection=0 → untouched
    ['row-garbage', 1, Buffer.from('deadbeef', 'hex')], // undecodable → skipped, not corrupted
  ]);
  if (!dbPath) {
    t.skip('better-sqlite3 not installed');
    return;
  }

  const dry = await projectDbTool.handler({ action: 'relayout_node_graphs', args: { projectDb: dbPath, dryRun: true } });
  assert.equal(dry.dryRun, true);
  assert.equal(dry.gradedVersions, 2);
  assert.equal(dry.wouldRelayout, 1);
  assert.equal(dry.skipped.length, 1);
  assert.equal(dry.skipped[0].id, 'row-garbage');
  assert.equal(dry.backup, null);

  // Closed-project gate enforced on writes.
  await assert.rejects(
    () => projectDbTool.handler({ action: 'relayout_node_graphs', args: { projectDb: dbPath } }),
    /close the project/i,
  );

  const wet = await projectDbTool.handler({
    action: 'relayout_node_graphs',
    args: { projectDb: dbPath, iConfirmProjectClosed: true },
  });
  assert.equal(wet.relaidOut, 1);
  assert.ok(fs.existsSync(wet.backup), 'auto-backup written');
  assert.match(wet.note, /QUIT Resolve/i);
  assert.deepEqual(wet.changed[0].after, [
    [290, 428],
    [785, 428],
    [1280, 428],
  ]);

  // Untouched rows really untouched; patched row decodes to the clean row.
  const Database = require('better-sqlite3');
  const db = new Database(dbPath, { readonly: true });
  const get = db.prepare('SELECT Body FROM "ListMgt::LmVersion" WHERE "ListMgt::LmVersion_id" = ?');
  assert.equal(get.get('row-garbage').Body.toString('hex'), 'deadbeef');
  assert.equal(get.get('row-ungraded').Body.toString('hex'), bodyHex(scattered));
  assert.deepEqual(await layout.readNodePositions(Buffer.from(get.get('row-scattered').Body)), [
    [290, 428],
    [785, 428],
    [1280, 428],
  ]);
  db.close();

  // Second sweep: nothing left to do (≤2px tolerance counts the clean row as clean).
  const again = await projectDbTool.handler({
    action: 'relayout_node_graphs',
    args: { projectDb: dbPath, iConfirmProjectClosed: true },
  });
  assert.equal(again.relaidOut, 0);
  assert.equal(again.alreadyClean, 1);

  fs.rmSync(dir, { recursive: true, force: true });
});
