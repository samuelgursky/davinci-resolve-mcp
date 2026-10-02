/** Transactional subtitle edits in a CLOSED local project library. */
import { randomUUID } from 'node:crypto';
import { createRequire } from 'node:module';
import { z } from 'zod';
import { openGuarded, requireNotLoaded, snapshotBackup } from './db-patch.mjs';
const require = createRequire(import.meta.url);
const { decodeCaption, encodeCaption, checkCaptions } = require('../vendor/drp-format/subtitle-captions.js');
const { decodePreset, setPresetInputs } = require('../vendor/drp-format/subtitle-preset.js');

const target = { projectDb: z.string().optional(), projectName: z.string().optional() };
const track = { timeline: z.string(), track: z.number().int().min(1).default(1) };
const write = { dryRun: z.boolean().default(false), iConfirmProjectClosed: z.boolean().optional(),
  allowWhileRunningIfNotLoaded: z.boolean().default(false) };
const frame = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const word = z.object({ text: z.string().min(1), start: z.number().nonnegative(), end: z.number().nonnegative() }).strict();
const caption = { text: z.string().min(1), start: frame, end: frame, words: z.array(word).min(1) };
const rgb = z.number().min(0).max(1);
const inputs = z.object({
  font: z.string().min(1).optional(), fontStyle: z.string().min(1).optional(),
  size: z.number().positive().max(1).optional(), position: z.tuple([rgb, rgb]).optional(),
  textRed: rgb.optional(), textGreen: rgb.optional(), textBlue: rgb.optional(), textAlpha: rgb.optional(),
  highlightRed: rgb.optional(), highlightGreen: rgb.optional(), highlightBlue: rgb.optional(),
  outlineRed: rgb.optional(), outlineGreen: rgb.optional(), outlineBlue: rgb.optional(),
  outlineEnabled: z.union([z.literal(0), z.literal(1)]).optional(), thickness: z.number().min(0).max(1).optional(),
}).strict();
export const subtitleSchemas = {
  list_subtitle_presets: z.object({ ...target, timeline: z.string().optional() }).strict(),
  list_captions: z.object({ ...target, ...track }).strict(),
  check_captions: z.object({ ...target, ...track, maxCharacters: z.number().int().positive().default(24) }).strict(),
  write_captions: z.object({ ...target, ...track, ...write,
    add: z.array(z.object(caption).strict()).default([]),
    replace: z.array(z.object({ id: z.string(), ...caption }).strict()).default([]),
    delete: z.array(z.string()).default([]), templateCaptionId: z.string().optional(),
  }).strict(),
  copy_subtitle_preset: z.object({ ...target, ...track, ...write,
    sourceProject: z.string().optional(), sourceProjectDb: z.string().optional(), sourceTimeline: z.string(),
    sourceTrack: z.number().int().positive().default(1), replace: z.boolean().default(false), inputs: inputs.optional(),
  }).strict(),
  set_subtitle_preset: z.object({ ...target, ...track, ...write, inputs }).strict(),
};

const quote = (s) => `"${s.replace(/"/g, '""')}"`;
function guard(db, table, columns) {
  const names = db.prepare(`PRAGMA table_info(${quote(table)})`).all().map((r) => r.name);
  for (const c of columns) if (!names.includes(c)) throw new Error(`unsupported schema: missing ${table}.${c}`);
  return names;
}
function tracks(db, timeline) {
  guard(db, 'Sm2TiTrack', ['Sm2TiTrack_id', 'Sequence', 'Type']);
  guard(db, 'Sm2Sequence', ['Sm2Sequence_id', 'Sm2Timeline_id', 'FrameRate']);
  guard(db, 'Sm2Timeline', ['Sm2Timeline_id', 'Name']);
  const timelines = db.prepare('SELECT Sm2Timeline_id id, Name FROM Sm2Timeline').all();
  if (timeline != null && timelines.filter((r) => r.Name === timeline).length !== 1) {
    throw new Error(`timeline "${timeline}" missing or ambiguous`);
  }
  const rows = db.prepare(`SELECT tr.Sm2TiTrack_id id, tl.Name timeline, tl.Sm2Timeline_id timelineId,
    sq.Sm2Sequence_id sequenceId, sq.FrameRate fpsBlob
    FROM Sm2TiTrack tr JOIN Sm2Sequence sq ON tr.Sequence=sq.Sm2Sequence_id
    JOIN Sm2Timeline tl ON tl.Sm2Timeline_id=sq.Sm2Timeline_id WHERE tr.Type=2 ORDER BY tl.rowid,tr.rowid`).all();
  // Resolve's vector association defines visible track order, not insertion order.
  const associations = ['Sm2Sequence_Sm2TiTrack', 'Sm2SequenceContainer_Sm2TiTrack']
    .filter((name) => db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name=?").get(name));
  const order = associations.flatMap((name) => {
    guard(db, name, ['DbOwner', 'DbAssociate', 'DbPropertyName', 'DbIndex']);
    return db.prepare(`SELECT * FROM ${name} WHERE DbPropertyName='SubtitleTrackVec'`).all();
  });
  if (order.length) {
    for (const r of rows) {
      const links = order.filter((a) => a.DbAssociate === r.id);
      if (links.length !== 1) throw new Error('unsupported subtitle track vector association');
      r.order = links[0].DbIndex;
    }
    rows.sort((a, b) => a.timelineId.localeCompare(b.timelineId) || a.order - b.order);
  } else if (rows.some((r, i) => rows.some((other, j) => j !== i && r.timelineId === other.timelineId))) {
    throw new Error('multiple subtitle tracks require SubtitleTrackVec ordering');
  }
  const counts = new Map();
  return rows.map((r) => {
    const n = (counts.get(r.timelineId) || 0) + 1; counts.set(r.timelineId, n);
    return { ...r, track: n };
  }).filter((r) => timeline == null || r.timeline === timeline);
}
function selectedTrack(db, p) {
  const row = tracks(db, p.timeline).find((r) => r.track === p.track);
  if (!row) throw new Error(`no subtitle track ${p.track} on timeline "${p.timeline}"`);
  const b = row.fpsBlob;
  if (!b || b.length !== 16) throw new Error('unsupported timeline FrameRate encoding');
  const fps = Buffer.from(b).readDoubleLE(0);
  if (!Number.isFinite(fps) || fps < 1 || fps > 240) throw new Error('invalid timeline frame rate');
  return { ...row, fps };
}
function items(db, tr, property) {
  guard(db, 'Sm2TiItem', ['Sm2TiItem_id', 'DbType', 'Name', 'Start', 'Duration', 'FieldsBlob', 'Sm2TiTrack_id', 'CompositionTable']);
  guard(db, 'Sm2TiItem_Sm2TiTrack', ['DbOwner', 'DbAssociate', 'DbPropertyName', 'DbIndex']);
  const links = db.prepare('SELECT * FROM Sm2TiItem_Sm2TiTrack WHERE DbOwner=? AND DbPropertyName=? ORDER BY DbIndex').all(tr.id, property);
  return links.map((link) => {
    const row = db.prepare('SELECT * FROM Sm2TiItem WHERE Sm2TiItem_id=?').get(link.DbAssociate);
    if (!row || row.Sm2TiTrack_id !== tr.id) throw new Error('dangling or inconsistent subtitle item association');
    return { row, link };
  });
}
function captions(db, tr) {
  return items(db, tr, 'Items').map(({ row, link }) => {
    if (row.DbType !== 'Sm2TiGenerator' || row.PrettyType !== 'Subtitle') throw new Error('unsupported item on subtitle track');
    const start = Number(row.Start), duration = Number(row.Duration);
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(duration)) throw new Error('invalid caption frame columns');
    return { row, link, decoded: { id: row.Sm2TiItem_id,
      ...decodeCaption(row.FieldsBlob, { name: row.Name || '', start, end: start + duration, fps: tr.fps }) } };
  });
}
function preset(db, tr) {
  const holders = items(db, tr, 'FusionCompHolderItems');
  if (holders.length > 1) throw new Error('multiple preset holders on one track; refusing ambiguous edit');
  if (!holders.length) return null;
  guard(db, 'Sm2TiCompositionTable', ['Sm2TiCompositionTable_id', 'Sm2TiItem_id', 'CompositionBA']);
  const { row, link } = holders[0];
  if (row.DbType !== 'Sm2TiVideoClip') throw new Error('unsupported preset holder type');
  const comp = db.prepare('SELECT * FROM Sm2TiCompositionTable WHERE Sm2TiCompositionTable_id=?').get(row.CompositionTable);
  if (!comp || comp.Sm2TiItem_id !== row.Sm2TiItem_id) throw new Error('dangling preset composition');
  return { row, link, comp, decoded: decodePreset(comp.CompositionBA) };
}
function insert(db, table, row) {
  const cols = guard(db, table, Object.keys(row));
  if (cols.length !== Object.keys(row).length) throw new Error(`source/target ${table} schema mismatch`);
  const keys = Object.keys(row);
  db.prepare(`INSERT INTO ${quote(table)} (${keys.map(quote).join(',')}) VALUES (${keys.map(() => '?').join(',')})`)
    .run(...keys.map((k) => row[k]));
}
function exclusive(db, row) {
  const links = db.prepare('SELECT * FROM Sm2TiItem_Sm2TiTrack WHERE DbAssociate=?').all(row.Sm2TiItem_id);
  if (links.length !== 1) throw new Error('shared subtitle item; refusing to mutate');
  for (const key of ['MediaRef', 'pLmVerTable', 'pAuxLmVerTable', 'OriginalClip', 'Sm2TiItem_Owner_id', 'TextRenderItemVec', 'Thumbnail', 'Group', 'ClipGroup']) {
    if (row[key]) throw new Error(`unsupported subtitle dependency ${key}; refusing to mutate`);
  }
}
function removeItem(db, row) {
  exclusive(db, row);
  if (row.CompositionTable) {
    const refs = db.prepare('SELECT Sm2TiItem_id FROM Sm2TiItem WHERE CompositionTable=?').all(row.CompositionTable);
    const comp = db.prepare('SELECT * FROM Sm2TiCompositionTable WHERE Sm2TiCompositionTable_id=?').get(row.CompositionTable);
    if (refs.length !== 1 || !comp || comp.Sm2MpMedia_id || comp.Sm2CompositionTableManager_id) throw new Error('shared/unsupported preset composition');
    db.prepare('DELETE FROM Sm2TiCompositionTable WHERE Sm2TiCompositionTable_id=?').run(row.CompositionTable);
  }
  db.prepare('DELETE FROM Sm2TiItem_Sm2TiTrack WHERE DbAssociate=?').run(row.Sm2TiItem_id);
  db.prepare('DELETE FROM Sm2TiItem WHERE Sm2TiItem_id=?').run(row.Sm2TiItem_id);
}
function captionEdit(db, p, mutate) {
  const tr = selectedTrack(db, p), current = captions(db, tr);
  const byId = new Map(current.map((c) => [c.decoded.id, c]));
  const ids = [...p.delete, ...p.replace.map((c) => c.id)];
  if (!p.add.length && !ids.length) throw new Error('no caption changes requested');
  if (new Set(ids).size !== ids.length) throw new Error('duplicate/conflicting caption ids');
  for (const id of ids) {
    if (!byId.has(id)) throw new Error(`caption ${id} is not on the selected track`);
    exclusive(db, byId.get(id).row);
  }
  const template = p.templateCaptionId ? byId.get(p.templateCaptionId) : current[0];
  if (p.add.length && !template) throw new Error('adding captions requires an existing caption on this track as a schema template');
  if (p.add.length) exclusive(db, template.row);
  const staged = [];
  for (const [fresh, list] of [[false, p.replace], [true, p.add]]) {
    for (const c of list) {
      if (c.text !== c.words.map((w) => w.text).join(' ') || c.words.some((w) => w.text !== w.text.trim())) {
        throw new Error('caption text must equal the words joined with spaces; words must be trimmed');
      }
      const base = fresh ? template : byId.get(c.id);
      if (base.row.CompositionTable) throw new Error('per-caption Fusion compositions are not supported');
      const blob = encodeCaption(base.row.FieldsBlob, c, tr.fps, { fresh });
      const id = fresh ? randomUUID() : c.id;
      const decoded = { id, ...decodeCaption(blob, { name: c.text, start: c.start, end: c.end, fps: tr.fps }) };
      const qc = checkCaptions([decoded], { fps: tr.fps });
      // Tick quantisation can otherwise turn a positive input word into a blank.
      // Half-tick boundary rounding is accepted; actual internal gaps are not.
      const errors = qc.issues.filter((r) => r.severity !== 'warning');
      if (errors.length) throw new Error(`invalid caption timing: ${JSON.stringify(errors)}`);
      const row = { ...base.row, Sm2TiItem_id: id, Name: ` ${c.text}`, Start: String(c.start),
        Duration: String(c.end - c.start), FieldsBlob: blob };
      if (fresh) for (const key of ['MarkersBA', 'RenderCacheBA', 'ImportExportMetadataBA']) if (key in row) row[key] = null;
      staged.push({ fresh, row, decoded });
    }
  }
  const removed = new Set(ids);
  const final = [...current.filter((c) => !removed.has(c.decoded.id)).map((c) => c.decoded), ...staged.map((c) => c.decoded)]
    .sort((a, b) => a.start - b.start || a.id.localeCompare(b.id));
  for (let i = 1; i < final.length; i++) if (final[i].start < final[i - 1].end) throw new Error('caption edits would leave overlapping captions');
  if (mutate) {
    for (const id of p.delete) removeItem(db, byId.get(id).row);
    for (const c of staged) {
      if (c.fresh) {
        insert(db, 'Sm2TiItem', c.row);
      } else db.prepare('UPDATE Sm2TiItem SET Name=?,Start=?,Duration=?,FieldsBlob=? WHERE Sm2TiItem_id=?')
        .run(c.row.Name, c.row.Start, c.row.Duration, c.row.FieldsBlob, c.row.Sm2TiItem_id);
    }
    // Resolve enforces DbIndex>=0, and its (owner,property,index) primary key
    // is ON CONFLICT REPLACE. Updating indices in place can silently DELETE a
    // neighbour when captions swap order. Rebuild only this Items vector in the
    // transaction, preserving each association's remaining columns.
    db.prepare("DELETE FROM Sm2TiItem_Sm2TiTrack WHERE DbOwner=? AND DbPropertyName='Items'").run(tr.id);
    final.forEach((c, i) => insert(db, 'Sm2TiItem_Sm2TiTrack', {
      ...(byId.get(c.id)?.link || template.link), DbOwner: tr.id, DbAssociate: c.id, DbPropertyName: 'Items', DbIndex: i,
    }));
    const back = captions(db, tr);
    if (JSON.stringify(back.map((c) => c.decoded)) !== JSON.stringify(final) || back.some((c, i) => c.link.DbIndex !== i)) {
      throw new Error('caption readback mismatch; transaction rolled back');
    }
  }
  return { timeline: p.timeline, track: p.track, fps: tr.fps, added: staged.filter((c) => c.fresh).map((c) => c.decoded.id),
    replaced: p.replace.map((c) => c.id), deleted: p.delete, captions: final, check: checkCaptions(final, { fps: tr.fps }) };
}
function presetEdit(db, p, mutate, source) {
  const tr = selectedTrack(db, p), before = preset(db, tr);
  if (source && before && !p.replace) throw new Error('target already has a preset; use replace:true');
  if (!source && !before) throw new Error('track has no animation preset; copy_subtitle_preset first');
  const base = source || before;
  if (before) exclusive(db, before.row);
  if (!source && !Object.keys(p.inputs).length) throw new Error('no preset input changes requested');
  const blob = p.inputs && Object.keys(p.inputs).length ? setPresetInputs(base.comp.CompositionBA, p.inputs) : Buffer.from(base.comp.CompositionBA);
  const after = decodePreset(blob);
  if (mutate) {
    if (source) {
      if (before) removeItem(db, before.row);
      const itemId = randomUUID(), compId = randomUUID();
      const row = { ...base.row, Sm2TiItem_id: itemId, Sm2TiTrack_id: tr.id, CompositionTable: compId };
      if (row.Track) row.Track = tr.id;
      const comp = { ...base.comp, Sm2TiCompositionTable_id: compId, Sm2TiItem_id: itemId, CompositionBA: blob };
      insert(db, 'Sm2TiItem', row);
      insert(db, 'Sm2TiCompositionTable', comp);
      insert(db, 'Sm2TiItem_Sm2TiTrack', { ...base.link, DbOwner: tr.id, DbAssociate: itemId, DbIndex: 0 });
    } else db.prepare('UPDATE Sm2TiCompositionTable SET CompositionBA=? WHERE Sm2TiCompositionTable_id=?')
      .run(blob, before.comp.Sm2TiCompositionTable_id);
    const back = preset(db, tr);
    if (!Buffer.from(back.comp.CompositionBA).equals(blob) || JSON.stringify(back.decoded) !== JSON.stringify(after)) {
      throw new Error('preset readback mismatch; transaction rolled back');
    }
  }
  return { timeline: p.timeline, track: p.track, before: before?.decoded || null, after,
    holderDuration: Number(base.row.Duration), note: 'Holder duration preserved from reference; render validation is required.' };
}

export async function subtitleDbAction(action, args, resolveDbPath) {
  // Snake-case project selectors from the workflow brief are accepted aliases.
  const aliases = { source_project: 'sourceProject', source_timeline: 'sourceTimeline',
    target_project: 'projectName', target_timeline: 'timeline', project: 'projectName' };
  args = { ...args };
  for (const [a, b] of Object.entries(aliases)) if (a in args) {
    if (b in args) throw new Error(`provide either ${a} or ${b}`);
    args[b] = args[a]; delete args[a];
  }
  const p = subtitleSchemas[action].parse(args), dbPath = await resolveDbPath(p);
  const db = openGuarded(dbPath);
  let source;
  try {
    if (action === 'list_subtitle_presets') return { presets: tracks(db, p.timeline).map((tr) => {
      const value = preset(db, tr);
      return { timeline: tr.timeline, timelineId: tr.timelineId, track: tr.track, trackId: tr.id,
        preset: value ? { id: value.row.Sm2TiItem_id, ...value.decoded, holderDuration: Number(value.row.Duration) } : null };
    }) };
    if (action === 'list_captions' || action === 'check_captions') {
      const tr = selectedTrack(db, p), list = captions(db, tr).map((c) => c.decoded);
      return { timeline: p.timeline, track: p.track, fps: tr.fps, timeUnit: 'timeline_frames',
        ...(action === 'list_captions' ? { captions: list } : checkCaptions(list, { fps: tr.fps, maxCharacters: p.maxCharacters })) };
    }
    if (action === 'copy_subtitle_preset') {
      const sourcePath = await resolveDbPath({ projectDb: p.sourceProjectDb, projectName: p.sourceProject });
      const src = openGuarded(sourcePath);
      try {
        source = preset(src, selectedTrack(src, { timeline: p.sourceTimeline, track: p.sourceTrack }));
        if (!source) throw new Error('source subtitle track has no animation preset');
        exclusive(src, source.row);
        if (source.comp.Sm2MpMedia_id || source.comp.Sm2CompositionTableManager_id) throw new Error('unsupported shared source composition');
      } finally { src.close(); }
    }
    const preview = action === 'write_captions' ? captionEdit(db, p, false) : presetEdit(db, p, false, source);
    if (p.dryRun) return { ...preview, dryRun: true, backup: null, verified: false };
  } finally { db.close(); }
  requireNotLoaded(p, dbPath);
  const backup = await snapshotBackup(dbPath);
  const loadedProject = requireNotLoaded(p, dbPath); // Recheck after the asynchronous snapshot.
  const writable = openGuarded(dbPath, { writable: true });
  try {
    const result = writable.transaction(() => action === 'write_captions'
      ? captionEdit(writable, p, true) : presetEdit(writable, p, true, source))();
    return { ...result, dryRun: false, backup, verified: true, validation: 'database_readback_only',
      ...(loadedProject ? { resolveRunning: true, loadedProject, reopenRequired: false,
        note: 'Written while Resolve kept another project loaded; load this project in Resolve to see the change.' }
        : { reopenRequired: true }) };
  } finally { writable.close(); }
}
