/**
 * Cluster E — editorial integrity. Native EDL/OTIO parse, changelist diff, timing silent-lie
 * guards, conform manifest, marker round-trip. All deterministic, no Resolve.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseEDL, parseOTIO, parseInterchange, diffChangelist, timingGuards, conformManifest, markerRoundtrip } from '../server/editorial.mjs';
import { editorialTool } from '../server/tools/editorial.mjs';

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
