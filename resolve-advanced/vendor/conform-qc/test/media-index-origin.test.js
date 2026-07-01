'use strict';

/**
 * MediaIndex IDF weighting + origin separation (§10.5) — regression for the real
 * false-match found on a production volume: a TEST roll (…Test…0425a) scored 0.75
 * against a production scan (…0508…) on shared boilerplate tokens.
 *
 * Fix: IDF-weighted token overlap — distinctive roll/date tokens decide the
 * match, boilerplate (Director/Sample/S16mm/4K) weighs ~nothing, so a
 * generic-only overlap stays well under threshold. Origin separation (excluding
 * the Tests tree for a finishing relink) is done by INDEX COMPOSITION, not a
 * name heuristic — because not every test source carries a "test" token
 * (LoCon / Normal / Reversal Dev do not).
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const { MediaIndex } = require('../repair/media-index');

const PROD_A04 = { path: '/vol/ScanLab Sample/ProRes4444XQ/Director Sample at Rest S16mm 12R BWN 4K 0508 CR A04 A05 A06.mov', basename: 'Director Sample at Rest S16mm 12R BWN 4K 0508 CR A04 A05 A06.mov' };
const PROD_A07 = { path: '/vol/ScanLab Sample/ProRes4444XQ/Director Sample at Rest S16mm 12R BWN 4K 0508 CR A07 A08 A09.mov', basename: 'Director Sample at Rest S16mm 12R BWN 4K 0508 CR A07 A08 A09.mov' };
const TEST_0425 = { path: '/vol/ScanLab Sample/Tests/Director Sample Test S16mm 12R BWN 4K 0425a.mov', basename: 'Director Sample Test S16mm 12R BWN 4K 0425a.mov' };

const full = new MediaIndex([PROD_A04, PROD_A07, TEST_0425]);

test('IDF: a TEST source resolves to the test scan, not the production scan (the 0.75 false-match)', () => {
  const t = full.findTrueSource('Director Sample Test S16mm 12R BWN 4K 0425a.mov', { minScore: 0.55 });
  assert.ok(t, 'the test source resolves');
  assert.match(t.path, /\/Tests\//, `test source must match the test scan, not production: ${JSON.stringify(t)}`);
});

test('IDF: distinctive roll tokens decide the match, not shared boilerplate', () => {
  // A04-A06 proxy must pick the A04-A06 scan over the A07-A09 scan, despite all
  // the shared "Director Sample at Rest S16mm 12R BWN 4K 0508" boilerplate.
  const p = full.findTrueSource('Director Sample at Rest S16mm 12R BWN 4K-2K 0508 CR A04 A05 A06.mov', { minScore: 0.55 });
  assert.ok(p, 'the production proxy resolves');
  assert.match(p.path, /ProRes4444XQ/, `production proxy must match the 4K scan: ${JSON.stringify(p)}`);
  assert.ok(p.basename.includes('A04 A05 A06') && !p.basename.includes('A07'), 'matches the right roll');
});

test('origin separation by index composition: a finishing-only index gives a test source no false production match', () => {
  // A finishing relink builds the index from the finishing trees only (the Tests
  // tree is excluded at composition). The test source then shares only generic
  // tokens with the production scans, so IDF keeps it under threshold → null.
  const finishing = new MediaIndex([PROD_A04, PROD_A07]);
  const t = finishing.findTrueSource('Director Sample Test S16mm 12R BWN 4K 0425a.mov', { minScore: 0.55 });
  assert.equal(t, null, `test source must NOT false-match production in a finishing-only index: ${JSON.stringify(t)}`);
});

test('opts.excludePathContains drops a tree inline (caller convenience)', () => {
  const t = full.findTrueSource('Director Sample Test S16mm 12R BWN 4K 0425a.mov', { minScore: 0.55, excludePathContains: ['/Tests/'] });
  assert.equal(t, null, 'excluding /Tests/ inline leaves no production false-match');
});
