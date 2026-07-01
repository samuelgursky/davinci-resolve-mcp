/**
 * MCP-layer smoke: exercise each tool's handler directly (no transport) to
 * verify the server wiring over the vendored libs. The vendored libs have
 * their own deep __tests__ (run via `node --test vendor/**`); this covers the
 * drp/drt/drx tool dispatch + round-trips that the server exposes.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import fs from 'node:fs/promises';

import { drpTool } from '../server/tools/drp.mjs';
import { drtTool } from '../server/tools/drt.mjs';
import { drxTool } from '../server/tools/drx.mjs';

const tmp = (n) => path.join(os.tmpdir(), `adv-test-${n}`);

test('drp.create_empty_project → valid .drp on disk', async () => {
  const out = await drpTool.handler({ action: 'create_empty_project', args: { outputPath: tmp('empty .drp'), timelineName: 'TestTL' } });
  assert.ok(out.bytes > 0, 'bytes > 0');
  assert.equal(out.timelineName, 'TestTL');
  const stat = await fs.stat(tmp('empty .drp'));
  assert.ok(stat.size === out.bytes, 'file size matches reported bytes');
});

test('drt.author → drt.parse round-trip', async () => {
  const spec = {
    timelines: [
      {
        name: 'T1',
        frameRate: 24,
        startTimecode: '01:00:00:00',
        resolution: '1920x1080',
        videoTracks: [{ clips: [{ start: 0, duration: 24, in: 0, mediaFilePath: '/m/c1.mov' }] }],
        audioTracks: [],
      },
    ],
  };
  const authored = await drtTool.handler({ action: 'author', args: { outputPath: tmp('t.drt'), spec } });
  assert.ok(authored.bytes > 0);
  const parsed = await drtTool.handler({ action: 'parse', args: { drtPath: tmp('t.drt') } });
  assert.ok(parsed.timelines || parsed.seqContainers, 'parse returns timelines/seqContainers');
});

test('drx.generate → drx.parse round-trip', async () => {
  const gen = await drxTool.handler({ action: 'generate', args: { gradeParams: { lift: [0, 0, 0, 0], gamma: [0, 0, 0, 0], gain: [1.05, 1, 0.95, 1] } } });
  const content = gen.content || (typeof gen === 'string' ? gen : null);
  assert.ok(content && String(content).includes('<'), 'generate produced DRX-ish content');
  const parsed = await drxTool.handler({ action: 'parse', args: { content: String(content) } });
  assert.ok(Array.isArray(parsed.nodes), 'parse returns a node array');
});

test('unknown action throws', async () => {
  await assert.rejects(() => drpTool.handler({ action: 'nope', args: {} }), /Unknown drp action/);
});
