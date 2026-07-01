'use strict';

/**
 * Normalized-key relink tier (proxy↔original exact match). Regression for the
 * production-reel conform bug where the IDF tokenizer dropped the single-char take marker
 * and collapsed "…#2" onto "…#1" (a DIFFERENT rescan of the same shot).
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { MediaIndex, normalizedKey } = require('../repair/media-index');

const HIGHRES = [
  { path: '/hr/ProRes4444XQ/Director Sample at Rest S16mm 12R BWN 4K 0508 CR A01 A02 A03.mov' },
  { path: '/hr/Rescans + Reshoots/Sample S16mm 12R 4K 0821 CR B01-B03 A08-A012 #1.mov' },
  { path: '/hr/Rescans + Reshoots/Sample S16mm 12R 4K 0821 CR B01-B03 A08-A012 #2.mov' },
  { path: '/hr/Rescans + Reshoots/Sample S16mm 12R 4K 0821 CR A07 A04-A06.mov' },
  { path: '/hr/Tests/Director S16mm 3378 LoCon 4K 0703a.mov' },
].map((m) => ({ ...m, basename: m.path.split('/').pop() }));

const idx = new MediaIndex(HIGHRES);

test('normalizedKey: erases proxy decoration but preserves the take marker', () => {
  assert.equal(
    normalizedKey('Sample S16mm 12R 4K 0821 CR B01-B03 A08-A012 #2.mp4'),
    normalizedKey('Sample S16mm 12R 4K 0821 CR B01-B03 A08-A012 #2.mov'),
  );
  assert.notEqual(
    normalizedKey('Sample S16mm 12R 4K 0821 CR B01-B03 A08-A012 #2.mp4'),
    normalizedKey('Sample S16mm 12R 4K 0821 CR B01-B03 A08-A012 #1.mov'),
  );
  // 4K-2K proxy marker and trailing _1 dup-import suffix are erased.
  assert.equal(
    normalizedKey('Director Sample at Rest S16mm 12R BWN 4K-2K 0508 CR A01 A02 A03.mov'),
    normalizedKey('Director Sample at Rest S16mm 12R BWN 4K 0508 CR A01 A02 A03.mov'),
  );
  assert.equal(normalizedKey('Director S16mm 3378 LoCon 4K 0703a_1.mov'), normalizedKey('Director S16mm 3378 LoCon 4K 0703a.mov'));
});

test('byNormalized: #2 proxy resolves to the #2 original, not #1', () => {
  const hit = idx.byNormalized('Sample S16mm 12R 4K 0821 CR B01-B03 A08-A012 #2.mp4');
  assert.equal(hit, '/hr/Rescans + Reshoots/Sample S16mm 12R 4K 0821 CR B01-B03 A08-A012 #2.mov');
  const hit1 = idx.byNormalized('Sample S16mm 12R 4K 0821 CR B01-B03 A08-A012 #1.mp4');
  assert.equal(hit1, '/hr/Rescans + Reshoots/Sample S16mm 12R 4K 0821 CR B01-B03 A08-A012 #1.mov');
});

test('byNormalized: 4K-2K proxy + _1 dup-suffix resolve to the original scan', () => {
  assert.equal(
    idx.byNormalized('Director Sample at Rest S16mm 12R BWN 4K-2K 0508 CR A01 A02 A03.mov'),
    '/hr/ProRes4444XQ/Director Sample at Rest S16mm 12R BWN 4K 0508 CR A01 A02 A03.mov',
  );
  assert.equal(
    idx.byNormalized('Director S16mm 3378 LoCon 4K 0703a_1.mov'),
    '/hr/Tests/Director S16mm 3378 LoCon 4K 0703a.mov',
  );
});

test('byNormalized: refuses to guess when the key is ambiguous', () => {
  const dup = new MediaIndex([
    { path: '/a/Shot 4K 0508.mov', basename: 'Shot 4K 0508.mov' },
    { path: '/b/Shot 4K-2K 0508.mov', basename: 'Shot 4K-2K 0508.mov' },
  ]);
  assert.equal(dup.byNormalized('Shot 4K 0508.mp4'), null);
});
