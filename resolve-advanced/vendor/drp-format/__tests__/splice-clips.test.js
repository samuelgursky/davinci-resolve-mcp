// Unit: in-place clip moves on a real Resolve .drp timeline (generalized #74 surgery).
// Structural verification via the reconciled parser; live Resolve round-trip is the
// acceptance gate (proven manually — see resolve21-schema-reconciliation.md).

const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');
const { moveClip, deleteClip, trimClip, trimClipHead, splitClip } = require('../splice-clips');
const { parseDRT } = require('../../drt-format');

// Build a minimal synthetic .drp buffer: one video track with N clips (start = i*100, dur 100).
async function synthDrp(n = 3) {
  const JSZip = require('jszip');
  const clips = Array.from({ length: n }, (_, i) =>
    `<Element><Sm2TiVideoClip DbId="c${i}"><FieldsBlob/><Name>clip${i}</Name>` +
    `<Start>${i * 100}</Start><Duration>100</Duration><In/><MediaStartTime>0</MediaStartTime>` +
    `<MediaFilePath>/x/${i}.mov</MediaFilePath></Sm2TiVideoClip></Element>`).join('');
  const track =
    '<Element><Sm2TiTrack DbId="t1"><FieldsBlob/><Type>0</Type><SubType>0</SubType><Flags>0</Flags>' +
    `<Sequence>seq1</Sequence><Items>${clips}</Items><FusionCompHolderItems/><UserDefinedName/><LayersVec/></Sm2TiTrack></Element>`;
  const seq =
    '<?xml version="1.0" encoding="UTF-8"?>\n<Sm2SequenceContainer DbId="seq-1"><FieldsBlob/>' +
    `<VideoTrackVec>${track}</VideoTrackVec><AudioTrackVec/></Sm2SequenceContainer>`;
  const zip = new JSZip();
  zip.file('SeqContainer/seq-1.xml', seq);
  return zip.generateAsync({ type: 'nodebuffer' });
}

async function startsOf(buf) {
  const parsed = await parseDRT(buf);
  const v = parsed.timelines[0].videoTracks[0].clips || [];
  return v.map((c) => ({ id: c.clipId, start: c.start, dur: c.duration }));
}

const FIXTURE = path.resolve(
  __dirname,
  '../../../docs/design/drp-drx-drt-closeout-harness/fixtures/canary-resolve21.drp',
);

// The canary timelines each have a media clip on V1. Pick the one whose V1 clip we can move.
async function targetTimelineUuid() {
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(fs.readFileSync(FIXTURE));
  for (const n of Object.keys(zip.files)) {
    if (!/SeqContainer\/[^/]+\.xml$/.test(n)) continue;
    const x = await zip.files[n].async('string');
    if (/<VideoTrackVec>[\s\S]*?<Sm2TiVideoClip/.test(x)) {
      return (x.match(/<Sm2SequenceContainer DbId="([^"]+)"/) || [])[1];
    }
  }
  return undefined;
}

test('moveClip relocates a V1 media clip to a new V2 (identity preserved)', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip(`fixture missing: ${FIXTURE}`); return; }
  const uuid = await targetTimelineUuid();

  const before = await parseDRT(FIXTURE);
  const beforeTl = before.timelines.find((tl) => tl.sequence && before && (tl.videoTracks || [])[0]?.clips?.length);
  const srcClip = beforeTl.videoTracks[0].clips[0];

  const res = await moveClip(FIXTURE, { timelineUuid: uuid, fromTrack: 1, toTrack: 2, clipIndex: 0, toStart: 12345 });
  assert.strictEqual(res.fromTrack, 1);
  assert.strictEqual(res.toTrack, 2);
  assert.strictEqual(res.createdTracks, 1, 'V2 created');
  assert.strictEqual(res.movedClipDbId, srcClip.clipId, 'same clip identity (DbId) preserved across the move');

  const after = await parseDRT(res.buffer);
  const tl = after.timelines.find((t2) => (t2.videoTracks || []).length >= 2);
  assert.ok(tl, 'timeline now has >=2 video tracks');
  // V1 lost the clip, V2 gained it at the new start.
  assert.strictEqual((tl.videoTracks[0].clips || []).length, 0, 'V1 no longer holds the moved clip');
  const v2 = tl.videoTracks[1].clips || [];
  assert.strictEqual(v2.length, 1, 'V2 holds the moved clip');
  assert.strictEqual(v2[0].clipId, srcClip.clipId, 'moved clip keeps DbId');
  assert.strictEqual(v2[0].start, 12345, 'moved clip retimed to toStart');
  assert.strictEqual(v2[0].mediaFilePath, srcClip.mediaFilePath, 'media reference carried verbatim');
});

test('moveClip errors on a non-existent source track', async (t) => {
  if (!fs.existsSync(FIXTURE)) { t.skip(`fixture missing: ${FIXTURE}`); return; }
  const uuid = await targetTimelineUuid();
  await assert.rejects(() => moveClip(FIXTURE, { timelineUuid: uuid, fromTrack: 9, toTrack: 2 }), /does not exist/);
});

test('moveClip validates track args', async () => {
  await assert.rejects(() => moveClip(FIXTURE, { fromTrack: 0, toTrack: 2 }), /fromTrack/);
  await assert.rejects(() => moveClip(FIXTURE, { fromTrack: 1, toTrack: -1 }), /toTrack/);
});

test('deleteClip without ripple removes only the target', async () => {
  const buf = await synthDrp(3);
  const res = await deleteClip(buf, { fromTrack: 1, clipIndex: 1 });
  assert.strictEqual(res.deletedClipDbId, 'c1');
  assert.strictEqual(res.remainingClips, 2);
  const s = await startsOf(res.buffer);
  assert.deepStrictEqual(s.map((c) => `${c.id}@${c.start}`), ['c0@0', 'c2@200'], 'others keep their starts');
});

test('deleteClip with ripple closes the gap', async () => {
  const buf = await synthDrp(3);
  const res = await deleteClip(buf, { fromTrack: 1, clipIndex: 1, ripple: true });
  const s = await startsOf(res.buffer);
  assert.deepStrictEqual(s.map((c) => `${c.id}@${c.start}`), ['c0@0', 'c2@100'], 'c2 shifts back by deleted duration');
});

test('trimClip with ripple shifts later clips by the duration delta', async () => {
  const buf = await synthDrp(3);
  const res = await trimClip(buf, { track: 1, clipIndex: 0, newDuration: 50, ripple: true });
  assert.strictEqual(res.oldDuration, 100);
  const s = await startsOf(res.buffer);
  assert.deepStrictEqual(s.map((c) => `${c.id}@${c.start}/${c.dur}`), ['c0@0/50', 'c1@50/100', 'c2@150/100']);
});

test('trimClip without ripple only resizes the target', async () => {
  const buf = await synthDrp(3);
  const res = await trimClip(buf, { track: 1, clipIndex: 0, newDuration: 50 });
  const s = await startsOf(res.buffer);
  assert.deepStrictEqual(s.map((c) => `${c.id}@${c.start}/${c.dur}`), ['c0@0/50', 'c1@100/100', 'c2@200/100']);
});

test('deleteClip/trimClip select by Name and DbId', async () => {
  const byName = await deleteClip(await synthDrp(3), { fromTrack: 1, nameContains: 'clip2' });
  assert.strictEqual(byName.deletedClipDbId, 'c2');
  const byId = await trimClip(await synthDrp(3), { track: 1, clipDbId: 'c1', newDuration: 33 });
  assert.strictEqual(byId.trimmedClipDbId, 'c1');
});

// Parse Start/Duration + source In framePos per clip (fields not adjacency-dependent).
async function clipFields(buf) {
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(buf);
  for (const n of Object.keys(zip.files)) {
    if (!/SeqContainer\/[^/]+\.xml$/.test(n)) continue;
    const x = await zip.files[n].async('string');
    const vtv = (x.match(/<VideoTrackVec>([\s\S]*?)<\/VideoTrackVec>/) || [null, ''])[1];
    return [...vtv.matchAll(/<Sm2TiVideoClip DbId="([^"]+)">([\s\S]*?)<\/Sm2TiVideoClip>/g)].map((m) => {
      const c = m[2];
      const num = (re) => { const mm = c.match(re); return mm ? +mm[1] : null; };
      return {
        id: m[1],
        start: num(/<Start>(\d+)<\/Start>/),
        dur: num(/<Duration>(\d+)<\/Duration>/),
        srcIn: (() => { const mm = c.match(/<In>(\d+)\|/); return mm ? +mm[1] : 0; })(),
      };
    });
  }
  return [];
}

test('trimClipHead (non-ripple) advances source In + Start, keeps OUT fixed', async () => {
  const buf = await synthDrp(3);
  const res = await trimClipHead(buf, { track: 1, clipIndex: 1, frames: 30 });
  assert.strictEqual(res.newIn, 30);
  assert.strictEqual(res.newStart, 130);     // 100 + 30
  assert.strictEqual(res.newDuration, 70);    // 100 - 30
  const f = await clipFields(res.buffer);
  const c1 = f.find((c) => c.id === 'c1');
  assert.deepStrictEqual([c1.start, c1.dur, c1.srcIn], [130, 70, 30]);
  assert.strictEqual(c1.start + c1.dur, 200, 'OUT point fixed');
  assert.strictEqual(f.find((c) => c.id === 'c2').start, 200, 'later clip unmoved (non-ripple)');
});

test('trimClipHead (ripple) keeps Start, advances In, shifts later clips left', async () => {
  const buf = await synthDrp(3);
  const res = await trimClipHead(buf, { track: 1, clipIndex: 0, frames: 40, ripple: true });
  const f = await clipFields(res.buffer);
  assert.deepStrictEqual([f[0].start, f[0].dur, f[0].srcIn], [0, 60, 40], 'head-trimmed, Start kept, In advanced');
  assert.strictEqual(f.find((c) => c.id === 'c1').start, 60, 'c1 shifted by -40');
  assert.strictEqual(f.find((c) => c.id === 'c2').start, 160, 'c2 shifted by -40');
});

test('trimClipHead rejects frames >= duration', async () => {
  const buf = await synthDrp(1);
  await assert.rejects(() => trimClipHead(buf, { track: 1, frames: 100 }), />=/);
});

test('splitClip cuts one clip into two abutting clips', async () => {
  const buf = await synthDrp(2);            // c0@0/100/ms0, c1@100/100/ms0
  const res = await splitClip(buf, { track: 1, at: 130 });  // splits c1 (100..200) at 130
  assert.strictEqual(res.leftDbId, 'c1', 'left keeps original DbId');
  assert.notStrictEqual(res.rightDbId, 'c1', 'right gets a fresh DbId');
  assert.strictEqual(res.leftDuration, 30);   // 130 - 100
  assert.strictEqual(res.rightDuration, 70);  // 200 - 130
  const f = await clipFields(res.buffer);
  const left = f.find((c) => c.id === 'c1');
  const right = f.find((c) => c.id === res.rightDbId);
  assert.deepStrictEqual([left.start, left.dur, left.srcIn], [100, 30, 0], 'left: start/dur/in-point');
  assert.deepStrictEqual([right.start, right.dur, right.srcIn], [130, 70, 30], 'right: abuts left, source In = leftIn+leftDur');
  assert.strictEqual(left.start + left.dur, right.start, 'no gap between halves');
});

test('splitClip errors when no clip spans the frame', async () => {
  const buf = await synthDrp(1);            // c0@0..100
  await assert.rejects(() => splitClip(buf, { track: 1, at: 500 }), /spans frame/);
});

// Synthetic .drp with a video track (2 clips) AND an audio track (2 Sm2TiAudioClips).
async function synthAV() {
  const JSZip = require('jszip');
  const vclips = [0, 1].map((i) => `<Element><Sm2TiVideoClip DbId="v${i}"><FieldsBlob/><Name>v${i}</Name><Start>${i * 100}</Start><Duration>100</Duration><In/><MediaStartTime>0</MediaStartTime></Sm2TiVideoClip></Element>`).join('');
  const aclips = [0, 1].map((i) => `<Element><Sm2TiAudioClip DbId="a${i}"><FieldsBlob/><Name>a${i}</Name><Start>${i * 100}</Start><Duration>100</Duration><In/><MediaStartTime>0</MediaStartTime></Sm2TiAudioClip></Element>`).join('');
  const vtrack = `<Element><Sm2TiTrack DbId="vt"><FieldsBlob/><Type>0</Type><SubType>0</SubType><Flags>0</Flags><Sequence>s</Sequence><Items>${vclips}</Items><FusionCompHolderItems/><UserDefinedName/><LayersVec/></Sm2TiTrack></Element>`;
  const atrack = `<Element><Sm2TiTrack DbId="at"><FieldsBlob/><Type>1</Type><SubType>0</SubType><Flags>0</Flags><Sequence>s</Sequence><Items>${aclips}</Items><FusionCompHolderItems/><UserDefinedName/><LayersVec/></Sm2TiTrack></Element>`;
  const seq = `<?xml version="1.0"?>\n<Sm2SequenceContainer DbId="s1"><FieldsBlob/><VideoTrackVec>${vtrack}</VideoTrackVec><AudioTrackVec>${atrack}</AudioTrackVec></Sm2SequenceContainer>`;
  const z = new JSZip(); z.file('SeqContainer/s1.xml', seq); return z.generateAsync({ type: 'nodebuffer' });
}

async function audioStarts(buf, vec = 'AudioTrackVec', tag = 'Sm2TiAudioClip') {
  const JSZip = require('jszip');
  const zip = await JSZip.loadAsync(buf);
  const x = await zip.file('SeqContainer/s1.xml').async('string');
  const v = (x.match(new RegExp(`<${vec}>([\\s\\S]*?)</${vec}>`)) || [null, ''])[1];
  return [...v.matchAll(new RegExp(`<${tag} DbId="([^"]+)">[\\s\\S]*?<Start>(\\d+)<`, 'g'))].map((m) => `${m[1]}@${m[2]}`);
}

test('deleteClip with ripple works on the AUDIO vec', async () => {
  const buf = await synthAV();
  const res = await deleteClip(buf, { trackType: 'audio', fromTrack: 1, clipIndex: 0, ripple: true });
  assert.strictEqual(res.deletedClipDbId, 'a0');
  assert.deepStrictEqual(await audioStarts(res.buffer), ['a1@0'], 'a1 rippled to 0; video untouched');
  assert.deepStrictEqual(await audioStarts(res.buffer, 'VideoTrackVec', 'Sm2TiVideoClip'), ['v0@0', 'v1@100']);
});

test('trimClipHead on the AUDIO vec advances In', async () => {
  const buf = await synthAV();
  const res = await trimClipHead(buf, { trackType: 'audio', track: 1, clipIndex: 1, frames: 25 });
  assert.strictEqual(res.newIn, 25);
  assert.strictEqual(res.newDuration, 75);
});

test('moveClip relocates an audio clip to a new A-track', async () => {
  const buf = await synthAV();
  const res = await moveClip(buf, { trackType: 'audio', fromTrack: 1, toTrack: 2, clipIndex: 0, toStart: 500 });
  assert.strictEqual(res.createdTracks, 1);
  assert.strictEqual(res.movedClipDbId, 'a0');
});

const { rippleTimeline } = require('../splice-clips');

test('rippleTimeline shifts clips on BOTH video+audio after a point (A/V stay in sync)', async () => {
  const buf = await synthAV();   // v0@0,v1@100 ; a0@0,a1@100
  const res = await rippleTimeline(buf, { at: 100, delta: -40 });
  assert.strictEqual(res.shifted, 2, 'v1 and a1 both shifted');
  const v = await audioStarts(res.buffer, 'VideoTrackVec', 'Sm2TiVideoClip');
  const a = await audioStarts(res.buffer, 'AudioTrackVec', 'Sm2TiAudioClip');
  assert.deepStrictEqual(v, ['v0@0', 'v1@60'], 'video: only v1 (>=100) shifts to 60');
  assert.deepStrictEqual(a, ['a0@0', 'a1@60'], 'audio: a1 shifts identically (sync kept)');
});

test('rippleTimeline validates args', async () => {
  const buf = await synthAV();
  await assert.rejects(() => rippleTimeline(buf, { at: 1.5, delta: 10 }), /at must/);
  await assert.rejects(() => rippleTimeline(buf, { at: 10 }), /delta must/);
});
