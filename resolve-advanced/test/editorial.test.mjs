/**
 * Cluster E — editorial integrity. Native EDL/OTIO parse, changelist diff, timing silent-lie
 * guards, conform manifest, marker round-trip. All deterministic, no Resolve.
 */
import { test } from 'node:test';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import { parseEDL, parseOTIO, parseInterchange, diffChangelist, timingGuards, listTransitions, conformManifest, markerRoundtrip } from '../server/editorial.mjs';
import { editorialTool } from '../server/tools/editorial.mjs';
import { drtTool } from '../server/tools/drt.mjs';

const EDL = `TITLE: EP012 LOCKED
FCM: NON-DROP FRAME
001  A001     V     C        01:00:00:00 01:00:04:00 01:00:00:00 01:00:04:00
002  B002     V     C        02:00:00:00 02:00:02:00 01:00:04:00 01:00:06:00
M2   B002     048.0             02:00:00:00
`;

test('parseEDL yields normalized events with frames + a retime from M2', () => {
  const ev = parseEDL(EDL, { fps: 24 });
  assert.equal(ev.length, 2);
  assert.equal(ev[0].source, 'A001');
  assert.equal(ev[0].recIn, 24 * 3600);
  assert.equal(ev[0].srcOut - ev[0].srcIn, 96); // 4s @ 24
  // B002 has M2 048.0 → 200% speed.
  assert.ok(Math.abs(ev[1].speed - 200) < 0.1, `speed ${ev[1].speed}`);
});

const OTIO = {
  OTIO_SCHEMA: 'Timeline.1',
  tracks: {
    children: [
      {
        OTIO_SCHEMA: 'Track.1',
        kind: 'Video',
        children: [
          {
            OTIO_SCHEMA: 'Clip.1',
            name: 'A001',
            media_reference: { target_url: 'A001.mov' },
            source_range: { start_time: { value: 0, rate: 24 }, duration: { value: 96, rate: 24 } },
          },
          { OTIO_SCHEMA: 'Gap.1', source_range: { duration: { value: 10, rate: 24 } } },
          {
            OTIO_SCHEMA: 'Clip.1',
            name: 'B002',
            media_reference: { target_url: 'B002.mov' },
            source_range: { start_time: { value: 0, rate: 24 }, duration: { value: 48, rate: 24 } },
            effects: [{ OTIO_SCHEMA: 'LinearTimeWarp.1', time_scalar: 2.0 }],
          },
        ],
      },
    ],
  },
};

test('parseOTIO accumulates record positions across gaps and reads time_scalar', () => {
  const ev = parseOTIO(OTIO);
  assert.equal(ev.length, 2);
  assert.equal(ev[0].recIn, 0);
  assert.equal(ev[0].recOut, 96);
  assert.equal(ev[1].recIn, 106); // 96 + 10 gap
  assert.equal(ev[1].speed, 200);
});

test('parseInterchange refuses AAF honestly', () => {
  assert.throws(() => parseInterchange('aaf', 'anything'), /AAF is binary/);
});

// A .drt/.drp is a ZIP. The cluster parses it (sequences.mjs listSequences) and the tool
// description advertises it, so the content-shaped caller must be ROUTED, not told the format
// is unknown — an "unknown format" here reads as "not supported" and the caller silently
// records zero events.
test('parseInterchange routes drt/drp to the path-based reader instead of calling them unknown', () => {
  for (const fmt of ['drt', 'drp', 'DRT']) {
    assert.throws(
      () => parseInterchange(fmt, 'PK (a .drt slurped as text)'),
      (err) => {
        assert.match(err.message, /ZIP/, `${fmt}: should say it is a ZIP — got: ${err.message}`);
        assert.match(err.message, /parseDRT/, `${fmt}: should name the path-based reader — got: ${err.message}`);
        assert.match(err.message, /list_sequences|drtPath/, `${fmt}: should name a callable entry point — got: ${err.message}`);
        assert.doesNotMatch(err.message, /unknown format/, `${fmt}: must not claim the format is unknown`);
        return true;
      },
    );
  }
});

test('parseInterchange default message lists drt|drp among the known formats', () => {
  assert.throws(
    () => parseInterchange('mogrt', 'x'),
    (err) => {
      assert.match(err.message, /unknown format 'mogrt'/);
      assert.match(err.message, /\bdrt\b/, `default message should list drt — got: ${err.message}`);
      assert.match(err.message, /\bdrp\b/, `default message should list drp — got: ${err.message}`);
      return true;
    },
  );
});

test('editorial.parse_interchange accepts drt/drp as a format and answers with the redirect, not a schema dump', async () => {
  for (const format of ['drt', 'drp']) {
    await assert.rejects(
      () => editorialTool.handler({ action: 'parse_interchange', args: { format, content: 'PK' } }),
      (err) => {
        assert.match(err.message, /parseDRT/, `${format}: got: ${err.message}`);
        assert.doesNotMatch(err.message, /invalid_enum_value|Invalid enum/, `${format}: must not be a bare zod dump`);
        return true;
      },
    );
  }
});

test('drt.parse names drtPath when a caller passes content instead of a path', async () => {
  await assert.rejects(
    () => drtTool.handler({ action: 'parse', args: { content: 'PK' } }),
    (err) => {
      assert.match(err.message, /drtPath/, `got: ${err.message}`);
      assert.doesNotMatch(err.message, /^\[\s*\{/, 'must not be a bare zod issue dump');
      return true;
    },
  );
});

test('turnover_changelist classifies moved / retimed / replaced / new / gone', () => {
  const oldE = parseOTIO(OTIO);
  // New cut: A001 moved later, B002 flattened to 100%, add a C003, drop nothing.
  const newE = [
    { track: 'V', source: 'A001.mov', srcIn: 0, srcOut: 96, recIn: 50, recOut: 146, speed: 100, reverse: false, fps: 24 },
    { track: 'V', source: 'B002.mov', srcIn: 0, srcOut: 48, recIn: 156, recOut: 204, speed: 100, reverse: false, fps: 24 },
    { track: 'V', source: 'C003.mov', srcIn: 0, srcOut: 24, recIn: 210, recOut: 234, speed: 100, reverse: false, fps: 24 },
  ];
  const d = diffChangelist(oldE, newE);
  const a = d.changes.find((c) => c.source === 'A001.mov');
  assert.equal(a.kind, 'moved');
  const b = d.changes.find((c) => c.source === 'B002.mov');
  assert.equal(b.kind, 'retimed');
  assert.ok(d.changes.some((c) => c.source === 'C003.mov' && c.kind === 'new'));
});

test('turnover_changelist detects a replacement at the same record position', () => {
  const oldE = [{ track: 'V', source: 'OLD', srcIn: 0, srcOut: 48, recIn: 100, recOut: 148, speed: 100, reverse: false, fps: 24 }];
  const newE = [{ track: 'V', source: 'NEW', srcIn: 0, srcOut: 48, recIn: 100, recOut: 148, speed: 100, reverse: false, fps: 24 }];
  const d = diffChangelist(oldE, newE);
  const rep = d.changes.find((c) => c.kind === 'replaced');
  assert.ok(rep, JSON.stringify(d.changes));
  assert.equal(rep.oldSource, 'OLD');
  assert.equal(rep.source, 'NEW');
});

test('timingGuards flags flattened retime, dropped split audio, reverse dropped, fps slip', () => {
  const oldE = [
    { track: 'V', source: 'RAMP', speed: 200, reverse: false, fps: 24 },
    { track: 'A', source: 'DIAL', speed: 100, reverse: false, fps: 24 },
    { track: 'V', source: 'DIAL', speed: 100, reverse: false, fps: 24 },
    { track: 'V', source: 'REV', speed: 100, reverse: true, fps: 24 },
    { track: 'V', source: 'PULL', speed: 100, reverse: false, fps: 24 },
  ];
  const newE = [
    { track: 'V', source: 'RAMP', speed: 100, reverse: false, fps: 24 }, // flattened
    { track: 'V', source: 'DIAL', speed: 100, reverse: false, fps: 24 }, // audio DIAL dropped
    { track: 'V', source: 'REV', speed: 100, reverse: false, fps: 24 }, // reverse dropped
    { track: 'V', source: 'PULL', speed: 100, reverse: false, fps: 23.976 }, // fps slip
  ];
  const g = timingGuards(oldE, newE);
  const kinds = g.flags.map((f) => f.kind);
  assert.ok(kinds.includes('flattened_retime'));
  assert.ok(kinds.includes('dropped_split_audio'));
  assert.ok(kinds.includes('reverse_dropped'));
  assert.ok(kinds.includes('framerate_slip'));
});

test('conform_manifest asserts source/handles/retime/reverse and starves a fat transition', () => {
  const events = [
    { index: 1, track: 'V', source: 'A001', speed: 100, reverse: false, transition: { type: 'D', duration: 24 } },
    { index: 2, track: 'V', source: 'B002', speed: 200, reverse: true, transition: null },
    { index: 3, track: 'V', source: 'OFF', speed: 100, reverse: false, transition: null },
  ];
  const resolution = {
    A001: { online: true, path: '/m/A001.mov', handleIn: 6, handleOut: 6 }, // transition needs 12/side → starved
    B002: { online: true, path: '/m/B002.mov', handleIn: 24, handleOut: 24, speed: 200, reverse: true },
    OFF: { online: false },
  };
  const r = conformManifest(events, resolution, { minHandle: 0 });
  assert.equal(r.pass, false);
  const a = r.rows.find((x) => x.source === 'A001');
  assert.equal(a.checks.find((c) => c.name === 'handles').pass, false);
  const b = r.rows.find((x) => x.source === 'B002');
  assert.equal(b.pass, true, JSON.stringify(b.checks));
  const off = r.rows.find((x) => x.source === 'OFF');
  assert.equal(off.checks.find((c) => c.name === 'source_resolved').pass, false);
});

test('marker_roundtrip preserves count + stamps provenance', () => {
  const r = markerRoundtrip(
    [
      { frame: 100, note: 'flash', source: 'editor' },
      { frame: 250, name: 'VFX' },
    ],
    { provenanceTag: 'AUTO:marker_roundtrip v1' },
  );
  assert.equal(r.count, 2);
  assert.equal(r.provenanceOk, true);
  assert.match(r.markers[0].provenance, /editor/);
});

test('editorial tool dispatches turnover_changelist with timing guards', async () => {
  const oldE = [{ track: 'V', source: 'RAMP', recIn: 0, speed: 200, reverse: false, fps: 24 }];
  const newE = [{ track: 'V', source: 'RAMP', recIn: 0, speed: 100, reverse: false, fps: 24 }];
  const r = await editorialTool.handler({ action: 'turnover_changelist', args: { old: oldE, new: newE } });
  assert.ok(r.timing.flags.some((f) => f.kind === 'flattened_retime'));
});

// ── E106: the changelist sees junctions ────────────────────────────────
// Measured 2026-09-01: a 24→12 dissolve change reported NOTHING, dropped
// fades read as "BL gone", and the zero-length CMX carrier line of the
// outgoing side read as "B002 gone". timingGuards paired first-row-wins,
// so an identical cut with a dropped A2 leg flagged a FALSE flattened
// retime and never flagged the audio drop (track 'A2' ≠ 'A').
const FADE_EDL_OLD = `TITLE: OLD
FCM: NON-DROP FRAME
001  BL       V     C        00:00:00:00 00:00:00:00 01:00:00:00 01:00:00:00
002  A001     V     D    024 00:00:00:00 00:00:04:00 01:00:00:00 01:00:04:00
003  A001     AA    C        00:00:00:00 00:00:04:00 01:00:00:00 01:00:04:00
004  A001     V     C        00:00:04:00 00:00:04:00 01:00:04:00 01:00:04:00
005  B002     V     D    024 00:00:00:00 00:00:04:00 01:00:04:00 01:00:08:00
006  B002     V     C        00:00:04:00 00:00:04:00 01:00:08:00 01:00:08:00
007  BL       V     D    024 00:00:00:00 00:00:01:00 01:00:08:00 01:00:09:00
008  A001     V     C        00:00:08:00 00:00:10:00 01:00:09:00 01:00:11:00
M2   A001           012.0                00:00:08:00
`;
const FADE_EDL_NEW = `TITLE: NEW
FCM: NON-DROP FRAME
001  A001     V     C        00:00:00:00 00:00:04:00 01:00:00:00 01:00:04:00
002  A001     AA    C        00:00:00:00 00:00:04:00 01:00:00:00 01:00:04:00
003  A001     V     C        00:00:04:00 00:00:04:00 01:00:04:00 01:00:04:00
004  B002     V     D    012 00:00:00:00 00:00:04:00 01:00:04:00 01:00:08:00
005  A001     V     C        00:00:08:00 00:00:10:00 01:00:08:00 01:00:10:00
`;

test('listTransitions classifies EDL fades and dissolves with bridge-exact spans (E106)', () => {
  const trs = listTransitions(parseEDL(FADE_EDL_OLD));
  assert.deepEqual(trs.map((t) => [t.fade, t.outgoing, t.incoming, t.duration, t.start, t.end, t.pre]), [
    ['in', 'BL', 'A001', 24, 86400, 86424, 0],
    [null, 'A001', 'B002', 24, 86496, 86520, 0],
    ['out', 'B002', 'BL', 24, 86592, 86616, 0],
  ]);
});

test('turnover_changelist reports dropped fades and a shortened dissolve — never a gone BL or carrier (E106)', () => {
  const oldE = parseEDL(FADE_EDL_OLD), newE = parseEDL(FADE_EDL_NEW);
  const d = diffChangelist(oldE, newE);
  assert.deepEqual(d.counts, { retimed: 1, transition_changed: 1, transition_dropped: 2 }, JSON.stringify(d.changes));
  assert.ok(!d.changes.some((c) => c.kind === 'gone' || c.kind === 'new'), 'carrier lines and fade legs must not read as sources');
  const fadeIn = d.changes.find((c) => c.kind === 'transition_dropped' && c.fade === 'in');
  assert.equal(fadeIn.incoming, 'A001');
  assert.equal(fadeIn.oldRecIn, 86400);
  const fadeOut = d.changes.find((c) => c.kind === 'transition_dropped' && c.fade === 'out');
  assert.equal(fadeOut.outgoing, 'B002');
  const dis = d.changes.find((c) => c.kind === 'transition_changed');
  assert.deepEqual(dis.deltas, { duration: { old: 24, new: 12 } });
  assert.deepEqual([dis.outgoing, dis.incoming, dis.fade], ['A001', 'B002', null]);
  assert.deepEqual(d.transitions, { old: 3, new: 1 });
  assert.deepEqual(d.carriersFolded, { old: 4, new: 1 });
  // Null control: a cut diffed against itself is silent on every axis.
  const self = diffChangelist(oldE, parseEDL(FADE_EDL_OLD));
  assert.equal(self.changedCount, 0, JSON.stringify(self.changes));
  assert.deepEqual(timingGuards(oldE, parseEDL(FADE_EDL_OLD)).flags, []);
});

test('timingGuards flags lost fades/dissolves as timing lies (E106)', () => {
  const g = timingGuards(parseEDL(FADE_EDL_OLD), parseEDL(FADE_EDL_NEW));
  const kinds = g.flags.map((f) => f.kind).sort();
  assert.deepEqual(kinds, ['flattened_retime', 'transition_dropped', 'transition_dropped']);
  assert.ok(g.flags.some((f) => f.kind === 'transition_dropped' && /fade-in/.test(f.detail)));
  assert.ok(g.flags.some((f) => f.kind === 'transition_dropped' && /fade-out/.test(f.detail)));
});

test('timingGuards pairs a twice-used source instance-to-instance and sees A2 (E106)', () => {
  const oldE = [
    { track: 'V', source: 'A001', srcIn: 0, srcOut: 48, recIn: 0, recOut: 48, speed: 100, reverse: false, fps: 24 },
    { track: 'V', source: 'A001', srcIn: 100, srcOut: 124, recIn: 200, recOut: 248, speed: 50, reverse: false, fps: 24 },
    { track: 'A2', source: 'A001', srcIn: 0, srcOut: 48, recIn: 0, recOut: 48, speed: 100, reverse: false, fps: 24 },
  ];
  // Same video, listed in the other order, A2 leg dropped: the ONLY truth is the audio drop.
  const g = timingGuards(oldE, [oldE[1], oldE[0]]);
  assert.deepEqual(g.flags.map((f) => f.kind), ['dropped_split_audio']);
  assert.equal(g.flags[0].track, 'A2');
  // The second instance flattened → flagged at ITS record position, not the first's.
  const g2 = timingGuards(oldE, [oldE[0], { ...oldE[1], speed: 100 }]);
  const flat = g2.flags.find((f) => f.kind === 'flattened_retime');
  assert.equal(flat.recIn, 200);
  // Null control: identical lists, either order, flag nothing.
  assert.deepEqual(timingGuards(oldE, [oldE[2], oldE[1], oldE[0]]).flags, []);
});

test('turnover_changelist sees an OTIO span reshaped from centered to start-at-cut (E106)', () => {
  const rt = (v, r = 24) => ({ OTIO_SCHEMA: 'RationalTime.1', rate: r, value: v });
  const tr = (s, d, r = 24) => ({ OTIO_SCHEMA: 'TimeRange.1', start_time: rt(s, r), duration: rt(d, r) });
  const clip = (url, sIn, d) => ({ OTIO_SCHEMA: 'Clip.2', name: url, source_range: tr(sIn, d), media_reference: { target_url: url }, effects: [], markers: [] });
  const T = (i, o) => ({ OTIO_SCHEMA: 'Transition.1', transition_type: 'SMPTE_Dissolve', in_offset: rt(i), out_offset: rt(o) });
  const tl = (children) => ({ OTIO_SCHEMA: 'Timeline.1', tracks: { OTIO_SCHEMA: 'Stack.1', children: [{ OTIO_SCHEMA: 'Track.1', kind: 'Video', markers: [], children }] } });
  const build = (pre) => parseOTIO(tl([T(pre, 24 - pre), clip('/m/cut.mp4', 24, 72), T(pre, 24 - pre), clip('/m/wht.mp4', 24, 48), T(12, 12), { OTIO_SCHEMA: 'Gap.1', source_range: tr(0, 48) }]), { fps: 24 });
  const oldE = build(12), newE = build(0);
  const trs = listTransitions(oldE);
  // A pre-rolled fade-in at track start spans before frame 0; its outgoing is still the BL slug.
  assert.deepEqual(trs.map((t) => [t.fade, t.start, t.end, t.junction]), [['in', -12, 12, 0], [null, 60, 84, 72], ['out', 108, 132, 120]]);
  const d = diffChangelist(oldE, newE);
  assert.deepEqual(d.counts, { transition_changed: 2 }, JSON.stringify(d.changes));
  assert.ok(d.changes.every((c) => c.deltas.pre.old === 12 && c.deltas.pre.new === 0));
  assert.equal(diffChangelist(oldE, build(12)).changedCount, 0);
});

test('editorial tool surfaces the junction diff through the protocol shape (E106)', async () => {
  const r = await editorialTool.handler({ action: 'turnover_changelist', args: { old: parseEDL(FADE_EDL_OLD), new: parseEDL(FADE_EDL_NEW) } });
  assert.equal(r.counts.transition_dropped, 2);
  assert.deepEqual(r.carriersFolded, { old: 4, new: 1 });
  assert.ok(r.timing.flags.some((f) => f.kind === 'transition_dropped'));
});


// E124: compound forms in the manifest and the changelist. Resolve's XML writer
// collapses a compound to one media-less clipitem (E121); its OTIO writer
// flattens the inner cuts (E120). Fixtures are the verbatim exports.
test('conform_manifest names a compound clipitem; turnover_changelist reports a collapse once (E124)', () => {
  const xml = parseInterchange('xml', fs.readFileSync(new URL('./fixtures/E120_resolve_nested_export.xml', import.meta.url), 'utf8'));
  const otio = parseInterchange('otio', fs.readFileSync(new URL('./fixtures/E120_resolve_nested_export.otio', import.meta.url), 'utf8'), { fps: 24 });
  const m = conformManifest(xml, { 'cut_src.mp4': { path: '/m/cut_src.mp4', handleIn: 24, handleOut: 24 } });
  const row = m.rows.find((r) => r.source === 'E57_OUT');
  assert.equal(row.pass, false);
  assert.equal(row.compound, 'E57_OUT');
  assert.match(row.checks[0].detail, /compound clip "E57_OUT".*OTIO/);
  // Mapped to a flattened file it resolves like any source.
  const mapped = conformManifest(xml, { 'cut_src.mp4': { path: '/m/cut_src.mp4' }, E57_OUT: { path: '/m/e57_out_flat.mov' } });
  assert.equal(mapped.rows.find((r) => r.source === 'E57_OUT').pass, true);
  // Changelist: flattened (OTIO) → collapsed (XML) is one compound_collapsed, not replaced + gone.
  const d = diffChangelist(otio, xml);
  assert.deepEqual(d.counts, { compound_collapsed: 1 }, JSON.stringify(d.changes));
  assert.deepEqual(d.changes[0], { kind: 'compound_collapsed', name: 'E57_OUT', track: 'V', oldRecIn: 48, newRecIn: 48, innerCuts: 2 });
  const back = diffChangelist(xml, otio);
  assert.deepEqual(back.counts, { compound_expanded: 1 });
  // Null control: a collapsed compound of ANOTHER name over those cuts is a real replacement.
  const stranger = xml.map((e) => (e.compound ? { ...e, compound: 'OTHER', source: 'OTHER' } : e));
  const d2 = diffChangelist(otio, stranger);
  assert.equal(d2.counts.compound_collapsed, undefined);
  assert.ok((d2.counts.replaced || 0) + (d2.counts.gone || 0) + (d2.counts.new || 0) >= 2);
});

// ── E138: changelist SHAPE — a sparse patch reel is a subset, not N deletions ──
const SHAPE_EDL_OLD = `TITLE: OLD
FCM: NON-DROP FRAME
001  A001     V     C        00:00:00:00 00:00:02:00 01:00:00:00 01:00:02:00
002  B002     V     C        00:00:00:00 00:00:02:00 01:00:02:00 01:00:04:00
003  B002     V     C        00:00:02:00 00:00:02:00 01:00:04:00 01:00:04:00
004  C003     V     D    012 00:00:00:00 00:00:02:00 01:00:04:00 01:00:06:00
005  A001     V     C        00:00:05:00 00:00:07:00 01:00:06:00 01:00:08:00
006  D004     V     C        00:00:00:00 00:00:02:00 01:00:08:00 01:00:10:00
`;
const SHAPE_EDL_SUBSET = `TITLE: PATCH
FCM: NON-DROP FRAME
001  A001     V     C        00:00:00:00 00:00:02:00 01:00:00:00 01:00:02:00
002  A001     V     C        00:00:05:00 00:00:07:00 01:00:06:00 01:00:08:00
`;
const SHAPE_EDL_SUBSET_TRIMMED = SHAPE_EDL_SUBSET.replace('00:00:05:00 00:00:07:00 01:00:06:00', '00:00:05:01 00:00:07:00 01:00:06:00');

test('turnover_changelist names a sparse patch reel a subset — nothing edited, dropped dissolve is a consequence (E138)', () => {
  const oldE = parseEDL(SHAPE_EDL_OLD), subE = parseEDL(SHAPE_EDL_SUBSET);
  const d = diffChangelist(oldE, subE);
  assert.equal(d.shape, 'subset', JSON.stringify(d.counts));
  assert.equal(d.retained, 2);
  assert.equal(d.oldCuts, 5);
  assert.equal(d.newCuts, 2);
  assert.equal(d.sparse, true);
  assert.deepEqual(d.counts, { gone: 3, transition_dropped: 1 });
  assert.deepEqual(d.retainedWindows.map((w) => [w.source, w.recIn, w.recOut]), [['A001', 86400, 86448], ['A001', 86544, 86592]]);
  assert.match(d.note, /keeps 2 of 5 cuts unchanged/);
  // gone changes now carry their record OUT so a dropped junction can be attributed to them
  assert.ok(d.changes.filter((c) => c.kind === 'gone').every((c) => Number.isFinite(c.oldRecOut)));
});

test('turnover_changelist: the reverse direction is a superset; identical is identical (E138)', () => {
  const oldE = parseEDL(SHAPE_EDL_OLD), subE = parseEDL(SHAPE_EDL_SUBSET);
  const up = diffChangelist(subE, oldE);
  assert.equal(up.shape, 'superset');
  assert.equal(up.retained, 2);
  assert.deepEqual(up.counts, { new: 3, transition_added: 1 });
  assert.match(up.note, /old is 2 of the new cut's 5 cuts/);
  const same = diffChangelist(oldE, parseEDL(SHAPE_EDL_OLD));
  assert.equal(same.shape, 'identical');
  assert.equal(same.retained, 5);
  assert.equal(same.changedCount, 0);
});

test('turnover_changelist: one trimmed survivor makes a patch reel an edit, never a subset (E138 null control)', () => {
  const d = diffChangelist(parseEDL(SHAPE_EDL_OLD), parseEDL(SHAPE_EDL_SUBSET_TRIMMED));
  assert.equal(d.shape, 'edit');
  assert.equal(d.counts.trimmed, 1);
  assert.equal(d.retained, 1);
  assert.equal(d.sparse, undefined);
  assert.equal(d.retainedWindows, undefined);
  // and a full re-cut with the same cut count stays an edit
  const full = diffChangelist(parseEDL(SHAPE_EDL_OLD), parseEDL(SHAPE_EDL_OLD.replace('D004', 'E005')));
  assert.equal(full.shape, 'edit');
  assert.equal(full.counts.replaced, 1);
});

test('pairEvents is closest-first globally — a later new instance keeps the old instance at its own position (E138)', () => {
  const X = (recIn) => ({ track: 'V', source: 'X.mov', srcIn: 100, srcOut: 148, recIn, recOut: recIn + 48, speed: 100 });
  const patch = [X(240)];
  const full = [X(0), X(240)];
  const up = diffChangelist(patch, full);
  assert.equal(up.shape, 'superset', JSON.stringify(up.changes));
  assert.deepEqual(up.counts, { new: 1 });
  assert.equal(up.changes[0].newRecIn, 0);
  const down = diffChangelist(full, patch);
  assert.equal(down.shape, 'subset');
  assert.deepEqual(down.counts, { gone: 1 });
  assert.equal(down.changes[0].oldRecIn, 0);
});
