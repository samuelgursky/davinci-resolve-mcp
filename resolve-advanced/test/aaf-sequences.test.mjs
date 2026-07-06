/**
 * AAF offline preview (pyaaf2 bridge), unified list_sequences enumeration, and PrProj honest
 * refusal. The AAF path is exercised with a STUB "python" so the wiring is deterministic without
 * pyaaf2 installed; the honest-refuse path is exercised with a stub that exits like a missing
 * pyaaf2. All offline, no Resolve.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { editorialTool } from '../server/tools/editorial.mjs';
import { drtTool } from '../server/tools/drt.mjs';
import { drt } from '../server/libs.mjs';

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'aaf-seq-'));

function writeStub(name, body) {
  const p = path.join(TMP, name);
  fs.writeFileSync(p, body, { mode: 0o755 });
  fs.chmodSync(p, 0o755);
  return p;
}

const OK_SEQS = {
  ok: true,
  sequences: [
    {
      id: 'urn:mob:1',
      name: 'EP012 CONFORM',
      eventCount: 2,
      events: [
        { index: 1, track: 'V', source: 'A001', srcIn: 0, srcOut: 48, recIn: 0, recOut: 48, speed: 100, reverse: false, transition: null, fps: 24 },
        { index: 2, track: 'V', source: 'B002', srcIn: 0, srcOut: 24, recIn: 48, recOut: 72, speed: 100, reverse: false, transition: null, fps: 24 },
      ],
    },
    { id: 'urn:mob:2', name: 'EP012 BONUS', eventCount: 0, events: [] },
  ],
};

const STUB_OK = writeStub('py_ok.sh', `#!/bin/sh\ncat <<'JSON'\n${JSON.stringify(OK_SEQS)}\nJSON\n`);
const STUB_NO_PYAAF2 = writeStub('py_nopyaaf2.sh', '#!/bin/sh\necho "AAF_PROBE_NO_PYAAF2: not installed" 1>&2\nexit 3\n');

// A fake .aaf so the existence check passes (the stub ignores the bytes).
const FAKE_AAF = path.join(TMP, 'turnover.aaf');
fs.writeFileSync(FAKE_AAF, 'AAF\0binary');

test('parse_interchange aaf → real events via the pyaaf2 bridge (stubbed)', async () => {
  process.env.AAF_PROBE_PYTHON = STUB_OK;
  const r = await editorialTool.handler({ action: 'parse_interchange', args: { format: 'aaf', content: FAKE_AAF } });
  assert.equal(r.format, 'aaf');
  assert.equal(r.count, 2); // flattened across sequences
  assert.equal(r.events[0].source, 'A001');
  assert.equal(r.events[1].recIn, 48);
});

test('list_sequences aaf → per-sequence [{id,name,eventCount}] for the picker', async () => {
  process.env.AAF_PROBE_PYTHON = STUB_OK;
  const r = await editorialTool.handler({ action: 'list_sequences', args: { path: FAKE_AAF } });
  assert.equal(r.count, 2);
  assert.deepEqual(
    r.sequences.map((s) => [s.name, s.eventCount]),
    [
      ['EP012 CONFORM', 2],
      ['EP012 BONUS', 0],
    ],
  );
});

test('AAF honest-refuses when pyaaf2 is unavailable (no fake parse)', async () => {
  process.env.AAF_PROBE_PYTHON = STUB_NO_PYAAF2;
  await assert.rejects(() => editorialTool.handler({ action: 'parse_interchange', args: { format: 'aaf', content: FAKE_AAF } }), /pyaaf2/);
  delete process.env.AAF_PROBE_PYTHON;
});

test('AAF with an empty/whitespace path is an honest error', async () => {
  await assert.rejects(() => editorialTool.handler({ action: 'parse_interchange', args: { format: 'aaf', content: '   ' } }), /binary/);
});

test('parse_interchange prproj → parses offline now (missing file = honest read error)', async () => {
  // prproj is supported offline (see prproj-bridge.test.mjs); a bad path is an honest error, not a refuse.
  await assert.rejects(
    () => editorialTool.handler({ action: 'parse_interchange', args: { format: 'prproj', content: '/x/y.prproj' } }),
    /ENOENT|no such file/i,
  );
});

test('list_sequences edl → single sequence with event count', async () => {
  const edl = path.join(TMP, 'reel.edl');
  fs.writeFileSync(
    edl,
    'TITLE: R1\n001  A001 V C 01:00:00:00 01:00:04:00 01:00:00:00 01:00:04:00\n002  B002 V C 02:00:00:00 02:00:02:00 01:00:04:00 01:00:06:00\n',
  );
  const r = await editorialTool.handler({ action: 'list_sequences', args: { path: edl } });
  assert.equal(r.count, 1);
  assert.equal(r.sequences[0].eventCount, 2);
  assert.equal(r.sequences[0].name, 'reel.edl');
});

test('list_sequences otio → single sequence', async () => {
  const otioPath = path.join(TMP, 'cut.otio');
  const otio = {
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
              source_range: { start_time: { value: 0, rate: 24 }, duration: { value: 24, rate: 24 } },
            },
          ],
        },
      ],
    },
  };
  fs.writeFileSync(otioPath, JSON.stringify(otio));
  const r = await editorialTool.handler({ action: 'list_sequences', args: { path: otioPath } });
  assert.equal(r.sequences[0].eventCount, 1);
});

test('list_sequences prproj → supported offline (missing file = honest read error)', async () => {
  await assert.rejects(() => editorialTool.handler({ action: 'list_sequences', args: { path: '/x/proj.prproj' } }), /ENOENT|no such file/i);
});

test('list_sequences unknown extension → honest error', async () => {
  const f = path.join(TMP, 'mystery.bin');
  fs.writeFileSync(f, 'x');
  await assert.rejects(() => editorialTool.handler({ action: 'list_sequences', args: { path: f } }), /unknown extension/);
});

test('list_sequences drt → enumerates authored timelines', async () => {
  const spec = {
    timelines: [
      {
        name: 'T1',
        frameRate: 24,
        startTimecode: '01:00:00:00',
        resolution: '1920x1080',
        videoTracks: [
          {
            clips: [
              { start: 0, duration: 24, in: 0, mediaFilePath: '/m/c1.mov' },
              { start: 24, duration: 24, in: 0, mediaFilePath: '/m/c2.mov' },
            ],
          },
        ],
        audioTracks: [],
      },
      {
        name: 'T2',
        frameRate: 24,
        startTimecode: '01:00:00:00',
        resolution: '1920x1080',
        videoTracks: [{ clips: [{ start: 0, duration: 24, in: 0, mediaFilePath: '/m/c3.mov' }] }],
        audioTracks: [],
      },
    ],
    metadata: { source: 'test' },
  };
  const buf = await drt().buildDRT(spec);
  const drtPath = path.join(TMP, 'multi.drt');
  fs.writeFileSync(drtPath, buf);

  const viaEditorial = await editorialTool.handler({ action: 'list_sequences', args: { path: drtPath } });
  assert.equal(viaEditorial.count, 2);
  assert.deepEqual(
    viaEditorial.sequences.map((s) => s.name),
    ['T1', 'T2'],
  );
  assert.equal(viaEditorial.sequences[0].eventCount, 2);
  assert.equal(viaEditorial.sequences[1].eventCount, 1);

  // The drt tool's dedicated action returns the same shape (part 2a).
  const viaDrt = await drtTool.handler({ action: 'list_sequences', args: { drpPath: drtPath } });
  assert.deepEqual(
    viaDrt.sequences.map((s) => [s.name, s.eventCount, s.index]),
    viaEditorial.sequences.map((s) => [s.name, s.eventCount, s.index]),
  );
});

test('list_sequences drp → enumerates the template project', async () => {
  const r = await drtTool.handler({ action: 'list_sequences', args: { drpPath: 'vendor/drp-format/templates/media-clip-h264.drp' } });
  assert.ok(r.count >= 1);
  assert.equal(r.sequences[0].name, 'sample.mp4');
  assert.ok(typeof r.sequences[0].id === 'string' && r.sequences[0].id.length);
});
