/**
 * Project-library discovery across BOTH Resolve editions.
 *
 * Studio keeps its library under Application Support. The free edition ships
 * from the App Store and runs sandboxed, so its library is inside the app
 * container under a differently-named root. Searching only the Studio root made
 * `project_db` resolved by projectName fail with "no Project.db found" for every
 * free-edition user — the exact audience the in-app bridge exists to serve.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  DISK_DB_ROOT,
  PROJECT_LIBRARY_ROOT,
  LITE_DB_ROOT,
  DB_ROOTS,
  findProjectDb,
  resolveDbPath,
} from '../server/db-patch.mjs';

test('every library root is searched, Studio layouts first', () => {
  // Both Studio layouts are real: older installs use "Resolve Disk Database",
  // stock modern installs use "Resolve Project Library" (issue #169).
  assert.deepEqual(DB_ROOTS, [DISK_DB_ROOT, PROJECT_LIBRARY_ROOT, LITE_DB_ROOT]);
  assert.match(PROJECT_LIBRARY_ROOT, /Application Support\/Blackmagic Design\/DaVinci Resolve\/Resolve Project Library\/Resolve Projects$/);
});

test('the free-edition root points inside the App Store sandbox container', () => {
  // Pinned because it is not derivable: the container id and the "Resolve
  // Project Library" folder name both differ from the Studio layout.
  assert.match(LITE_DB_ROOT, /Library\/Containers\/com\.blackmagic-design\.DaVinciResolveLite\/Data\//);
  assert.match(LITE_DB_ROOT, /Resolve Project Library\/Resolve Projects$/);
  assert.ok(!LITE_DB_ROOT.includes('Resolve Disk Database'), 'must not reuse the Studio root name');
});

test('findProjectDb locates a project under an arbitrary root', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dbroot-'));
  const proj = path.join(root, 'Users', 'guest', 'Projects', 'MyProject');
  fs.mkdirSync(proj, { recursive: true });
  fs.writeFileSync(path.join(proj, 'Project.db'), '');

  const hits = findProjectDb('MyProject', root);
  assert.equal(hits.length, 1);
  assert.equal(hits[0], path.join(proj, 'Project.db'));

  assert.deepEqual(findProjectDb('NoSuchProject', root), []);
  fs.rmSync(root, { recursive: true, force: true });
});

test('a missing project names the searched and skipped roots', () => {
  // Hermetic on purpose: walking the REAL machine roots hung this suite when
  // macOS rendered the Lite sandbox container unresponsive (measured live
  // 2026-08-30 — `ls` itself hung). Tests pass explicit roots; production
  // callers go through responsiveRoots() for the same reason.
  const a = fs.mkdtempSync(path.join(os.tmpdir(), 'dbroot-a-'));
  const b = fs.mkdtempSync(path.join(os.tmpdir(), 'dbroot-b-'));
  try {
    assert.throws(
      () => resolveDbPath({
        projectName: '__nope__',
        roots: [a, b],
        skippedRoots: [{ root: '/stalled/container', reason: 'unresponsive' }],
      }),
      (err) =>
        err.message.includes(a) &&
        err.message.includes(b) &&
        err.message.includes('/stalled/container') &&
        err.message.includes('unresponsive'),
    );
  } finally {
    fs.rmSync(a, { recursive: true, force: true });
    fs.rmSync(b, { recursive: true, force: true });
  }
});

test('responsiveRoots keeps answering and absent roots', async () => {
  const { responsiveRoots } = await import('../server/db-patch.mjs');
  const real = fs.mkdtempSync(path.join(os.tmpdir(), 'dbroot-live-'));
  try {
    const { roots, skipped } = await responsiveRoots([real, '/no/such/dir/anywhere'], 2000);
    assert.ok(roots.includes(real));
    assert.ok(roots.includes('/no/such/dir/anywhere'), 'ENOENT answers fast — kept for the walk to no-op');
    assert.deepEqual(skipped, []);
  } finally {
    fs.rmSync(real, { recursive: true, force: true });
  }
});

test('an explicit projectDb path bypasses discovery entirely', () => {
  // Relocated libraries, Postgres, and the free edition on Windows/Linux all
  // land here — discovery must never be the only way in.
  assert.equal(resolveDbPath({ projectDb: '/somewhere/else/Project.db' }), '/somewhere/else/Project.db');
});

test('neither projectDb nor projectName is an explicit error', () => {
  assert.throws(() => resolveDbPath({}), /provide projectDb \(path\) or projectName/);
});
