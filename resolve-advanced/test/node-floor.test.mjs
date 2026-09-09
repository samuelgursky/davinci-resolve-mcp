/** Node-floor self-heal: the version rule, the candidate search, the pick, and
 * the launcher's real re-exec path (forced old version → re-exec under this Node). */

import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { meetsFloor, candidateNodeBinaries, findReplacementNode, probeNodeVersion } from '../../bin/node-floor.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const LAUNCHER = path.resolve(here, '..', '..', 'bin', 'davinci-resolve-advanced-mcp.mjs');

test('meetsFloor: 20.9 is the line, v-prefix tolerated, garbage refused', () => {
  assert.equal(meetsFloor('20.9.0'), true);
  assert.equal(meetsFloor('v20.20.2'), true);
  assert.equal(meetsFloor('23.10.0'), true);
  assert.equal(meetsFloor('20.8.9'), false);
  assert.equal(meetsFloor('18.20.8'), false);
  assert.equal(meetsFloor(''), false);
  assert.equal(meetsFloor('node'), false);
});

test('candidateNodeBinaries: explicit override first, nvm newest-first, then system paths; self excluded', () => {
  const home = '/h';
  const fsMap = new Set([
    '/h/.nvm/versions/node',
    '/h/.nvm/versions/node/v18.20.8/bin/node',
    '/h/.nvm/versions/node/v20.20.2/bin/node',
    '/h/.nvm/versions/node/v22.22.3/bin/node',
    '/opt/homebrew/bin/node',
    '/custom/node',
  ]);
  const out = candidateNodeBinaries({
    env: { HOME: home, DAVINCI_RESOLVE_NODE: '/custom/node' },
    home,
    platform: 'darwin',
    execPath: '/h/.nvm/versions/node/v18.20.8/bin/node',
    exists: (p) => fsMap.has(p),
    readdir: () => ['v18.20.8', 'v22.22.3', 'v20.20.2'],
  });
  assert.deepEqual(out, ['/custom/node', '/h/.nvm/versions/node/v22.22.3/bin/node', '/h/.nvm/versions/node/v20.20.2/bin/node', '/opt/homebrew/bin/node']);
});

test('findReplacementNode: first candidate that probes >= floor wins; failures recorded', () => {
  const versions = { '/a': '18.20.8', '/b': null, '/c': '20.19.0', '/d': '23.10.0' };
  const probed = [];
  const pick = findReplacementNode({ candidates: ['/a', '/b', '/c', '/d'], probe: (p) => versions[p], probed });
  assert.deepEqual(pick, { path: '/c', version: '20.19.0' });
  assert.deepEqual(
    probed.map((p) => p.path),
    ['/a', '/b', '/c'],
  );
  assert.equal(findReplacementNode({ candidates: ['/a', '/b'], probe: (p) => versions[p] }), null);
});

test('probeNodeVersion: the running Node answers with its own version; a non-node binary is null', () => {
  assert.equal(probeNodeVersion(process.execPath), process.versions.node);
  assert.equal(probeNodeVersion('/bin/echo'), null);
  assert.equal(probeNodeVersion('/definitely/not/here'), null);
});

test('launcher: forced-old version re-execs under the override Node; --node-check reports the re-exec', () => {
  const r = spawnSync(process.execPath, [LAUNCHER, '--node-check'], {
    encoding: 'utf8',
    env: { ...process.env, DAVINCI_RESOLVE_ADVANCED_ASSUME_NODE: '18.20.8', DAVINCI_RESOLVE_NODE: process.execPath },
  });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stderr, /below the supported floor .* re-executing under/);
  const report = JSON.parse(r.stdout);
  assert.equal(report.reexec, true);
  assert.equal(report.execPath, process.execPath);
  assert.equal(report.node, process.versions.node);
});

test('launcher: --version and --help answer before the floor, whatever Node started them', () => {
  const r = spawnSync(process.execPath, [LAUNCHER, '--version'], {
    encoding: 'utf8',
    env: { ...process.env, DAVINCI_RESOLVE_ADVANCED_ASSUME_NODE: '18.20.8', DAVINCI_RESOLVE_ADVANCED_NO_NODE_SEARCH: '1' },
  });
  assert.equal(r.status, 0);
  assert.match(r.stdout, /^\d+\.\d+\.\d+/);
  assert.equal(r.stderr, '');
});

test('launcher: forced-old version with no usable replacement refuses with the fix and what it probed', () => {
  const r = spawnSync(process.execPath, [LAUNCHER, '--node-check'], {
    encoding: 'utf8',
    env: {
      ...process.env,
      DAVINCI_RESOLVE_ADVANCED_ASSUME_NODE: '18.20.8',
      DAVINCI_RESOLVE_NODE: '/bin/echo',
      DAVINCI_RESOLVE_ADVANCED_NO_NODE_SEARCH: '1',
    },
  });
  assert.equal(r.status, 1);
  assert.match(r.stderr, /below the supported floor/);
  assert.match(r.stderr, /Fix: point the MCP registration/);
  assert.match(r.stderr, /probed: \/bin\/echo \(not node\)/);
});
