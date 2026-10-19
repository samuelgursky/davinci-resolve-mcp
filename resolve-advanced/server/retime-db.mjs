/**
 * Variable-speed ramps written straight into a CLOSED project's Project.db (Studio 21 schema).
 *
 * A ramp made on Resolve's retime bar changes exactly two Sm2TiItem columns: MediaTimemapBA
 * (an Sm2TimeMap with protobuf keyframes) and Duration. This writes the same two, render-verified
 * on Studio 21.0.4.5 (see buildRampTimemapR21). Same safety tier as subtitle-db: Resolve fully
 * quit (process list), unique SQLite snapshot backup, schema guards, transaction, readback.
 */
import { randomUUID } from 'node:crypto';
import { createRequire } from 'node:module';
import { z } from 'zod';
import { openGuarded, requireResolveQuit, snapshotBackup } from './db-patch.mjs';
const require = createRequire(import.meta.url);
const { decodeTimemap, buildRampTimemapR21 } = require('../vendor/drp-format/media-timemap.js');

const target = { projectDb: z.string().optional(), projectName: z.string().optional() };
const segment = z.object({ durationFrames: z.number().int().positive(), speed: z.number().positive() }).strict();
export const retimeSchemas = {
  list_video_items: z.object({ ...target, timeline: z.string().optional() }).strict(),
  set_speed_ramp: z.object({
    ...target,
    itemId: z.string().optional().describe('Sm2TiItem_id from list_video_items'),
    timeline: z.string().optional(), track: z.number().int().min(1).default(1), index: z.number().int().min(0).default(0),
    segments: z.array(segment).min(1).describe('record-domain pieces from the clip head, e.g. [{durationFrames:30,speed:1},{durationFrames:90,speed:0.25}]'),
    allowRetimed: z.boolean().default(false).describe('replace an existing retime (default: only an unretimed 1x clip)'),
    dryRun: z.boolean().default(false), iConfirmProjectClosed: z.boolean().optional(),
  }).strict(),
};

const COLS = ['Sm2TiItem_id', 'Name', 'Start', 'Duration', 'MediaTimemapBA', 'Sm2TiTrack_id'];
function videoItems(db, timeline) {
  const rows = db.prepare(`SELECT it.Sm2TiItem_id id, it.Name name, it.Start start, it.Duration duration,
      it.MediaTimemapBA timemap, tr.Sm2TiTrack_id trackId, tl.Name timeline, sq.FrameRate fpsBlob
    FROM Sm2TiItem it JOIN Sm2TiTrack tr ON it.Sm2TiTrack_id = tr.Sm2TiTrack_id
    JOIN Sm2Sequence sq ON tr.Sequence = sq.Sm2Sequence_id
    JOIN Sm2Timeline tl ON tl.Sm2Timeline_id = sq.Sm2Timeline_id
    WHERE tr.Type = 0 ORDER BY tl.rowid, tr.rowid, CAST(it.Start AS INTEGER)`).all();
  const trackNo = new Map(); const perTrack = new Map();
  return rows.filter((r) => timeline == null || r.timeline === timeline).map((r) => {
    const key = r.timeline;
    if (!trackNo.has(key)) trackNo.set(key, []);
    const list = trackNo.get(key); if (!list.includes(r.trackId)) list.push(r.trackId);
    const idx = perTrack.get(r.trackId) || 0; perTrack.set(r.trackId, idx + 1);
    const fps = r.fpsBlob && r.fpsBlob.length >= 8 ? Buffer.from(r.fpsBlob).readDoubleLE(0) : null;
    let retime = null;
    try { retime = r.timemap ? decodeTimemap(Buffer.from(r.timemap)) : null; } catch (e) { retime = { error: e.message }; }
    return { id: r.id, name: r.name, timeline: r.timeline, track: list.indexOf(r.trackId) + 1, index: idx,
      start: Number(r.start), duration: Number(r.duration), fps, retime };
  });
}
const summary = (t) => (!t ? null : t.error ? { error: t.error } : t.form === 'identity'
  ? { form: 'identity', sourceFrames: null, seconds: t.seconds }
  : { form: 'retimed', variable: t.variable, segments: t.segments, sourceDurationSec: t.sourceDurationSec, recordDurationSec: t.recordDurationSec });

export async function retimeDbAction(action, args, resolveDbPath) {
  const p = retimeSchemas[action].parse(args);
  const dbPath = await resolveDbPath(p);
  if (action === 'list_video_items') {
    const db = openGuarded(dbPath, { table: 'Sm2TiItem', column: 'MediaTimemapBA' });
    try { return { items: videoItems(db, p.timeline).map((i) => ({ ...i, retime: summary(i.retime) })) }; } finally { db.close(); }
  }
  // set_speed_ramp
  if (!p.dryRun) requireResolveQuit(p);
  const db = openGuarded(dbPath, { writable: !p.dryRun, table: 'Sm2TiItem', column: 'MediaTimemapBA' });
  try {
    const names = db.prepare('PRAGMA table_info("Sm2TiItem")').all().map((c) => c.name);
    for (const c of COLS) if (!names.includes(c)) throw new Error(`unsupported schema: missing Sm2TiItem.${c}`);
    const all = videoItems(db, p.itemId ? undefined : p.timeline);
    const item = p.itemId ? all.find((i) => i.id === p.itemId) : all.find((i) => i.track === p.track && i.index === p.index);
    if (!item) throw new Error(p.itemId ? `no video item ${p.itemId}` : `no video item ${p.index} on V${p.track} of "${p.timeline}"`);
    if (!item.fps) throw new Error('unsupported timeline FrameRate encoding');
    if (item.retime?.error) throw new Error(`existing MediaTimemapBA does not decode: ${item.retime.error}`);
    if (item.retime?.form !== 'identity' && !p.allowRetimed) throw new Error('item is already retimed; pass allowRetimed:true to replace it');
    // Identity map = [02][(sourceFrames-1)/fps ...]: the media extent in seconds.
    const extentSec = item.retime?.form === 'identity' ? item.retime.seconds[0] : item.retime?.sourceDurationSec;
    const sourceFrames = Math.round(extentSec * item.fps) + 1;
    if (!(sourceFrames > 1)) throw new Error('cannot derive the media frame count from the existing map');
    const built = buildRampTimemapR21({ segments: p.segments, sourceFrames, fps: item.fps, uniqueId: randomUUID() });
    const plan = { item: { id: item.id, name: item.name, timeline: item.timeline, track: item.track, index: item.index },
      fps: item.fps, sourceFrames, durationFrames: built.durationFrames, sourceEndFrame: built.sourceEndFrame,
      before: { duration: item.duration, retime: summary(item.retime) } };
    if (p.dryRun) return { dryRun: true, ...plan };
    const backupPath = await snapshotBackup(dbPath);
    db.exec('BEGIN IMMEDIATE');
    try {
      db.prepare('UPDATE Sm2TiItem SET MediaTimemapBA=?, Duration=? WHERE Sm2TiItem_id=?')
        .run(built.timemap, String(built.durationFrames), item.id);
      const back = db.prepare('SELECT MediaTimemapBA m, Duration d FROM Sm2TiItem WHERE Sm2TiItem_id=?').get(item.id);
      if (!Buffer.from(back.m).equals(built.timemap) || Number(back.d) !== built.durationFrames) throw new Error('readback mismatch');
      db.exec('COMMIT');
    } catch (e) { db.exec('ROLLBACK'); throw e; }
    const after = decodeTimemap(built.timemap);
    return { ...plan, backupPath, after: summary(after),
      note: 'Readback only. Prove timing with a render (frame-coded clip), not this result.' };
  } finally { db.close(); }
}
