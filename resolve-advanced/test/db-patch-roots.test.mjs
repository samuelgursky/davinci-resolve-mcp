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
  LITE_DB_ROOT,
  DB_ROOTS,
  findProjectDb,
  resolveDbPath,
} from '../server/db-patch.mjs';

test('both edition roots are searched, Studio first', () => {
  assert.deepEqual(DB_ROOTS, [DISK_DB_ROOT, LITE_DB_ROOT]);
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

test('a missing project names both roots so the user knows where it looked', () => {
  assert.throws(
    () => resolveDbPath({ projectName: '__almost_certainly_not_a_real_project__' }),
    (err) => err.message.includes(DISK_DB_ROOT) && err.message.includes(LITE_DB_ROOT),
  );
});

test('an explicit projectDb path bypasses discovery entirely', () => {
  // Relocated libraries, Postgres, and the free edition on Windows/Linux all
  // land here — discovery must never be the only way in.
  assert.equal(resolveDbPath({ projectDb: '/somewhere/else/Project.db' }), '/somewhere/else/Project.db');
});

test('neither projectDb nor projectName is an explicit error', () => {
  assert.throws(() => resolveDbPath({}), /provide projectDb \(path\) or projectName/);
});
