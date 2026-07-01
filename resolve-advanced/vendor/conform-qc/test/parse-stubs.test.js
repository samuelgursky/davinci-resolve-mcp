'use strict';

/**
 * parse/ contract + format-stub tests. Client-free (no raw material needed).
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const parse = require('../parse');

test('parse: captured-geometry contract is the shared shape (XMEML conforms)', () => {
  assert.ok(Array.isArray(parse.CAPTURED_CLIP_FIELDS));
  for (const f of ['seqstart', 'xml_in', 'pproTicksIn', 'is_subclip', 'subclip_startoffset', 'scale_premiere', 'srcW', 'srcH', 'source_basename']) {
    assert.ok(parse.CAPTURED_CLIP_FIELDS.includes(f), `contract must include "${f}"`);
  }
  assert.equal(typeof parse.parseGeometry, 'function');
});

test('parse: AAF capture is a stub that throws (conforms to interface)', () => {
  assert.equal(typeof parse.parseGeometryAAF, 'function');
  assert.throws(() => parse.parseGeometryAAF('<aaf/>'), /AAF geometry capture not implemented/);
});

test('parse: OTIO capture is a stub that throws (conforms to interface)', () => {
  assert.equal(typeof parse.parseGeometryOTIO, 'function');
  assert.throws(() => parse.parseGeometryOTIO('{}'), /OTIO geometry capture not implemented/);
});
