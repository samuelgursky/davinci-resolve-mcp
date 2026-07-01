/**
 * shot-intent tagging (Layer-3) — deterministic signals → tags + the neutralize-exclusion
 * contract the matchers honor. Synthesizes frames, reads them, asserts the derived tags.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { scopeRead } from '../server/scope-read.mjs';
import { deriveIntentTags, shouldExcludeFromNeutralize } from '../server/shot-intent.mjs';
import { drxTool } from '../server/tools/drx.mjs';

const require = createRequire(import.meta.url);
const sharp = require('sharp');

async function solid(file, { r, g, b }, w = 64, h = 64) {
  const buf = Buffer.alloc(w * h * 3);
  for (let i = 0; i < buf.length; i += 3) {
    buf[i] = r;
    buf[i + 1] = g;
    buf[i + 2] = b;
  }
  await sharp(buf, { raw: { width: w, height: h, channels: 3 } })
    .png()
    .toFile(file);
}

const tagNames = (r) => r.tags.map((t) => t.tag);

test('a low-key frame is tagged low_key and excluded from neutralize', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'intent-'));
  const f = path.join(dir, 'dark.png');
  await solid(f, { r: 18, g: 20, b: 24 });
  const scope = await scopeRead(f);
  const { tags } = deriveIntentTags(scope);
  assert.ok(tagNames({ tags }).includes('low_key'));
  assert.equal(shouldExcludeFromNeutralize(tags), true);
});

test('a warm frame is tagged motivated_warm; metadata WB raises confidence', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'intent-'));
  const f = path.join(dir, 'warm.png');
  await solid(f, { r: 190, g: 120, b: 70 });
  const scope = await scopeRead(f);
  const withMeta = deriveIntentTags(scope, { whiteBalanceK: 3200 });
  const warm = withMeta.tags.find((t) => t.tag === 'motivated_warm');
  assert.ok(warm, 'motivated_warm tagged');
  assert.equal(warm.confidence, 'high', 'scope + metadata → high confidence');
});

test('a neutral gray frame is not excluded from neutralize', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'intent-'));
  const f = path.join(dir, 'gray.png');
  await solid(f, { r: 128, g: 128, b: 128 });
  const scope = await scopeRead(f);
  const { tags } = deriveIntentTags(scope);
  assert.equal(shouldExcludeFromNeutralize(tags), false);
});

test('drx intent_tags action returns candidate tags + signals', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'intent-'));
  const f = path.join(dir, 'teal.png');
  await solid(f, { r: 20, g: 130, b: 130 });
  const r = await drxTool.handler({ action: 'intent_tags', args: { png: f } });
  assert.ok(Array.isArray(r.tags));
  assert.ok(r.tags.some((t) => t.tag === 'monochromatic'));
  assert.ok(r.signals);
});
