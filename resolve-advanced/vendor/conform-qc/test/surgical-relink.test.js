'use strict';

/** Surgical relink + scale-correction: changes only pathurl/name/scale, preserves
 *  everything else; corrects per-clip scale by source width; leaves the audio
 *  (no srcW) and unresolved sources untouched. */

const test = require('node:test');
const assert = require('node:assert/strict');

const { MediaIndex } = require('../repair/media-index');
const { surgicalRelink, encodePathUrl } = require('../packaging/surgical-relink');

const XML = `<?xml version="1.0"?>
<xmeml version="4">
<sequence><name>r1</name>
<media><video><track>
  <clipitem id="ci-1">
    <name>Shot A 4K-2K 0508.mov</name>
    <in>100</in><out>196</out>
    <pproTicksIn>123456</pproTicksIn>
    <file id="file-1"><name>Shot A 4K-2K 0508.mov</name>
      <pathurl>file://localhost/proxy/Shot%20A%204K-2K%200508.mov</pathurl>
      <media><video><samplecharacteristics><width>2048</width><height>1306</height></samplecharacteristics></video></media>
    </file>
    <filter><effect><name>Basic Motion</name>
      <parameter><parameterid>scale</parameterid><value>175.781</value></parameter>
      <parameter><parameterid>rotation</parameterid><value>0</value></parameter>
    </effect></filter>
  </clipitem>
  <clipitem id="ci-2">
    <name>Shot A 4K-2K 0508.mov</name>
    <in>200</in><out>296</out>
    <file id="file-1"/>
    <filter><effect><name>Basic Motion</name>
      <parameter><parameterid>scale</parameterid><value>179</value></parameter>
    </effect></filter>
  </clipitem>
</track></video></media>
</sequence>
</xmeml>`;

const index = new MediaIndex([
  { path: '/hr/Shot A 4K 0508.mov', basename: 'Shot A 4K 0508.mov' },
]);

test('surgical: relinks proxy→original, corrects per-clip scale (aspect-aware), preserves ticks/in/out', () => {
  const r = surgicalRelink(XML, index, { sequenceWidth: 3600, sequenceHeight: 2160 });
  // pathurl repointed (encoded), name updated
  assert.ok(r.xml.includes(encodePathUrl('/hr/Shot A 4K 0508.mov')));
  assert.ok(!r.xml.includes('/proxy/'));
  assert.ok(r.xml.includes('<name>Shot A 4K 0508.mov</name>'));
  // source 2048x1306 (1.568) is NARROWER than the 3600x2160 (1.667) timeline, so
  // Resolve scaleToFit fits by HEIGHT — correct by srcH/seqH:
  //   175.781*1306/2160 = 106.282 ; 179*1306/2160 = 108.229 (NOT the width-rule 100/101.831)
  assert.ok(r.xml.includes('<value>106.282</value>'));
  assert.ok(r.xml.includes('<value>108.229</value>'));
  assert.ok(!r.xml.includes('<value>175.781</value>'));
  assert.ok(!r.xml.includes('<value>100</value>')); // width-rule pillarbox value must NOT appear
  // untouched fields preserved byte-identical
  assert.ok(r.xml.includes('<pproTicksIn>123456</pproTicksIn>'));
  assert.ok(r.xml.includes('<in>100</in><out>196</out>'));
  assert.ok(r.xml.includes('<value>0</value>')); // rotation untouched
  assert.equal(r.scale.edits, 2);
  assert.equal(r.relink.resolved.length, 1);
});

test('surgical: leaves full-frame (srcW>=seqW) and no-media sources alone', () => {
  const xml = XML.replace('<width>2048</width>', '<width>3600</width>');
  const r = surgicalRelink(xml, index, { sequenceWidth: 3600, sequenceHeight: 2160 });
  assert.equal(r.scale.edits, 0);
  assert.ok(r.xml.includes('<value>175.781</value>')); // scale not corrected
  assert.equal(r.relink.skipped.length, 1);
});
