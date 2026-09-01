/**
 * E127: Resolve's EXPORT_DRT of a compound timeline (fixture = verbatim export
 * from Studio 19.1.3.7 of the E57 depth-2 nested timeline). A SeqContainer XML
 * carries no timeline name — its first <Name> is the first CLIP's — so parse /
 * list_sequences called the timeline "cut_src.mp4" and the compounds
 * "white_src.mp4". The pool folder's Sm2MpTimelineClip / Sm2MpCompoundClip
 * embed the Sm2Sequence whose DbId the container's <Sequence> names; that is
 * where the names and kinds live. A media-less clip named after a compound is
 * that compound placed on the track.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { summarizeDrtTimelines } from '../server/sequences.mjs';
import { drtTool } from '../server/tools/drt.mjs';

const require = createRequire(import.meta.url);
const { parseDRT } = require('../vendor/drt-format/drt-parser.js');
const { createEmptyProject } = require('../vendor/drp-format/author-project.js');
const FIXTURE = new URL('./fixtures/E127_resolve_nested_export.drt', import.meta.url).pathname;

test('parseDRT names containers from the pool and kinds them timeline/compound (E127)', async () => {
  const parsed = await parseDRT(FIXTURE);
  assert.deepEqual(parsed.timelines.map((t) => [t.name, t.kind]), [['E57_IN', 'compound'], ['E57_OUT', 'compound'], ['E57_NESTED', 'timeline']]);
  const top = parsed.timelines.find((t) => t.name === 'E57_NESTED');
  const clips = top.videoTracks[0].clips.map((c) => [c.name, c.compound || null, c.mediaFilePath != null]);
  assert.deepEqual(clips, [['cut_src.mp4', null, true], ['E57_OUT', 'E57_OUT', false]]);
  const mid = parsed.timelines.find((t) => t.name === 'E57_OUT');
  assert.deepEqual(mid.videoTracks[0].clips.map((c) => [c.name, c.compound || null]), [['E57_IN', 'E57_IN'], ['cut_src.mp4', null]]);
});

test('list_sequences reports kind and nestedIn so a picker can demote compounds (E127)', async () => {
  const seqs = summarizeDrtTimelines(await parseDRT(FIXTURE));
  assert.deepEqual(seqs.map((s) => [s.name, s.kind, s.nestedIn]), [['E57_IN', 'compound', ['E57_OUT']], ['E57_OUT', 'compound', ['E57_NESTED']], ['E57_NESTED', 'timeline', []]]);
});

test('a tool-authored project without compounds keeps its names and carries no kind (E127 null control)', async () => {
  const { buffer } = await createEmptyProject({ timelineName: 'Plain' });
  const parsed = await parseDRT(buffer);
  assert.equal(parsed.timelines.length, 1);
  assert.ok(parsed.timelines[0].name, 'a name survives');
  const seqs = summarizeDrtTimelines(parsed);
  assert.deepEqual(seqs.map((s) => s.nestedIn), [[]]);
  assert.ok(parsed.timelines[0].videoTracks.every((t) => (t.clips || []).every((c) => c.compound === undefined)));
});

// E128: extract_from_drp used index 0 by default, and SeqContainers list
// name-sorted by DbId — on Resolve's export of a compound timeline (E127
// fixture) that was the INNER compound E57_IN, not the timeline. The default
// is now the first container the pool kinds as a timeline; timelineName picks
// by pool name; an explicit timelineIndex still means exactly that container.
test('extract_from_drp defaults to the pool\'s timeline, not the first-sorted compound (E128)', async () => {
  const fx = new URL('./fixtures/E127_resolve_nested_export.drt', import.meta.url).pathname;
  const tmp = (n) => path.join(os.tmpdir(), `e128-${process.pid}-${n}.drt`);
  const names = async (file) => (await parseDRT(file)).timelines.map((t) => t.name).sort();
  const byDefault = await drtTool.handler({ action: 'extract_from_drp', args: { drpPath: fx, outputPath: tmp('default') } });
  assert.equal(byDefault.pickedBy, 'first timeline in the pool');
  assert.deepEqual(byDefault.container, { name: 'E57_NESTED', kind: 'timeline' });
  assert.deepEqual(await names(tmp('default')), ['E57_IN', 'E57_NESTED', 'E57_OUT'], 'the timeline keeps its compounds (recursively)');
  const byName = await drtTool.handler({ action: 'extract_from_drp', args: { drpPath: fx, outputPath: tmp('name'), timelineName: 'E57_OUT' } });
  assert.equal(byName.pickedBy, 'timelineName');
  assert.deepEqual(await names(tmp('name')), ['E57_IN', 'E57_OUT']);
  const byIndex = await drtTool.handler({ action: 'extract_from_drp', args: { drpPath: fx, outputPath: tmp('idx'), timelineIndex: 0 } });
  assert.equal(byIndex.pickedBy, 'timelineIndex');
  assert.deepEqual(await names(tmp('idx')), ['E57_IN'], 'index 0 is the first-sorted container — an inner compound here');
  const missing = await drtTool.handler({ action: 'extract_from_drp', args: { drpPath: fx, outputPath: tmp('x'), timelineName: 'NOPE' } });
  assert.match(missing.error, /no SeqContainer named "NOPE"/);
});
