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
      startTimecode: '00:59:50:00',
      startFrame: 86160,
      startTimecodeFps: 24,
      startTimecodeDrop: false,
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

test('the sequence START TIMECODE survives the bridge on both entry points', async () => {
  // A conform that places events without it builds the timeline at Resolve's default
  // 01:00:00:00 while the AAF starts at 00:59:50:00 — every clip ten seconds out, and
  // only visible against a linked picture reference.
  process.env.AAF_PROBE_PYTHON = STUB_OK;
  try {
    const list = await editorialTool.handler({ action: 'list_sequences', args: { path: FAKE_AAF } });
    assert.deepEqual(
      list.sequences.map((s) => [s.startTimecode, s.startFrame, s.startTimecodeFps, s.startTimecodeDrop]),
      [
        ['00:59:50:00', 86160, 24, false],
        [null, null, null, null], // a sequence with no timecode slot says so explicitly
      ],
    );
    // parse_interchange flattens events across sequences, which cannot express a
    // per-sequence start — so it carries the summaries alongside.
    const parsed = await editorialTool.handler({ action: 'parse_interchange', args: { format: 'aaf', content: FAKE_AAF } });
    assert.equal(parsed.count, 2);
    assert.deepEqual(
      parsed.sequences.map((s) => [s.name, s.startTimecode, s.startFrame]),
      [
        ['EP012 CONFORM', '00:59:50:00', 86160],
        ['EP012 BONUS', null, null],
      ],
    );
  } finally {
    delete process.env.AAF_PROBE_PYTHON;
  }
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

// ── Motion Control retime ratio recovery (OperationGroup parameters) ───────────
// Avid stores the retime ratio on the OperationGroup's PARAMETERS. "SpeedRatio"
// (AAF Edit Protocol) is a rational RECORD/SOURCE length ratio — the INVERSE of the
// play rate (a stored 1/2 = 100 record frames consume 200 source frames = 200%
// fast motion; negative = reverse). Avid's PARAM_*_U parameters store play-rate
// scalars directly. Verified against real Media Composer turnovers by cross-checking
// source-vs-record lengths and PARAM_SPEED_MAP_U control points.

test('aaf_probe: Motion Control constant SpeedRatio → recovered play rate + honest record span', { skip: PY ? false : 'python3 not available' }, () => {
  const out = runWalker(`
from fractions import Fraction
# 200% fast motion: 100 source frames render into 50 record frames → stored 1/2.
fast = opgroup("Motion Control", 50, [mk("Sequence", components=[clip("A001", 100)])])
fast.parameters = [mk("ConstantValue", name="SpeedRatio", value=Fraction(1, 2))]
# 100% reverse: stored -1/1. Source and record spans are equal.
rev = opgroup("Motion Control", 40, [mk("Sequence", components=[clip("A002", 40)])])
rev.parameters = [mk("ConstantValue", name="SpeedRatio", value=Fraction(-1, 1))]
seq = mk("Sequence", components=[fast, rev, clip("B001", 25)])
state = new_state()
ap._walk_slot(seq, prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  assert.deepEqual(
    out.events.map((e) => [e.source, e.srcIn, e.srcOut, e.recIn, e.recOut, e.speed, e.speedRatio, e.reverse]),
    [
      // srcIn/srcOut keep the SOURCE-side range; recOut spans the group's RECORD length.
      ['A001', 0, 100, 0, 50, 200, 2.0, false],
      ['A002', 0, 40, 50, 90, 100, 1.0, true],
      ['B001', 0, 25, 90, 115, 100, undefined, false],
    ],
  );
  assert.equal(out.events[0].effect, 'Motion Control');
  assert.equal(out.events[2].effect, undefined);
  assert.deepEqual(out.unhandled, {});
});

test('aaf_probe: variable-speed timewarp → speedVarying, never a fabricated number', { skip: PY ? false : 'python3 not available' }, () => {
  const out = runWalker(`
from fractions import Fraction
og = opgroup("Motion Control", 193, [mk("Sequence", components=[clip("A001", 181)])])
og.parameters = [
    # Even with a constant SpeedRatio present, a speed map with more than one
    # distinct value proves the speed VARIES — the map wins and no single ratio
    # is reported.
    mk("ConstantValue", name="SpeedRatio", value=Fraction(800, 1001)),
    mk("VaryingValue", name="PARAM_SPEED_MAP_U", pointlist=[
        mk("ControlPoint", time=0.0, value=0.5),
        mk("ControlPoint", time=90.0, value=1.0),
        mk("ControlPoint", time=193.0, value=1.0),
    ]),
]
state = new_state()
ap._walk_slot(mk("Sequence", components=[og]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  const [ev] = out.events;
  assert.equal(ev.speedVarying, true);
  assert.equal(ev.speedRatio, undefined, 'a varying retime must not carry a single fabricated ratio');
  assert.equal(ev.speed, 100, 'speed stays at the honest default for a varying retime');
  assert.equal(ev.effect, 'Motion Control');
  assert.deepEqual([ev.srcIn, ev.srcOut, ev.recIn, ev.recOut], [0, 181, 0, 193]);
});

test('aaf_probe: retime with no readable parameters → unchanged flag-only contract', { skip: PY ? false : 'python3 not available' }, () => {
  const out = runWalker(`
og = opgroup("Motion Control", 60, [mk("Sequence", components=[clip("A002", 60)])])
state = new_state()
ap._walk_slot(mk("Sequence", components=[og]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  const [ev] = out.events;
  assert.equal(ev.effect, 'Motion Control');
  assert.equal(ev.speed, 100);
  assert.equal(ev.speedRatio, undefined, 'no parameters → no ratio is invented');
  assert.equal(ev.speedVarying, undefined, 'absence of evidence is not evidence of varying');
  assert.deepEqual([ev.recIn, ev.recOut], [0, 60]);
});

test('aaf_probe: OperationGroup declared length drives the record span (slow motion extends it)', { skip: PY ? false : 'python3 not available' }, () => {
  const out = runWalker(`
from fractions import Fraction
# 50% slow motion: 50 source frames fill 100 record frames → stored 2/1.
slow = opgroup("Motion Control", 100, [mk("Sequence", components=[clip("A001", 50)])])
slow.parameters = [mk("ConstantValue", name="SpeedRatio", value=Fraction(2, 1))]
seq = mk("Sequence", components=[slow, clip("B001", 10)])
state = new_state()
ap._walk_slot(seq, prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  assert.deepEqual(
    out.events.map((e) => [e.source, e.srcOut, e.recIn, e.recOut, e.speed]),
    [
      // Before the fix recOut advanced by the SOURCE length (50), so slow motion
      // undershot and fast motion inflated the record span — every measured
      // record-overlap on a real turnover involved a Motion Control event.
      ['A001', 50, 0, 100, 50],
      ['B001', 10, 100, 110, 100],
    ],
  );
  assert.equal(out.events[0].speedRatio, 0.5);
});

test('aaf_probe: Avid *_U parameter variants store play rates directly', { skip: PY ? false : 'python3 not available' }, () => {
  const out = runWalker(`
# PARAM_SPEED_RATIO_U is a play-rate scalar (same family as the speed map), NOT a
# record/source rational — it must not be inverted.
a = opgroup("Motion Control", 100, [mk("Sequence", components=[clip("A001", 175)])])
a.parameters = [mk("ConstantValue", name="PARAM_SPEED_RATIO_U", value=1.75)]
# A flat single-point speed map is a constant retime; its value is the play rate.
b = opgroup("Motion Control", 80, [mk("Sequence", components=[clip("A002", 80)])])
b.parameters = [mk("VaryingValue", name="PARAM_SPEED_MAP_U", pointlist=[mk("ControlPoint", time=0.0, value=-1.0)])]
seq = mk("Sequence", components=[a, b])
state = new_state()
ap._walk_slot(seq, prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  assert.deepEqual(
    out.events.map((e) => [e.source, e.speed, e.speedRatio, e.reverse, e.recIn, e.recOut]),
    [
      ['A001', 175, 1.75, false, 0, 100],
      ['A002', 100, 1.0, true, 100, 180],
    ],
  );
});

// ── Transitions subtract from record advancement ──────────────────────────────
// AAF Edit Protocol: a Transition OVERLAPS its neighbours rather than occupying record
// time of its own, so sequence length == sum(components) - sum(transitions). The walker
// annotated the following clip but never rewound `rec`, leaving every later event on
// that track late by the CUMULATIVE transition time. On a real Avid turnover a single
// 59-frame dissolve put 651 subsequent V1 events 59 frames past Resolve's own native
// import of the same file — silent, track-local, invisible without a dissolve.

test('aaf_probe: a transition pulls every LATER event earlier by its duration', { skip: PY ? false : 'python3 not available' }, () => {
  const out = runWalker(`
seq = mk("Sequence", components=[
    clip("A001", 100), mk("Transition", length=20), clip("A002", 50), clip("A003", 30),
])
state = new_state()
walked = ap._walk_segment(seq, track="V", fps=24, rec=0, state=state, depth=0)
print(json.dumps({"events": state["events"], "walked": walked}))
`);
  assert.deepEqual(
    out.events.map((e) => [e.source, e.recIn, e.recOut]),
    [
      ['A001', 0, 100],
      ['A002', 80, 130], // rewound by the 20f dissolve — it overlaps A001's tail
      ['A003', 130, 160], // and every later cut inherits the shift
    ],
  );
  // The declared-length cross-check: 100 + 50 + 30 - 20.
  assert.equal(out.walked, 160, 'sequence length == sum(components) - sum(transitions)');
  // The clip AFTER the transition is still the one annotated with it.
  assert.deepEqual(out.events[1].transition, { type: 'dissolve', duration: 20, alignment: 'start' });
  assert.equal(out.events[0].transition, null);
  assert.equal(out.events[2].transition, null);
});

test('aaf_probe: transitions are PER-TRACK — a dissolve on one layer never moves another', { skip: PY ? false : 'python3 not available' }, () => {
  // The measured failure mode was track-local: V1's dissolve shifted only V1, so a
  // conform checked on any other track looked perfectly aligned.
  const out = runWalker(`
layers = [
    mk("Sequence", components=[clip("A001", 100), mk("Transition", length=30), clip("A002", 100)]),
    mk("Sequence", components=[clip("B001", 100), clip("B002", 100)]),
    mk("Sequence", components=[clip("C001", 40), mk("Transition", length=10), clip("C002", 40), mk("Transition", length=5), clip("C003", 40)]),
]
state = new_state()
ap._walk_slot(mk("NestedScope", length=200, slots=layers), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  assert.deepEqual(
    out.events.map((e) => [e.track, e.source, e.recIn]),
    [
      ['V1', 'A001', 0],
      ['V1', 'A002', 70], // shifted by V1's own 30f dissolve
      ['V2', 'B001', 0],
      ['V2', 'B002', 100], // untouched — no dissolve on this layer
      ['V3', 'C001', 0],
      ['V3', 'C002', 30], // -10
      ['V3', 'C003', 65], // -10 -5, cumulative down the track
    ],
  );
});

test('aaf_probe: a transition at the head clamps — and is a fade-in from black (E93)', { skip: PY ? false : 'python3 not available' }, () => {
  // A leading transition has no preceding material to overlap: the rewind
  // clamps at the sequence start, and since the sequence head counts as
  // black, a zero-length BL pseudo-event materializes the fade-in side for
  // the bridge's black machinery.
  const out = runWalker(`
seq = mk("Sequence", components=[mk("Transition", length=25), clip("A001", 50), clip("A002", 10)])
state = new_state()
walked = ap._walk_segment(seq, track="V", fps=24, rec=0, state=state, depth=0)
print(json.dumps({"events": state["events"], "walked": walked}))
`);
  assert.deepEqual(
    out.events.map((e) => [e.source, e.recIn, e.recOut]),
    [
      ['BL', 0, 0],
      ['A001', 0, 50],
      ['A002', 50, 60],
    ],
  );
  assert.equal(out.walked, 60, 'the clamp does not let the rewind escape the sequence start');
  assert.equal(out.events[0].transition, null);
  assert.deepEqual(out.events[1].transition, { type: 'dissolve', duration: 25, alignment: 'start' });
});

test('aaf_probe: back-to-back clips are unaffected by the subtraction', { skip: PY ? false : 'python3 not available' }, () => {
  // The regression guard in the other direction: a dissolve-free track must still lay
  // components strictly end to end.
  const out = runWalker(`
seq = mk("Sequence", components=[clip("A001", 40), clip("A002", 60), mk("Filler", length=10), clip("A003", 25)])
state = new_state()
walked = ap._walk_segment(seq, track="V", fps=24, rec=0, state=state, depth=0)
print(json.dumps({"events": state["events"], "walked": walked}))
`);
  assert.deepEqual(
    out.events.map((e) => [e.source, e.recIn, e.recOut]),
    [
      ['A001', 0, 40],
      ['A002', 40, 100],
      ['A003', 110, 135],
    ],
  );
  assert.equal(out.walked, 135);
  assert.deepEqual(
    out.events.map((e) => e.transition),
    [null, null, null],
  );
});

// ── Sequence start timecode ───────────────────────────────────────────────────
// Avid writes one Timecode slot PER COMMON RATE, all naming the same wall-clock start
// (a real turnover carried seven: 86160@24, 89750@25, 107592@30drop, 107700@30,
// 215400@60 — every one of them 00:59:50:00). They agree on the string and disagree on
// the frame number, so picking "the first one" hands back a frame count in a rate the
// rest of the parse never uses.

test('aaf_probe: the timecode slot matching the EDIT RATE wins, not the first one', { skip: PY ? false : 'python3 not available' }, () => {
  const out = runWalker(`
def tc(start, fps, drop=False):
    return mk("Timecode", start=start, fps=fps, drop=drop, media_kind="Timecode")
def slot(seg, kind="Timecode"):
    return mk("TimelineMobSlot", media_kind=kind, segment=seg)
# Same wall-clock start (00:59:50:00) expressed at five different rates, with the
# 25fps slot deliberately FIRST so "take the first" would pick the wrong frame count.
slots = [slot(tc(89750, 25)), slot(tc(86160, 24)), slot(tc(107592, 30, True)),
         slot(tc(107700, 30)), slot(tc(215400, 60)),
         slot(mk("NestedScope", length=10, slots=[]), kind="Picture")]
m = mk("CompositionMob", slots=slots)
print(json.dumps({
    "at24": ap._sequence_start_timecode(m, 23.976024),
    "at25": ap._sequence_start_timecode(m, 25.0),
    "at30": ap._sequence_start_timecode(m, 29.97),
    "at60": ap._sequence_start_timecode(m, 59.94),
    "no_rate_hint": ap._sequence_start_timecode(m, None),
}))
`);
  // Every slot names the same instant; only the frame number and rate differ.
  assert.deepEqual(out.at24, { startTimecode: '00:59:50:00', startFrame: 86160, startTimecodeFps: 24, startTimecodeDrop: false });
  assert.deepEqual(out.at25, { startTimecode: '00:59:50:00', startFrame: 89750, startTimecodeFps: 25, startTimecodeDrop: false });
  // 29.97 drop-frame renumbers, so the SAME instant is a different frame count and
  // prints with a ';' separator.
  assert.deepEqual(out.at30, { startTimecode: '00:59:50;00', startFrame: 107592, startTimecodeFps: 30, startTimecodeDrop: true });
  assert.deepEqual(out.at60, { startTimecode: '00:59:50:00', startFrame: 215400, startTimecodeFps: 60, startTimecodeDrop: false });
  // With no editorial rate to match, fall back to the first readable slot — and say
  // which rate the frame number is in, so the mismatch cannot hide.
  assert.deepEqual(out.no_rate_hint, { startTimecode: '00:59:50:00', startFrame: 89750, startTimecodeFps: 25, startTimecodeDrop: false });
});

test('aaf_probe: a timecode slot wrapped in a Pulldown is still found', { skip: PY ? false : 'python3 not available' }, () => {
  // Avid wraps the rate-converted views in a Pulldown, and pyaaf2 exposes the wrapped
  // segment as the InputSegment PROPERTY — not as an attribute.
  const out = runWalker(`
def tc(start, fps, drop=False):
    return mk("Timecode", start=start, fps=fps, drop=drop, media_kind="Timecode")
def pulldown_prop(inner):
    p = mk("Pulldown", media_kind="Timecode")
    type(p).__getitem__ = lambda self, k, _i=inner: mk("Prop", value=_i) if k == "InputSegment" else None
    return p
def pulldown_getvalue(inner):
    p = mk("Pulldown", media_kind="Timecode")
    p.getvalue = lambda k, _i=inner: _i if k == "InputSegment" else None
    return p
def slot(seg): return mk("TimelineMobSlot", media_kind="Timecode", segment=seg)
print(json.dumps({
    "prop": ap._sequence_start_timecode(mk("CompositionMob", slots=[slot(pulldown_prop(tc(86160, 24)))]), 24),
    "getvalue": ap._sequence_start_timecode(mk("CompositionMob", slots=[slot(pulldown_getvalue(tc(86160, 24)))]), 24),
    "in_sequence": ap._sequence_start_timecode(mk("CompositionMob", slots=[slot(mk("Sequence", components=[tc(86160, 24)]))]), 24),
}))
`);
  for (const key of ['prop', 'getvalue', 'in_sequence']) {
    assert.equal(out[key].startTimecode, '00:59:50:00', `${key} unwraps to the Timecode component`);
    assert.equal(out[key].startFrame, 86160);
  }
});

test('aaf_probe: an AAF with no timecode slot emits nulls, never a guessed 01:00:00:00', { skip: PY ? false : 'python3 not available' }, () => {
  const out = runWalker(`
picture = mk("TimelineMobSlot", media_kind="Picture", segment=mk("NestedScope", length=10, slots=[]))
# An unreadable Timecode (no usable start) must not become a fabricated zero either.
broken = mk("TimelineMobSlot", media_kind="Timecode", segment=mk("Timecode", start=None, fps=24, drop=False))
print(json.dumps({
    "none": ap._sequence_start_timecode(mk("CompositionMob", slots=[picture]), 24),
    "broken": ap._sequence_start_timecode(mk("CompositionMob", slots=[picture, broken]), 24),
    "zero_is_real": ap._sequence_start_timecode(
        mk("CompositionMob", slots=[mk("TimelineMobSlot", media_kind="Timecode", segment=mk("Timecode", start=0, fps=24, drop=False))]), 24),
}))
`);
  const nulls = { startTimecode: null, startFrame: null, startTimecodeFps: null, startTimecodeDrop: null };
  assert.deepEqual(out.none, nulls, 'no timecode slot → explicit nulls, not an omitted key');
  assert.deepEqual(out.broken, nulls, 'an unreadable timecode is absent, not zero');
  // A genuine 00:00:00:00 start is data, not a missing value — it must survive.
  assert.deepEqual(out.zero_is_real, { startTimecode: '00:00:00:00', startFrame: 0, startTimecodeFps: 24, startTimecodeDrop: false });
});

test('aaf_probe: drop-frame timecode renumbers rather than rescaling', { skip: PY ? false : 'python3 not available' }, () => {
  // Drop-frame skips two frame NUMBERS a minute (four at 60) except every tenth minute.
  // It never drops a picture frame, so the same frame count means a later wall clock.
  const out = runWalker(`
cases = [(0, 30, True), (1799, 30, True), (1800, 30, True), (17982, 30, True), (107592, 30, True),
         (107592, 30, False), (86160, 24, False), (0, 24, False), (215400, 60, False),
         (215184, 60, True), (86400*24, 24, False)]
print(json.dumps([[f, r, d, ap._frames_to_timecode(f, r, d)] for f, r, d in cases]))
`);
  assert.deepEqual(out, [
    [0, 30, true, '00:00:00;00'],
    [1799, 30, true, '00:00:59;29'], // minute 0 drops nothing — all 1800 labels are used
    [1800, 30, true, '00:01:00;02'], // ...then ;00 and ;01 of minute 1 do not exist
    [17982, 30, true, '00:10:00;00'], // the tenth minute drops nothing — back in step
    [107592, 30, true, '00:59:50;00'],
    [107592, 30, false, '00:59:46:12'], // same frames, non-drop → an earlier clock
    [86160, 24, false, '00:59:50:00'],
    [0, 24, false, '00:00:00:00'],
    [215400, 60, false, '00:59:50:00'],
    [215184, 60, true, '00:59:50;00'], // 60-family drops FOUR numbers a minute
    [86400 * 24, 24, false, '00:00:00:00'], // 24h wraps rather than printing hour 24
  ]);
});

// ── Per-clip geometry (Avid transform OperationGroups) ─────────────────────────
// The data behind Resolve's "Use sizing information" import option. Census of a real
// 878-event Avid turnover: PaintResize_v2 (285) carries scale/position/crop,
// SpatialAdapter (90) carries the source and framing rectangles, FlipHoriz_2 (10) is a
// flip. Scale is PROVEN to be a percent (212 of 285 groups sit at exactly 100 =
// identity); the units of position/crop and the absolute rectangle unit are NOT proven,
// so those pass through raw under Avid's own names — the SpeedRatio lesson, which was
// stored as the INVERSE of play rate and would have shipped inverted as a "normalized"
// field.

test('aaf_probe: PaintResize scale is a percent; unproven units keep their Avid names', { skip: PY ? false : 'python3 not available' }, () => {
  const out = runWalker(`
from fractions import Fraction
og = opgroup("PaintResize_v2", 40, [mk("Sequence", components=[clip("A001", 40)])])
og.parameters = [
    mk("ConstantValue", name="AFX_SCALE_X_U", value=Fraction(110, 1)),
    mk("ConstantValue", name="AFX_SCALE_Y_U", value=Fraction(110, 1)),
    mk("ConstantValue", name="AFX_POS_X_U", value=Fraction(479999999, 10000000)),
    mk("ConstantValue", name="AFX_POS_Y_U", value=Fraction(0, 1)),
    mk("ConstantValue", name="AFX_CROP_LEFT_U", value=Fraction(360, 1)),
    mk("ConstantValue", name="AFX_FIXED_ASPECT_U", value=True),
    # Colour/blend parameters ride on the same group and must not leak into geometry.
    mk("ConstantValue", name="AFX_BG_H_U", value=Fraction(0, 1)),
    mk("ConstantValue", name="AvidParameterByteOrder", value=18761),
]
state = new_state()
ap._walk_slot(mk("Sequence", components=[og]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  const [ev] = out.events;
  assert.deepEqual(ev.geometry, [
    {
      effect: 'PaintResize_v2',
      scalePercentX: 110.0,
      scalePercentY: 110.0,
      // Raw, under Avid's own parameter names — no invented "position in frame widths".
      params: { AFX_CROP_LEFT_U: 360.0, AFX_FIXED_ASPECT_U: true, AFX_POS_X_U: 48.0, AFX_POS_Y_U: 0.0 },
    },
  ]);
  assert.equal(ev.effect, undefined, 'a resize is not a retime — it must not set the retime fields');
  assert.equal(ev.speed, 100);
});

test('aaf_probe: SpatialAdapter rectangles yield a unit-free reformat ratio', { skip: PY ? false : 'python3 not available' }, () => {
  // The rectangles arrive as _NUM/_DEN rational pairs and share one (unknown) unit, so
  // their RATIO is the only unit-free quantity — and it is the one that matters: a
  // 2.39:1 source reformatted into a 16:9 framing is the letterbox the reference showed.
  const out = runWalker(`
og = opgroup("SpatialAdapter", 30, [mk("Sequence", components=[clip("A001", 30)])])
og.parameters = [
    mk("ConstantValue", name="AFX_SPATIAL_SOURCE_WID_NUM", value=5120),
    mk("ConstantValue", name="AFX_SPATIAL_SOURCE_WID_DEN", value=3),
    mk("ConstantValue", name="AFX_SPATIAL_SOURCE_HEI_NUM", value=715),
    mk("ConstantValue", name="AFX_SPATIAL_SOURCE_HEI_DEN", value=1),
    mk("ConstantValue", name="AFX_SPATIAL_FRAMING_WID_NUM", value=11440),
    mk("ConstantValue", name="AFX_SPATIAL_FRAMING_WID_DEN", value=9),
    mk("ConstantValue", name="AFX_SPATIAL_FRAMING_HEI_NUM", value=715),
    mk("ConstantValue", name="AFX_SPATIAL_FRAMING_HEI_DEN", value=1),
    mk("ConstantValue", name="AFX_SPATIAL_REFORMAT", value=-1),
    mk("ConstantValue", name="AFX_SPATIAL_LOCK_ASPECT", value=True),
]
state = new_state()
ap._walk_slot(mk("Sequence", components=[og]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  assert.deepEqual(out.events[0].geometry, [
    {
      effect: 'SpatialAdapter',
      rect: {
        AFX_SPATIAL_FRAMING_HEI: 715.0,
        AFX_SPATIAL_FRAMING_WID: 1271.111111,
        AFX_SPATIAL_SOURCE_HEI: 715.0,
        AFX_SPATIAL_SOURCE_WID: 1706.666667,
      },
      reformatScaleX: 0.744792, // 2.39:1 squeezed into a 16:9 framing
      reformatScaleY: 1.0, // full height retained — i.e. pillarbox, not crop
      params: { AFX_SPATIAL_LOCK_ASPECT: true, AFX_SPATIAL_REFORMAT: -1.0 },
    },
  ]);
});

test('aaf_probe: nested transform groups stack innermost-first, never collapse', { skip: PY ? false : 'python3 not available' }, () => {
  // 84 of the fixture's clips are a SpatialAdapter wrapped in a PaintResize. A single
  // `geometry` field would have silently dropped one stage of the transform.
  const out = runWalker(`
from fractions import Fraction
inner = opgroup("SpatialAdapter", 30, [mk("Sequence", components=[clip("A001", 30)])])
inner.parameters = [mk("ConstantValue", name="AFX_SCALE_X_U", value=Fraction(744, 10))]
outer = opgroup("PaintResize_v2", 30, [mk("Sequence", components=[inner])])
outer.parameters = [mk("ConstantValue", name="AFX_SCALE_X_U", value=Fraction(100, 1))]
flip = opgroup("FlipHoriz_2", 20, [mk("Sequence", components=[clip("A002", 20)])])
state = new_state()
ap._walk_slot(mk("Sequence", components=[outer, flip]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  assert.deepEqual(
    out.events[0].geometry.map((g) => [g.effect, g.scalePercentX]),
    [
      ['SpatialAdapter', 74.4], // innermost applies first...
      ['PaintResize_v2', 100.0], // ...and the walk annotates on the way back out
    ],
  );
  assert.deepEqual(out.events[1].geometry, [{ effect: 'FlipHoriz_2', flipHorizontal: true }]);
});

test('aaf_probe: an ANIMATED transform is named, never flattened to one number', { skip: PY ? false : 'python3 not available' }, () => {
  // Same rule as the variable-speed timewarp: a parameter with more than one distinct
  // control-point value has no single honest value. A FLAT point list is a constant.
  const out = runWalker(`
og = opgroup("PaintResize_v2", 50, [mk("Sequence", components=[clip("A001", 50)])])
og.parameters = [
    mk("VaryingValue", name="AFX_POS_X_U", pointlist=[
        mk("ControlPoint", value=-42.0), mk("ControlPoint", value=0.0)]),
    mk("VaryingValue", name="AFX_SCALE_X_U", pointlist=[
        mk("ControlPoint", value=110.0), mk("ControlPoint", value=110.0)]),
    mk("VaryingValue", name="AFX_CROP_TOP_U", pointlist=[mk("ControlPoint", value=0.0)]),
]
state = new_state()
ap._walk_slot(mk("Sequence", components=[og]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  const [geo] = out.events[0].geometry;
  assert.deepEqual(geo.varying, ['AFX_POS_X_U'], 'the animated parameter is named');
  assert.equal(geo.params?.AFX_POS_X_U, undefined, 'and carries no fabricated single value');
  // A point list whose values are all equal IS a constant — same rule as the speed map.
  assert.equal(geo.scalePercentX, 110.0);
  assert.equal(geo.params.AFX_CROP_TOP_U, 0.0);
});

test('aaf_probe: non-transform effects carry no geometry at all', { skip: PY ? false : 'python3 not available' }, () => {
  const out = runWalker(`
from fractions import Fraction
cc = opgroup("RGBColorCorrect_2", 30, [mk("Sequence", components=[clip("A001", 30)])])
cc.parameters = [mk("ConstantValue", name="AFX_SCALE_X_U", value=Fraction(110, 1))]
retime = opgroup("Motion Control", 50, [mk("Sequence", components=[clip("A002", 100)])])
retime.parameters = [mk("ConstantValue", name="SpeedRatio", value=Fraction(1, 2))]
state = new_state()
ap._walk_slot(mk("Sequence", components=[cc, retime]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  // A colour corrector is not a transform, even when it happens to carry a scale param.
  assert.equal(out.events[0].geometry, undefined);
  // And a retime keeps its own contract, untouched by the geometry pass.
  assert.equal(out.events[1].geometry, undefined);
  assert.equal(out.events[1].speed, 200);
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

// ── Physical source position + timecode (the consolidated-media trap) ─────────
//
// MEASURED on a consolidated Avid turnover (2026-08-05): a SourceClip's own
// `start` is an offset into whatever it references DIRECTLY. For consolidated
// media that is a per-cut fragment with handles, so 774 of 878 events reported
// srcIn <= 45 and one take used 13 times reported srcIn 40 THIRTEEN TIMES. A
// consumer placing those numbers against camera originals puts every clip on
// the right cut of the right take showing the wrong moment — and the number
// FITS inside the file, so no range check can catch it.
//
// The chase sums `start` down the mob chain and reads the nearest mob timecode.
// Verified frame-exact against the turnover's own picture reference: the probe
// says 21:19:28:21 at the frame the reference burned 21:19:28:21.

test('aaf_probe: srcPos/srcTc chase the mob chain to the PHYSICAL source, not the fragment', { skip: PY ? false : 'python3 not available' }, () => {
  const out = runWalker(`
def tc_slot(start, rate=24, drop=False):
    tc = mk("Timecode", start=start, fps=rate, drop=drop)
    slot = mk("TimelineMobSlot", segment=tc, media_kind="timecode")
    slot.getvalue = lambda key: None
    return slot

def picture_slot(segment):
    slot = mk("TimelineMobSlot", segment=segment, media_kind="picture")
    slot.getvalue = lambda key: None
    return slot

# (1) camera original — the media mob's own timeline IS its timecode timeline
# (tc start 0), so the chased position reads out directly as source TC. This is
# the measured shape: srcIn 40 on the fragment, 1,752,142 in the take.
original = mk("SourceMob", name="A001C001", mob_id="mob:orig", slots=[tc_slot(0)])
inner = mk("SourceClip", length=999999, start=1752102, mob=original)
fragment = mk("MasterMob", name="A001C001.new.01", mob_id="mob:frag", slots=[picture_slot(inner)])
cut_a = mk("SourceClip", length=196, start=40, mob=fragment)

# (2) archival file with no real timecode — Avid stamps 01:00:00:00 (86400 @24)
# and the position is an offset from there.
arch = mk("SourceMob", name="ARCHIVE_0001", mob_id="mob:arch", slots=[tc_slot(86400)])
arch_inner = mk("SourceClip", length=99999, start=200, mob=arch)
arch_frag = mk("MasterMob", name="ARCHIVE_0001.new.01", mob_id="mob:archfrag", slots=[picture_slot(arch_inner)])
cut_b = mk("SourceClip", length=47, start=40, mob=arch_frag)

state = new_state()
ap._walk_slot(mk("Sequence", components=[cut_a, cut_b]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  const [a, b] = out.events;

  // srcIn keeps its old meaning — fragment-relative, unchanged, back-compatible.
  assert.equal(a.srcIn, 40);
  assert.equal(b.srcIn, 40);
  // …and the two clips, INDISTINGUISHABLE by srcIn, separate completely once the
  // chain is chased. This is the whole point.
  assert.equal(a.srcPos, 1752142, 'srcPos sums every hop: 40 + 1,752,102');
  assert.equal(b.srcPos, 240, '40 + 200');
  assert.equal(a.srcTcFrame, 1752142);
  assert.equal(a.srcTc, '20:16:45:22');
  assert.equal(b.srcTcFrame, 86640, "the archival mob's own 01:00:00:00 origin + 240");
  assert.equal(b.srcTc, '01:00:10:00');
  assert.equal(a.srcTcFps, 24);
  assert.equal(a.srcTcDrop, false);
});

test('aaf_probe: a clip whose chain goes nowhere reports NO source position — never a guess', { skip: PY ? false : 'python3 not available' }, () => {
  // A bare MasterMob with no inner source clip and no timecode slot: the chase
  // finds nothing, so nothing is emitted. Silence here is the honest answer —
  // restating srcIn as srcPos would manufacture a physical position we never read.
  const out = runWalker(`
state = new_state()
ap._walk_slot(mk("Sequence", components=[clip("A001", 100, start=40)]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  const e = out.events[0];
  assert.equal(e.srcIn, 40);
  assert.ok(!('srcPos' in e), 'no srcPos when the chain adds nothing');
  assert.ok(!('srcTcFrame' in e), 'no source timecode when no mob carries one');
});

// ── Keyframes (U21) ───────────────────────────────────────────────────────────
// Until U21 a VaryingValue was read for its VALUES only, to answer "constant or
// not". `ControlPoint.time` was never asked for, so an animated reframe reached a
// consumer as the bare word "varying" — enough to refuse the clip, never enough to
// rebuild it. These pin the two time domains, which are NOT the same and whose
// confusion would be wrong by the effect's whole length.

test('aaf_probe: a transform curve carries time, value, and frame — domain (length - 1)', { skip: PY ? false : 'python3 not available' }, () => {
  // Measured over all 1254 geometry control points of a real Avid turnover: 1243
  // land on an integer frame under (length - 1) and only 278 under (length), so the
  // two are distinguishable and the endpoint is INCLUSIVE. This is that clip:
  // length 131, times 0.338461538 / 0.515384615 → frames 44 and 67 exactly.
  const out = runWalker(`
og = opgroup("PaintResize_v2", 131, [mk("Sequence", components=[clip("A001", 131)])])
og.parameters = [
    mk("VaryingValue", name="AFX_POS_X_U",
       interpolationdef=mk("InterpolationDefinition", name="LinearInterp"),
       pointlist=[mk("ControlPoint", time=0.338461538, value=-42.0),
                  mk("ControlPoint", time=0.515384615, value=0.0)]),
]
state = new_state()
ap._walk_slot(mk("Sequence", components=[og]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  const [geo] = out.events[0].geometry;
  assert.deepEqual(geo.varying, ['AFX_POS_X_U'], 'the old contract is untouched — consumers gate on it');
  assert.deepEqual(geo.keyframes.AFX_POS_X_U, {
    domain: 'effectSpan',
    points: [
      { t: 0.338461538, v: -42.0, frame: 44.0 },
      { t: 0.515384615, v: 0.0, frame: 67.0 },
    ],
    interpolation: 'LinearInterp',
    effectLength: 131,
  });
});

test('aaf_probe: keys outside the trimmed range are KEPT, and a half-frame key stays half', { skip: PY ? false : 'python3 not available' }, () => {
  // 107 of the fixture's 1254 keys sit before frame 0 or past the last frame —
  // what Avid leaves behind when a clip is trimmed after it was animated. Clamping
  // them would silently move the animation. And one real key lands at frame 125.5.
  // Length 180 and t=0.7011173184357542 are the real ones: they are the single key
  // in the whole fixture that lands on neither denominator as an integer, because
  // it is genuinely at frame 125.5. Under (length - 1) it renders exactly.
  const out = runWalker(`
og = opgroup("PaintResize_v2", 180, [mk("Sequence", components=[clip("A001", 180)])])
og.parameters = [
    mk("VaryingValue", name="AFX_SCALE_X_U",
       pointlist=[mk("ControlPoint", time=-0.5, value=100.0),
                  mk("ControlPoint", time=0.7011173184357542, value=127.0),
                  mk("ControlPoint", time=1.5, value=140.0)]),
]
state = new_state()
ap._walk_slot(mk("Sequence", components=[og]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  const frames = out.events[0].geometry[0].keyframes.AFX_SCALE_X_U.points.map((p) => p.frame);
  assert.deepEqual(frames, [-89.5, 125.5, 268.5], 'negative, half-frame and past-the-end keys all survive');
});

test('aaf_probe: a retime carries its own curves, and the offset map is in effect FRAMES', { skip: PY ? false : 'python3 not available' }, () => {
  // The second time domain. PARAM_SPEED_OFFSET_MAP_U spans exactly 0..length on
  // every retime measured — it is ALREADY frames, so the (length - 1) normalization
  // the transform params need would be wrong here by the effect's whole length.
  const out = runWalker(`
from fractions import Fraction
og = opgroup("Motion Control", 112, [mk("Sequence", components=[clip("A001", 202)])])
og.parameters = [
    mk("ConstantValue", name="SpeedRatio", value=Fraction(112, 201)),
    mk("VaryingValue", name="PARAM_SPEED_OFFSET_MAP_U",
       interpolationdef=mk("InterpolationDefinition", name="LinearInterp"),
       pointlist=[mk("ControlPoint", time=0.0, value=0.0),
                  mk("ControlPoint", time=112.0, value=201.6)]),
]
state = new_state()
ap._walk_slot(mk("Sequence", components=[og]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  const ev = out.events[0];
  const off = ev.speedCurve.sourceOffset;
  assert.equal(off.domain, 'effectFrames');
  assert.deepEqual(off.points.map((p) => p.frame), [0.0, 112.0], 'frame == t, not t x (length - 1)');
  assert.equal(off.parameter, 'PARAM_SPEED_OFFSET_MAP_U', "kept under Avid's own name");
});

test('aaf_probe: the declared SpeedRatio is whole-frame TRUNCATED — both numbers ship, neither is substituted', { skip: PY ? false : 'python3 not available' }, () => {
  // 🚨 Measured on the fixture: 7 of 18 constant retimes disagree with their own
  // source-offset curve, always the same way — the rational is the source span
  // rounded to whole frames (201/112) while the curve is exact (201.6/112 = 1.80).
  // The worst is 1.631579 declared against a true 1.70: a 4% speed error handed to
  // an operator to type in. Reporting both under their own names is the contract;
  // silently replacing `speedRatio` would be the SpeedRatio inversion all over again.
  const out = runWalker(`
from fractions import Fraction
og = opgroup("Motion Control", 112, [mk("Sequence", components=[clip("A001", 202)])])
og.parameters = [
    mk("ConstantValue", name="SpeedRatio", value=Fraction(112, 201)),
    mk("VaryingValue", name="PARAM_SPEED_OFFSET_MAP_U",
       pointlist=[mk("ControlPoint", time=0.0, value=0.0),
                  mk("ControlPoint", time=112.0, value=201.6)]),
]
state = new_state()
ap._walk_slot(mk("Sequence", components=[og]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  const ev = out.events[0];
  assert.equal(ev.speedRatio, 1.794643, 'the DECLARED rational is reported unchanged');
  assert.equal(ev.speedRatioFromCurve, 1.8, 'and the curve is reported as what it measures');
});

test('aaf_probe: a real timewarp is never averaged into one rate', { skip: PY ? false : 'python3 not available' }, () => {
  // The colinearity test is what separates "a dense curve that happens to be a
  // straight line" from "a ramp". A ramp has no single rate, so none is offered —
  // but the curve itself still ships, which is what makes it rebuildable at all.
  const out = runWalker(`
pts = [mk("ControlPoint", time=float(i), value=float(i * i) / 40.0) for i in range(0, 81)]
og = opgroup("Motion Control", 80, [mk("Sequence", components=[clip("A001", 160)])])
og.parameters = [
    mk("VaryingValue", name="PARAM_SPEED_MAP_U",
       pointlist=[mk("ControlPoint", time=0.0, value=0.5),
                  mk("ControlPoint", time=80.0, value=2.0)]),
    mk("VaryingValue", name="PARAM_SPEED_OFFSET_MAP_U", pointlist=pts),
]
state = new_state()
ap._walk_slot(mk("Sequence", components=[og]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  const ev = out.events[0];
  assert.equal(ev.speedVarying, true);
  assert.equal(ev.speedRatioFromCurve, undefined, 'a ramp gets no single rate');
  assert.equal(ev.speedCurve.sourceOffset.points.length, 81, 'but the whole ramp is carried');
});

test('aaf_probe: an unreadable control point refuses the WHOLE curve', { skip: PY ? false : 'python3 not available' }, () => {
  // A curve with a hole in it is worse than no curve: a consumer would interpolate
  // straight through the missing key and produce a confident, wrong animation.
  const out = runWalker(`
og = opgroup("PaintResize_v2", 50, [mk("Sequence", components=[clip("A001", 50)])])
og.parameters = [
    mk("VaryingValue", name="AFX_POS_X_U",
       pointlist=[mk("ControlPoint", time=0.0, value=-42.0),
                  mk("ControlPoint", value=10.0),
                  mk("ControlPoint", time=1.0, value=0.0)]),
]
state = new_state()
ap._walk_slot(mk("Sequence", components=[og]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  const [geo] = out.events[0].geometry;
  assert.deepEqual(geo.varying, ['AFX_POS_X_U'], 'still named as animated — the refusal is loud');
  assert.equal(geo.keyframes, undefined, 'and no partial curve is offered');
});

// ── Uninterpreted transform ops (U22) ─────────────────────────────────────────

test('aaf_probe: a transform op we do not interpret is REPORTED, under a key nobody applies', { skip: PY ? false : 'python3 not available' }, () => {
  // 🚨 The trap this shape exists to avoid: 2DMatteKey_2 carries AFX_POS_X_U 500.0,
  // and AFX_POS_X_U is a name a consumer already has a CALIBRATED pan rule for. Put
  // it in `params` and a clip nobody repositioned slides ~960px. So an uninterpreted
  // op's numbers travel in `rawParams`, which no existing consumer reads.
  const out = runWalker(`
from fractions import Fraction
mk_key = opgroup("2DMatteKey_2", 40, [mk("Sequence", components=[clip("A001", 40)])])
mk_key.parameters = [mk("ConstantValue", name="AFX_POS_X_U", value=Fraction(500, 1))]
blend = opgroup("SBlend_v2", 30, [mk("Sequence", components=[clip("A002", 30)])])
blend.parameters = [
    mk("ConstantValue", name="DVE_SCALE_X_U", value=Fraction(103, 1)),
    mk("ConstantValue", name="DVE_ROT_Z_U", value=Fraction(3, 1)),
    mk("ConstantValue", name="AvidParameterByteOrder", value=18761),
]
state = new_state()
ap._walk_slot(mk("Sequence", components=[mk_key, blend]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  const [matte] = out.events[0].geometry;
  assert.equal(matte.passthrough, true);
  assert.equal(matte.rawParams.AFX_POS_X_U, 500.0, 'the number is carried...');
  assert.equal(matte.params, undefined, '...but never where the calibrated pan rule looks');
  assert.equal(matte.scalePercentX, undefined, 'and never as a composable scale');

  const [blend] = out.events[1].geometry;
  assert.deepEqual(blend.rawParams, { DVE_ROT_Z_U: 3.0, DVE_SCALE_X_U: 103.0 });
  assert.equal(blend.scalePercentX, undefined, 'DVE_SCALE is a different unit per op — never normalized');
});

test('aaf_probe: an uninterpreted op that animates still carries the curve', { skip: PY ? false : 'python3 not available' }, () => {
  const out = runWalker(`
blend = opgroup("SBlend_v2", 21, [mk("Sequence", components=[clip("A001", 21)])])
blend.parameters = [
    mk("VaryingValue", name="DVE_POS_X_U",
       pointlist=[mk("ControlPoint", time=0.0, value=0.0),
                  mk("ControlPoint", time=1.0, value=99.0)]),
    mk("VaryingValue", name="DVE_SCALE_X_U",
       pointlist=[mk("ControlPoint", time=0.0, value=110.0),
                  mk("ControlPoint", time=1.0, value=110.0)]),
]
state = new_state()
ap._walk_slot(mk("Sequence", components=[blend]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  const [geo] = out.events[0].geometry;
  assert.deepEqual(geo.varying, ['DVE_POS_X_U']);
  assert.deepEqual(geo.keyframes.DVE_POS_X_U.points.map((p) => p.frame), [0, 20]);
  assert.equal(geo.rawParams.DVE_SCALE_X_U, 110.0, 'a flat point list is still a constant');
});

// ── Effects that occupy record time and emit nothing (U23) ────────────────────

test('aaf_probe: an effect that consumes record time but emits no event is COUNTED', { skip: PY ? false : 'python3 not available' }, () => {
  // 🚨 `unhandled` structurally cannot see this. It counts component classes the
  // walker does not model — and these are modeled perfectly: an OperationGroup is
  // walked, its inputs are walked, and they contain no SourceClip. On the reference
  // turnover `unhandled` reads {} (a complete parse) while 29 SubCap titles occupy
  // real record time and reach the consumer as nothing whatsoever. A conform that
  // silently loses 29 titles is indistinguishable from one that never had any.
  const out = runWalker(`
title = opgroup("SubCap", 60, [])
real  = opgroup("PaintResize_v2", 40, [mk("Sequence", components=[clip("A001", 40)])])
state = new_state()
ap._walk_slot(mk("Sequence", components=[title, real]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  assert.deepEqual(out.unhandled, {}, 'nothing is UNMODELLED — that is exactly the trap');
  assert.deepEqual(out.effectsWithoutEvents, { SubCap: 1 });
  assert.equal(out.events.length, 1, 'and the real clip is unaffected');
  // The title still consumed its record time, so the clip after it lands at 60.
  assert.equal(out.events[0].recIn, 60);
});

test('aaf_probe: an empty effect is charged ONCE, to the innermost group', { skip: PY ? false : 'python3 not available' }, () => {
  // A wrapper around an empty effect is empty for the same single reason. Charging
  // both would report one lost title as two, which is its own kind of wrong.
  const out = runWalker(`
inner = opgroup("SubCap", 60, [])
outer = opgroup("PaintResize_v2", 60, [mk("Sequence", components=[inner])])
state = new_state()
ap._walk_slot(mk("Sequence", components=[outer]), prefix="V", fps=24, state=state)
print(json.dumps(state))
`);
  assert.deepEqual(out.effectsWithoutEvents, { SubCap: 1 }, 'the innermost cause, once');
});

// Regression: assemble_from_interchange format 'aaf' used to fall through to
// the sync parseInterchange, which THROWS for aaf — the tool-layer AAF route
// never worked before v2.126.0 (every earlier proof called parseAAF directly).
test('assemble_from_interchange aaf routes through the async parser (stubbed)', async () => {
  // Single-source events (the multi-source path needs captured templates,
  // which is not what this regression is about).
  const ONE_SEQ = {
    sequences: [{ id: 'urn:mob:9', name: 'ONE', eventCount: 2, events: [
      { index: 1, track: 'V', source: 'A001', srcIn: 0, srcOut: 48, recIn: 0, recOut: 48, speed: 100, reverse: false, transition: null, fps: 24 },
      { index: 2, track: 'V', source: 'A001', srcIn: 96, srcOut: 120, recIn: 48, recOut: 72, speed: 100, reverse: false, transition: null, fps: 24 },
    ] }],
  };
  const stubOne = writeStub('py_one.sh', `#!/bin/sh\ncat <<'JSON'\n${JSON.stringify(ONE_SEQ)}\nJSON\n`);
  process.env.AAF_PROBE_PYTHON = stubOne;
  const { drtTool } = await import('../server/lib.mjs');
  const out = path.join(TMP, 'aaf-route.drt');
  const r = await drtTool.handler({ action: 'assemble_from_interchange', args: {
    format: 'aaf', path: FAKE_AAF, outputPath: out, targetAppVersion: '19.1.3',
    sourceMap: {
      A001: { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 } },
    },
  }});
  assert.ok(!r.error, r.error);
  assert.equal(r.conform.videoEvents, 2);
  assert.ok(fs.existsSync(out));
  fs.rmSync(out, { force: true });
});

test('assemble_from_interchange picks a sequence by name from a multi-seq AAF', async () => {
  process.env.AAF_PROBE_PYTHON = STUB_OK; // EP012 CONFORM (2 events) + EP012 BONUS (0)
  const { drtTool } = await import('../server/lib.mjs');
  const out = path.join(TMP, 'aaf-pick.drt');
  const mkArgs = (extra) => ({ action: 'assemble_from_interchange', args: {
    format: 'aaf', path: FAKE_AAF, outputPath: out, targetAppVersion: '19.1.3',
    sourceMap: {
      A001: { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 } },
      B002: { mediaFilePath: '/m/a.mp4', spec: { width: 640, height: 360, frameCount: 480, fps: 24 } },
    }, ...extra,
  }});
  // only ONE sequence has events → auto-picks it, no flag needed
  const r1 = await drtTool.handler(mkArgs({}));
  assert.ok(!r1.error, r1.error);
  assert.equal(r1.conform.videoEvents, 2);
  // explicit name works too; a wrong name names the available ones
  const r2 = await drtTool.handler(mkArgs({ sequenceName: 'EP012 CONFORM' }));
  assert.ok(!r2.error, r2.error);
  await assert.rejects(drtTool.handler(mkArgs({ sequenceName: 'NOPE' })), /available: EP012 CONFORM, EP012 BONUS/);
  fs.rmSync(out, { force: true });
});
