'use strict';

/**
 * ops/conform-diff.js — stage 4: diff the emulated conform TRUTH against the
 * actual imported Project.db state, per clip, across entries / timing / source-
 * frame / scaling / retime / transitions. The output drives injection (stage 5).
 *
 * Pure: takes the emulated truth (oracle/emulate output) + a normalized DB readout
 * and returns a per-clip/per-attribute discrepancy report. No IO — the caller
 * reads Project.db (project_read + effect-encoder/media-timemap decode) and passes
 * the normalized `db` in.
 *
 * DB readout shape:
 *   { clips: [{ start, duration, mediaStart, name, zoomX, zoomY, retimePresent }],
 *     transitions?: [{ start, end, type }], startOffset? }
 * Record positions are matched after removing the timeline start offset (the
 * import lead, e.g. 01:00:00:00); pass db.startOffset or it's inferred.
 */

function approx(a, b, tol) {
  if (a == null || b == null) return a === b;
  return Math.abs(a - b) <= tol;
}

/** Infer the record-start offset (db.start - truth.seqstart) as the modal delta. */
function inferOffset(truthClips, dbClips) {
  const ts = [...truthClips].map((c) => c.seqstart).sort((a, b) => a - b);
  const ds = [...dbClips].map((c) => c.start).sort((a, b) => a - b);
  // align by the smallest of each (first content clip)
  if (!ts.length || !ds.length) return 0;
  return ds[0] - ts[0];
}

/**
 * @param truth  oracle/emulate emulateSequence() output { clips, transitions }
 * @param db     normalized Project.db readout (see header)
 * @param opts   { zoomTol=0.0005, offset? }
 */
function diffConform(truth, db, opts = {}) {
  const zoomTol = opts.zoomTol != null ? opts.zoomTol : 0.0005;
  const offset = opts.offset != null ? opts.offset : (db.startOffset != null ? db.startOffset : inferOffset(truth.clips, db.clips));

  // Index DB clips by aligned record start (+track-agnostic; collide → list).
  const dbByStart = new Map();
  for (const d of db.clips) {
    const k = d.start - offset;
    if (!dbByStart.has(k)) dbByStart.set(k, []);
    dbByStart.get(k).push(d);
  }
  const matchedDb = new Set();
  const perClip = [];
  const missing = []; // in truth, not in DB (dropped on import)
  for (const t of truth.clips) {
    const cands = dbByStart.get(t.seqstart) || [];
    const d = cands.find((x) => !matchedDb.has(x)) || null;
    if (!d) {
      missing.push({ seqstart: t.seqstart, source: t.source.basename, sourceFrame: t.sourceFrame });
      continue;
    }
    matchedDb.add(d);
    const issues = [];
    if (!approx(t.transform.zoomX, d.zoomX, zoomTol)) {
      issues.push({ attr: 'scaling', truth: t.transform.zoomX, db: d.zoomX, confidence: t.flags.scaleConfidence, aspectMismatch: t.flags.aspectMismatch });
    }
    if (t.timing.duration != null && d.duration != null && t.timing.duration !== d.duration) {
      issues.push({ attr: 'timing', truth: t.timing.duration, db: d.duration });
    }
    if (t.sourceFrame != null && d.mediaStart != null && t.sourceFrame !== d.mediaStart) {
      issues.push({ attr: 'sourceFrame', truth: t.sourceFrame, db: d.mediaStart });
    }
    if (t.retime.retimed !== !!d.retimePresent) {
      issues.push({ attr: 'retime', truth: t.retime.retimed, db: !!d.retimePresent });
    }
    perClip.push({ seqstart: t.seqstart, source: t.source.basename, ok: issues.length === 0, issues });
  }
  const extra = db.clips.filter((d) => !matchedDb.has(d)).map((d) => ({ start: d.start - offset, name: d.name }));

  // transitions: count + position/type (best-effort; db transitions optional)
  const dbTr = db.transitions || [];
  const transitions = {
    truth: truth.transitions.length,
    db: dbTr.length,
    match: truth.transitions.length === dbTr.length,
  };

  const withIssues = perClip.filter((c) => !c.ok);
  return {
    offset,
    summary: {
      truthClips: truth.clips.length,
      dbClips: db.clips.length,
      matched: perClip.length,
      clean: perClip.filter((c) => c.ok).length,
      withIssues: withIssues.length,
      missing: missing.length,
      extra: extra.length,
      byAttr: ['scaling', 'timing', 'sourceFrame', 'retime'].reduce((m, a) => {
        m[a] = withIssues.filter((c) => c.issues.some((i) => i.attr === a)).length;
        return m;
      }, {}),
      transitions,
    },
    issues: withIssues,
    missing,
    extra,
  };
}

module.exports = { diffConform, inferOffset };
