/** .drp timeline-clip reader — pure XML parsing, no Resolve. Shapes measured on
 * Resolve 19.1.3.7 exports (DbPrjVer 14). */

import test from 'node:test';
import assert from 'node:assert/strict';
import { listDrpTimelines, parseSeqContainerClips } from '../server/drp-timeline-clips.mjs';

const MP = `<MpFolder><Sm2Timeline DbId="tl-1">
  <FieldsBlob/>
  <Name>REEL_01 v07</Name>
  <Sequence><Sm2Sequence DbId="seq-1"><Parent>tl-1</Parent></Sm2Sequence></Sequence>
</Sm2Timeline><Sm2Timeline DbId="tl-2"><Name>Other</Name><Sequence><Sm2Sequence DbId="seq-2"/></Sequence></Sm2Timeline></MpFolder>`;

const version = (id, name, corrected, body) =>
  `<ListMgt::LmVersion DbId="${id}"><FieldsBlob/><Name>${name}</Name><HasCorrection>${corrected}</HasCorrection><VerType>0</VerType><Body>${body}</Body></ListMgt::LmVersion>`;
const clip = (id, o) => `<Element><Sm2TiVideoClip DbId="${id}">
  <Name>${o.name}</Name><Start>${o.start}</Start><Duration>${o.duration}</Duration>
  <In>${o.In}</In><MediaRef>${o.ref || 'ref-' + id}</MediaRef><MediaStartTime>76028.953</MediaStartTime>
  <MediaFilePath>${o.path}</MediaFilePath>${o.reel === undefined ? '<MediaReelNumber/>' : `<MediaReelNumber>${o.reel}</MediaReelNumber>`}
  ${o.versions ? `<pLmVerTable><ListMgt::LmVersionTable DbId="vt-${id}"><VerType>0</VerType><pActive>${o.active}</pActive><Locals>${o.versions.map((v) => `<Element>${v}</Element>`).join('')}</Locals></ListMgt::LmVersionTable></pLmVerTable>` : ''}
</Sm2TiVideoClip></Element>`;
const track = (id, type, seq, items) =>
  `<Element><Sm2TiTrack DbId="${id}"><Type>${type}</Type><Sequence>${seq}</Sequence><Items>${items}</Items></Sm2TiTrack></Element>`;

const CONTAINER = `<Sm2SequenceContainer DbId="c1"><VideoTrackVec>
${track('v1', 0, 'seq-1', clip('a', { name: 'A025C025', start: 86677, duration: 107, In: 48, path: '/Volumes/x/A025C025.mov', reel: 'A025A1EH', active: 'ver-2', versions: [version('ver-1', 'Version 1', 'true', 'AA11'), version('ver-2', 'Version 2', 'true', 'BB22')] }) + clip('b', { name: 'B', start: 90000, duration: 10, In: '47|0000eaffffffef3f', path: '/Volumes/x/B.mov', active: 'ver-3', versions: [version('ver-3', 'Version 1', 'false', 'CC33')] }))}
${track('v2', 0, 'seq-1', clip('c', { name: 'C', start: 91000, duration: 5, In: 'garbage', path: '/Volumes/x/C.mov' }))}
${track('v9', 0, 'seq-OTHER', clip('z', { name: 'Z', start: 1, duration: 1, In: 0, path: '/z.mov' }))}
</VideoTrackVec><AudioTrackVec>${track('a1', 1, 'seq-1', '<Element><Sm2TiAudioClip DbId="au"><Name>AU</Name><Start>86677</Start><Duration>107</Duration><In>0</In><MediaFilePath>/a.wav</MediaFilePath></Sm2TiAudioClip></Element>')}</AudioTrackVec></Sm2SequenceContainer>`;

test('listDrpTimelines maps every timeline name to its sequence id', () => {
  const tls = listDrpTimelines([MP]);
  assert.deepEqual(tls, [
    { name: 'REEL_01 v07', timelineId: 'tl-1', sequenceId: 'seq-1' },
    { name: 'Other', timelineId: 'tl-2', sequenceId: 'seq-2' },
  ]);
});

test('parseSeqContainerClips reads only the tracks of the requested sequence, video and audio typed', () => {
  const rows = parseSeqContainerClips(CONTAINER, 'seq-1', { includeGrade: true });
  assert.deepEqual(
    rows.map((r) => r.itemId),
    ['a', 'b', 'c', 'au'],
  );
  assert.deepEqual(
    rows.map((r) => r.trackType),
    [0, 0, 0, 1],
  );
  const a = rows[0];
  assert.equal(a.name, 'A025C025');
  assert.equal(a.start, 86677);
  assert.equal(a.duration, 107);
  assert.equal(a.sourceIn, 48);
  assert.equal(a.reel, 'A025A1EH');
  assert.equal(a.mediaPath, '/Volumes/x/A025C025.mov');
  assert.equal(a.poolId, 'ref-a');
  assert.equal(a.trackId, 'v1');
});

test('the ACTIVE corrected version wins; an uncorrected active version is no grade', () => {
  const rows = parseSeqContainerClips(CONTAINER, 'seq-1', { includeGrade: true });
  const [a, b, c] = rows;
  assert.equal(a.gradeVersion, 'Version 2');
  assert.equal(a.gradeBody, 'bb22');
  assert.equal(a.hasGrade, true);
  assert.equal(b.gradeBody, null);
  assert.equal(b.hasGrade, false);
  assert.equal(c.gradeBody, null);
});

test('In decodes like project_read: pipe composite → first field, garbage → null, empty reel → ""', () => {
  const rows = parseSeqContainerClips(CONTAINER, 'seq-1');
  assert.equal(rows[1].sourceIn, 47);
  assert.equal(rows[2].sourceIn, null);
  assert.equal(rows[1].reel, '');
  assert.equal('gradeBody' in rows[0], false, 'gradeBody stripped unless includeGrade');
});
