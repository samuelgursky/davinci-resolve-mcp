/**
 * AAF offline preview (pyaaf2 bridge), unified list_sequences enumeration, and PrProj honest
 * refusal. The AAF path is exercised with a STUB "python" so the wiring is deterministic without
 * pyaaf2 installed; the honest-refuse path is exercised with a stub that exits like a missing
 * pyaaf2. All offline, no Resolve.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { editorialTool } from '../server/tools/editorial.mjs';
import { drtTool } from '../server/tools/drt.mjs';
import { drt } from '../server/libs.mjs';

const PROBE_PY = fileURLToPath(new URL('../server/aaf_probe.py', import.meta.url));

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

// ── aaf_probe.py segment walker (Avid multi-layer NestedScope) ─────────────────
// The walker dispatches purely on `type(x).__name__` and duck-typed attributes, and
// aaf_probe.py imports `aaf2` lazily (inside probe()/main()). So the structural logic
// is testable with a bare python3 and hand-built fakes — no pyaaf2, no .aaf fixture.
// This is the regression guard for the bug where an Avid multi-layer picture turnover
// (a NestedScope, which has `.slots` and NO `.components`) returned eventCount: 0
// while still reporting ok:true.

function python() {
  for (const cmd of [process.env.AAF_PROBE_TEST_PYTHON, 'python3', 'python']) {
    if (!cmd) continue;
    const probe = spawnSync(cmd, ['-c', 'import sys; print(sys.version_info[0])'], { encoding: 'utf8' });
    if (!probe.error && probe.status === 0 && probe.stdout.trim() === '3') return cmd;
  }
  return null;
}

const PY = python();

/** Run `script` with aaf_probe.py importable as `ap`; returns its parsed JSON stdout. */
function runWalker(script) {
  const head = [
    'import importlib.util, json',
    `spec = importlib.util.spec_from_file_location("ap", ${JSON.stringify(PROBE_PY)})`,
    'ap = importlib.util.module_from_spec(spec)',
    'spec.loader.exec_module(ap)',
    // Build a duck-typed AAF component whose python class NAME is what the walker keys on.
    'def mk(cls, **kw):',
    '    obj = type(cls, (object,), {})()',
    '    for k, v in kw.items(): setattr(obj, k, v)',
    '    return obj',
    'def clip(name, length, start=0):',
    '    mob = mk("MasterMob", name=name, mob_id="mob:" + name, slots=[])',
    '    return mk("SourceClip", length=length, start=start, mob=mob)',
    'def selector(sel, length):',
    '    s = mk("Selector", length=length)',
    '    s.getvalue = lambda key, _s=sel: _s if key == "Selected" else None',
    '    return s',
    'def opgroup(op, length, segments):',
    '    return mk("OperationGroup", length=length, segments=segments, operation=mk("Operation", name=op))',
    'def new_state(): return {"idx": 1, "events": [], "unhandled": {}}',
  ].join('\n');
  const r = spawnSync(PY, ['-c', `${head}\n${script}`], { encoding: 'utf8' });
  assert.equal(r.status, 0, `python walker harness failed: ${r.stderr}`);
  return JSON.parse(r.stdout);
}

test('aaf_probe: NestedScope picture slot → one numbered track per layer, each restarting at rec 0', { skip: PY ? false : 'python3 not available' }, () => {
  // THE BUG: NestedScope has `.slots`, not `.components`. The old walker fell back to
  // `[segment]`, matched no branch, and emitted nothing for the entire timeline.
  const out = runWalker(`
layers = [
    mk("Sequence", components=[clip("A001", 100), mk("Filler", length=50), clip("A002", 25)]),
    mk("Sequence", components=[mk("ScopeReference", length=30), clip("B001", 70)]),
    mk("Sequence", components=[clip("C001", 10)]),
]
scope = mk("NestedScope", length=175, slots=layers)
state = new_state()
ap._walk_slot(scope, prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  assert.deepEqual(
    out.events.map((e) => [e.index, e.track, e.source, e.recIn, e.recOut]),
    [
      [1, 'V1', 'A001', 0, 100], // layer 1 starts at 0
      [2, 'V1', 'A002', 150, 175], // ...after the 50f Filler gap
      [3, 'V2', 'B001', 30, 100], // layer 2 RESTARTS at 0, offset by its ScopeReference
      [4, 'V3', 'C001', 0, 10], // layer 3 restarts too — layers are parallel, not sequential
    ],
  );
  // Index stays monotonic across every layer of the mob.
  assert.deepEqual(
    out.events.map((e) => e.index),
    [1, 2, 3, 4],
  );
  assert.deepEqual(out.unhandled, {}, 'a fully-modelled timeline reports no structural misses');
});

test('aaf_probe: sound NestedScope numbers A1..An', { skip: PY ? false : 'python3 not available' }, () => {
  const out = runWalker(`
scope = mk("NestedScope", length=10, slots=[mk("Sequence", components=[clip("A001.wav", 10)]), mk("Sequence", components=[clip("A002.wav", 10)])])
state = new_state()
ap._walk_slot(scope, prefix="A", fps=48, state=state)
print(json.dumps(state))
`);
  assert.deepEqual(
    out.events.map((e) => e.track),
    ['A1', 'A2'],
  );
});

test('aaf_probe: OperationGroup descends through its nested Sequence (not just a direct SourceClip)', { skip: PY ? false : 'python3 not available' }, () => {
  // Avid wraps the real clip in OperationGroup > Sequence > SourceClip. The old branch
  // only looked for a DIRECT SourceClip in `.segments`, so effect-wrapped clips (the
  // overwhelming majority of a real turnover) were dropped.
  const out = runWalker(`
og = opgroup("PaintResize_v2", 40, [mk("Sequence", components=[clip("A001", 40)])])
retime = opgroup("Motion Control", 60, [mk("Sequence", components=[clip("A002", 60)])])
seq = mk("Sequence", components=[og, retime])
state = new_state()
ap._walk_slot(seq, prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  assert.deepEqual(
    out.events.map((e) => [e.source, e.recIn, e.recOut]),
    [
      ['A001', 0, 40],
      ['A002', 40, 100],
    ],
  );
  // A retime is flagged honestly — we can see an effect exists but not its ratio offline.
  assert.equal(out.events[0].effect, undefined);
  assert.equal(out.events[1].effect, 'Motion Control');
  assert.equal(out.events[1].speed, 100, 'speed is never fabricated from an effect name');
});

test('aaf_probe: Selector descends to its Selected variant; secondary effect inputs are kept', { skip: PY ? false : 'python3 not available' }, () => {
  const out = runWalker(`
sel = selector(opgroup("RGBColorCorrect_2", 30, [mk("Sequence", components=[clip("A001", 30)])]), 30)
blend = opgroup("SBlend_v2", 20, [mk("Sequence", components=[clip("BG", 20)]), mk("Sequence", components=[clip("FG", 20)])])
seq = mk("Sequence", components=[sel, blend])
state = new_state()
ap._walk_slot(seq, prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  assert.deepEqual(
    out.events.map((e) => [e.source, e.recIn, e.recOut]),
    [
      ['A001', 0, 30],
      ['BG', 30, 50],
      // The blend B-side is real referenced media; it shares the A-side's record span.
      ['FG', 30, 50],
    ],
  );
  assert.deepEqual(out.unhandled, {});
});

test('aaf_probe: an unmodelled component is COUNTED, not silently swallowed', { skip: PY ? false : 'python3 not available' }, () => {
  // The whole point of the fix: a structural miss must be visible rather than
  // masquerading as an empty timeline behind ok:true.
  const out = runWalker(`
seq = mk("Sequence", components=[clip("A001", 10), mk("EssenceGroup", length=20), mk("EssenceGroup", length=5), mk("Pulldown", length=7), clip("A002", 10)])
state = new_state()
ap._walk_slot(seq, prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  assert.deepEqual(out.unhandled, { EssenceGroup: 2, Pulldown: 1 });
  // Unknown components still advance record time, so later clips do not slide early.
  assert.deepEqual(
    out.events.map((e) => [e.source, e.recIn]),
    [
      ['A001', 0],
      ['A002', 42],
    ],
  );
});

test('aaf_probe: non-editorial slots are skipped by MEDIA KIND, not by segment class', { skip: PY ? false : 'python3 not available' }, () => {
  // Avid wraps timecode slots in a Pulldown (segment class "Pulldown", media_kind
  // "Timecode"), so a class-name-only skip let them through and they polluted both the
  // events and the unhandled counter.
  const out = runWalker(`
def slot(kind, segcls):
    return mk("TimelineMobSlot", media_kind=kind, segment=mk(segcls, length=100, media_kind=kind))
cases = [
    ("Timecode", "Timecode"), ("Timecode", "Pulldown"), ("Edgecode", "EdgeCode"),
    ("Descriptive Metadata", "Sequence"), ("SoundMasterTrack", "Sequence"),
    ("Picture", "NestedScope"), ("Sound", "Sequence"),
]
print(json.dumps([[k, c, ap._is_editorial_slot(slot(k, c)), ap._media_kind_to_track(slot(k, c))] for k, c in cases]))
`);
  assert.deepEqual(out, [
    ['Timecode', 'Timecode', false, 'V'],
    ['Timecode', 'Pulldown', false, 'V'], // the class-name-brittleness case
    ['Edgecode', 'EdgeCode', false, 'V'],
    ['Descriptive Metadata', 'Sequence', false, 'V'],
    ['SoundMasterTrack', 'Sequence', false, 'A'],
    ['Picture', 'NestedScope', true, 'V'],
    ['Sound', 'Sequence', true, 'A'],
  ]);
});

test('aaf_probe: source names chase Avid subclip indirection to the nearest NAMED mob', { skip: PY ? false : 'python3 not available' }, () => {
  // A timeline SourceClip points at an UNNAMED intermediate CompositionMob; the real
  // camera-roll name lives one hop further on the MasterMob. Stopping at `clip.mob.name`
  // reported "UNKNOWN" for the majority of a real turnover.
  const out = runWalker(`
master = mk("MasterMob", name="A001C001_240101_AB01.new.01", mob_id="mob:master", slots=[])
inner = mk("SourceClip", length=180, start=40, mob=master)
comp = mk("CompositionMob", name="", mob_id="mob:comp", slots=[mk("MobSlot", segment=mk("Sequence", components=[inner]))])
seq = mk("Sequence", components=[mk("SourceClip", length=180, start=40, mob=comp)])
state = new_state()
ap._walk_slot(seq, prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  assert.equal(out.events[0].source, 'A001C001_240101_AB01.new.01');
});

test('aaf_probe: an unresolvable source is UNKNOWN, never a fabricated name', { skip: PY ? false : 'python3 not available' }, () => {
  const out = runWalker(`
orphan = mk("SourceClip", length=10, start=0)
# pyaaf2 returns the CLASS NAME for an unset .name — that must not become a source.
named_as_class = mk("SourceClip", length=10, start=0, name="SourceClip")
state = new_state()
ap._walk_slot(mk("Sequence", components=[orphan, named_as_class]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  assert.deepEqual(
    out.events.map((e) => e.source),
    ['UNKNOWN', 'UNKNOWN'],
  );
});

test('aaf_probe: a reference cycle terminates instead of spinning', { skip: PY ? false : 'python3 not available' }, () => {
  const out = runWalker(`
a = mk("CompositionMob", name="", mob_id="mob:a", slots=[])
b = mk("CompositionMob", name="", mob_id="mob:b", slots=[])
a.slots = [mk("MobSlot", segment=mk("SourceClip", length=10, start=0, mob=b))]
b.slots = [mk("MobSlot", segment=mk("SourceClip", length=10, start=0, mob=a))]
state = new_state()
ap._walk_slot(mk("Sequence", components=[mk("SourceClip", length=10, start=0, mob=a)]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  assert.equal(out.events[0].source, 'UNKNOWN');
});

test('the bridge passes multi-layer tracks + the unhandled report through unchanged', async () => {
  const MULTI = {
    ok: true,
    sequences: [
      {
        id: 'urn:mob:9',
        name: 'PROD',
        eventCount: 3,
        unhandled: { EssenceGroup: 2 },
        events: [
          { index: 1, track: 'V1', source: 'A001', srcIn: 0, srcOut: 48, recIn: 0, recOut: 48, speed: 100, reverse: false, transition: null, fps: 23.976024 },
          { index: 2, track: 'V2', source: 'B002', srcIn: 0, srcOut: 24, recIn: 0, recOut: 24, speed: 100, reverse: false, transition: null, fps: 23.976024 },
          { index: 3, track: 'V3', source: 'C003', srcIn: 0, srcOut: 12, recIn: 8, recOut: 20, speed: 100, reverse: false, transition: null, fps: 23.976024 },
        ],
      },
    ],
  };
  const stub = writeStub('py_multi.sh', `#!/bin/sh\ncat <<'JSON'\n${JSON.stringify(MULTI)}\nJSON\n`);
  process.env.AAF_PROBE_PYTHON = stub;
  try {
    const r = await editorialTool.handler({ action: 'parse_interchange', args: { format: 'aaf', content: FAKE_AAF } });
    assert.equal(r.count, 3);
    assert.deepEqual(
      r.events.map((e) => e.track),
      ['V1', 'V2', 'V3'],
      'numbered per-layer tracks survive the bridge',
    );
    // Parallel layers legitimately overlap in record time — the bridge must not reorder
    // or dedupe them.
    assert.deepEqual(
      r.events.map((e) => e.recIn),
      [0, 0, 8],
    );
    const list = await editorialTool.handler({ action: 'list_sequences', args: { path: FAKE_AAF } });
    assert.equal(list.sequences[0].eventCount, 3);
  } finally {
    delete process.env.AAF_PROBE_PYTHON;
  }
});
