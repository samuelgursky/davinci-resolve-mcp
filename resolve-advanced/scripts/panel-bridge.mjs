#!/usr/bin/env node
/**
 * panel-bridge — one-shot JSON bridge from the control panel (Python) to the
 * advanced server's libraries. Invoked as:
 *
 *   node scripts/panel-bridge.mjs <surface> <op> [argsJson]
 *
 * Prints exactly one JSON object to stdout: {success, result} | {success:false, error}.
 *
 * Surfaces are a deliberate READ-ONLY allowlist — the panel inspects state, it
 * never mutates through this bridge:
 *   capabilities get                     → optional-dep availability + install hints
 *   lineage list    {lineageDb, reel?}   → snapshots in a conform lineage sidecar
 *   lineage show    {lineageDb, snapshotId}
 *   lineage diff    {lineageDb, aId, bId}
 *   lineage verdicts{lineageDb, snapshotId, referenceRef?} → per-cut QC verdicts
 */

const [surface, op, argsJson] = process.argv.slice(2);

function out(obj) {
  process.stdout.write(JSON.stringify(obj));
}

try {
  const args = argsJson ? JSON.parse(argsJson) : {};
  let result;
  if (surface === 'capabilities') {
    const { capabilitiesTool } = await import('../server/tools/capabilities.mjs');
    result = await capabilitiesTool.handler({ action: op || 'get', args: {} });
  } else if (surface === 'lineage') {
    const lineage = await import('../server/lineage-db.mjs');
    const db = args.lineageDb;
    if (!db) throw new Error('lineageDb (path to the lineage SQLite sidecar) is required');
    if (op === 'list') result = { snapshots: lineage.listSnapshots(db, { reel: args.reel }) };
    else if (op === 'show') result = lineage.getSnapshot(db, args.snapshotId);
    else if (op === 'diff') result = lineage.diffSnapshots(db, args.aId, args.bId);
    else if (op === 'verdicts') result = { verdicts: lineage.listVerdicts(db, args.snapshotId, args.referenceRef ?? null) };
    else throw new Error(`unknown lineage op '${op}' (read-only bridge: list|show|diff|verdicts)`);
  } else {
    throw new Error(`unknown surface '${surface}' (capabilities|lineage)`);
  }
  out({ success: true, result });
} catch (e) {
  out({ success: false, error: String((e && e.message) || e) });
  process.exitCode = 1;
}
