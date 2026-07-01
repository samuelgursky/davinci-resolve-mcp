'use strict';

/**
 * ops/patch.js — patch / re-cut lifecycle (spec §0.5, P4.5). Ingest a revised
 * turnover, diff it against the current online, re-conform & re-verify ONLY the
 * changed cuts, and ripple-update neighbours. Pure.
 */

/** Identity of a cut for diffing: its source + source position (not its record slot). */
function cutKey(c) {
  return `${c.source_basename || c.path || ''}@${c.sourceFrame != null ? c.sourceFrame : c.xml_in}`;
}

/**
 * Diff a revised timeline against the current online.
 * @returns { changed[], added[], removed[], unchanged[] } (each entry { seqstart, cut })
 */
function diffTimelines(currentClips, revisedClips) {
  const curBySeq = new Map(currentClips.map((c) => [c.seqstart, c]));
  const revBySeq = new Map(revisedClips.map((c) => [c.seqstart, c]));
  const changed = [];
  const added = [];
  const unchanged = [];
  for (const rev of revisedClips) {
    const cur = curBySeq.get(rev.seqstart);
    if (!cur) {
      added.push({ seqstart: rev.seqstart, cut: rev });
    } else if (cutKey(cur) !== cutKey(rev) || (cur.seqend - cur.seqstart) !== (rev.seqend - rev.seqstart)) {
      changed.push({ seqstart: rev.seqstart, cut: rev, was: cur });
    } else {
      unchanged.push({ seqstart: rev.seqstart, cut: rev });
    }
  }
  const removed = currentClips.filter((c) => !revBySeq.has(c.seqstart)).map((c) => ({ seqstart: c.seqstart, cut: c }));
  return { changed, added, removed, unchanged };
}

/** Re-conform & re-verify ONLY the changed/added cuts (not the whole reel). */
async function reverifyChanged(diff, verifyOne) {
  const targets = [...diff.changed, ...diff.added];
  const results = [];
  for (const t of targets) {
    // eslint-disable-next-line no-await-in-loop
    results.push({ seqstart: t.seqstart, result: await verifyOne(t.cut) });
  }
  return { reverified: results, skipped: diff.unchanged.length };
}

/**
 * Ripple-aware update (§9 patch-drift): a changed-duration cut shifts the record
 * positions of downstream cuts; mark touched + neighbours for re-verify, record
 * provenance. Returns the rippled timeline + the touched set.
 */
function rippleUpdate(currentClips, diff) {
  const changedBySeq = new Map(diff.changed.map((d) => [d.seqstart, d]));
  const sorted = [...currentClips].sort((a, b) => a.seqstart - b.seqstart);
  let shift = 0;
  const touched = new Set();
  const rippled = sorted.map((c, i) => {
    const ch = changedBySeq.get(c.seqstart);
    const next = { ...c, seqstart: c.seqstart + shift, seqend: c.seqend + shift };
    if (ch) {
      const oldDur = c.seqend - c.seqstart;
      const newDur = ch.cut.seqend - ch.cut.seqstart;
      const delta = newDur - oldDur;
      next.seqend = next.seqstart + newDur;
      touched.add(c.seqstart);
      if (i + 1 < sorted.length) touched.add(sorted[i + 1].seqstart); // neighbour
      shift += delta;
      next.provenance = { op: 'patch', durationDelta: delta };
    } else if (shift !== 0) {
      next.provenance = { op: 'ripple', recordShift: shift };
      touched.add(c.seqstart);
    }
    return next;
  });
  return { rippled, touched: [...touched], totalShift: shift };
}

module.exports = { diffTimelines, reverifyChanged, rippleUpdate, cutKey };
