'use strict';

/** Operator runbook content check (P5-docs-runbook) — documents every closed decision. */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const DOC = fs.readFileSync(path.join(__dirname, '..', 'docs', 'runbook.md'), 'utf8');

test('runbook: documents both surfaces, tiers, package options, and the closed decisions', () => {
  const must = [
    /two surfaces/i,
    /Cloud/, /Local/,
    /A — burned reference/i, /B — clean ref/i, /C — no reference/i, /math-verified/,
    /no picture, no `?content-verified/i,
    /brightness/i,
    /ADVISORY ONLY/i,
    /never.*(clear a flag|flip a deterministic)/i,
    /host-injected `?VisionValidator|supplied by the host/i, // optional vision seam, no bundled LLM
    /SSIM ≥ 0\.90|PSNR ≥ 25/,
    /VFX alignment \*\*never\*\* auto-applies|VFX alignment never/i,
    /MediaRelationship.*→.*project override.*→.*editorialRole|resolution/i, // §10 order
    /OTIO is the internal canonical/i,
    /<in>.*<pproTicksIn>.*consistent|Resolve reads ticks/i,
    /trigger model/i,
  ];
  for (const re of must) assert.match(DOC, re, `runbook must document: ${re}`);
});
