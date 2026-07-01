/** Node color — storage RE'd (node-convention/provenance spec, 2026-06-22). Set node 01's color to Blue in
 * the calibration UI → Cmd+S → diffed the grade Body: a new node-level field F15 appeared, a plain string
 * "ClipColorBlue". So node color = node field F15 = "ClipColor<Name>" (absent = no color); the names match
 * the Resolve palette (Orange/Apricot/Yellow/Lime/Olive/Green/Teal/Navy/Blue/Purple/Violet/Pink/Tan/Beige/
 * Brown/Chocolate). Trivial to read (UTF-8 of F15) and to write (set/clear the string — same low-risk plain-
 * string surgery class as the node label in F6). This unblocks the provenance "blue lens" + grade labeling. */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { drxTool } from '../server/tools/drx.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const content = fs.readFileSync(path.join(here, 'fixtures', 'node-color-blue.drx'), 'utf8');

test('node color decodes from F15 ("ClipColor<Name>" → bare name)', async () => {
  const r = await drxTool.handler({ action: 'parse', args: { content } });
  assert.ok(
    r.nodes.some((n) => n.color === 'Blue'),
    `a node reports color "Blue" (got ${r.nodes.map((n) => n.color)})`,
  );
});
