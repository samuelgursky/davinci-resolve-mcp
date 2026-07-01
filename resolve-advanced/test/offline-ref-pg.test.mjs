/**
 * PostgreSQL backend for the offline-reference live-DB patch — PROJECT-SCOPED.
 * Fixture-free: an injected fake pg client models a shared DB with TWO projects
 * (each a no-owner Master + a subfolder), a real reference in project A, and a
 * cross-project GHOST with the same name in project B. The resolver must scope to
 * the target project, refuse bare names, and reject cross-project clips.
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import { listInProject, linkInProject, unlinkInProject } from '../server/offline-ref-db.mjs';

// Folder tree (id -> owner); null owner = a project Master root.
const FOLDERS = { mA: null, sA: 'mA', mB: null, sB: 'mB' };
const walkUp = (f) => {
  let cur = f;
  while (FOLDERS[cur] != null) cur = FOLDERS[cur];
  return cur;
};
const subtree = (master) => Object.keys(FOLDERS).filter((f) => walkUp(f) === master);

function makeFakeClient({ timelines, media }) {
  const state = { offlineClip: timelines[0]?.OfflineClip ?? null, frameOffset: timelines[0]?.OfflineFrameOffset ?? 0, queries: [] };
  return {
    state,
    async query(sql, params = []) {
      state.queries.push(sql.replace(/\s+/g, ' ').trim());
      if (sql.includes('information_schema')) return { rows: state.schemaOk === false ? [] : [{ ok: 1 }] };
      if (sql.includes('RECURSIVE up')) return { rows: [{ id: walkUp(params[0]) }] };
      if (sql.includes('RECURSIVE dn')) return { rows: subtree(params[0]).map((id) => ({ id })) };
      if (sql.includes('AS folder FROM "Sm2MpMedia"')) {
        const m = media.find((x) => x.Sm2MpMedia_id === params[0]);
        return { rows: m ? [{ folder: m.Sm2MpFolder_id }] : [] };
      }
      if (sql.includes('ANY($3')) {
        const scope = params[2];
        return {
          rows: media
            .filter((m) => (m.Name === params[0] || m.Name === params[1]) && scope.includes(m.Sm2MpFolder_id))
            .map((m) => ({ id: m.Sm2MpMedia_id, Name: m.Name })),
        };
      }
      if (sql.includes('ORDER BY "Name"')) {
        return {
          rows: timelines.map((t) => ({
            id: t.Sm2Timeline_id,
            Name: t.Name,
            OfflineClip: t.Sm2Timeline_id === state.tid ? state.offlineClip : (t.OfflineClip ?? null),
            OfflineFrameOffset: t.OfflineFrameOffset ?? 0,
          })),
        };
      }
      if (sql.startsWith('SELECT "Sm2Timeline_id" AS id') && sql.includes('WHERE')) {
        return {
          rows: timelines
            .filter((t) => params[0] === t.Sm2Timeline_id || params[0] === t.Name)
            .map((t) => ({ id: t.Sm2Timeline_id, Name: t.Name, OfflineClip: state.offlineClip })),
        };
      }
      if (sql.startsWith('UPDATE "Sm2Timeline" SET "OfflineClip" = $1')) {
        state.offlineClip = params[0];
        state.frameOffset = params[1];
        return { rows: [] };
      }
      if (sql.startsWith('UPDATE "Sm2Timeline" SET "OfflineClip" = NULL')) {
        state.offlineClip = null;
        return { rows: [] };
      }
      if (sql.includes('SELECT "OfflineClip", "OfflineFrameOffset"'))
        return { rows: [{ OfflineClip: state.offlineClip, OfflineFrameOffset: state.frameOffset }] };
      if (sql.includes('SELECT "OfflineClip" FROM')) return { rows: [{ OfflineClip: state.offlineClip }] };
      return { rows: [] };
    },
    async end() {
      state.ended = true;
    },
  };
}

const TL = { Sm2Timeline_id: '4bc09de2', Name: 'CONFORM_4K', OfflineClip: null, OfflineFrameOffset: 0 };
// real ref in project A, ghost with same name in project B
const REF = { Sm2MpMedia_id: '2c4eb2e5', Name: 'ref.mov', Sm2MpFolder_id: 'sA' };
const GHOST = { Sm2MpMedia_id: 'ghost99', Name: 'ref.mov', Sm2MpFolder_id: 'sB' };

function client(media = [REF, GHOST]) {
  const fake = makeFakeClient({ timelines: [TL], media });
  fake.state.tid = TL.Sm2Timeline_id;
  return fake;
}
function opts(fake, top = {}) {
  return {
    postgres: { host: 'studio', database: 'testdb', __client: fake, __backupFn: () => '/tmp/b.sql' },
    timelineId: '4bc09de2',
    iConfirmProjectClosed: true,
    ...top,
  };
}

test('pg list_in_project returns timelines + linked count', async () => {
  const r = await listInProject({ postgres: { host: 'h', database: 'd', __client: client() } });
  assert.equal(r.backend, 'postgres');
  assert.equal(r.count, 1);
  assert.equal(r.linked, 0);
});

test('referenceName + referenceFolderRoot resolves the IN-PROJECT clip (not the ghost)', async () => {
  const fake = client();
  const r = await linkInProject(opts(fake, { referenceName: 'ref.mov', referenceFolderRoot: 'sA' }));
  assert.equal(r.linkedTo, '2c4eb2e5'); // project-A clip, NOT ghost99
  assert.equal(r.verified, true);
  assert.equal(fake.state.offlineClip, '2c4eb2e5');
});

test('bare referenceName (no folder scope) is REFUSED on Postgres', async () => {
  const fake = client();
  await assert.rejects(() => linkInProject(opts(fake, { referenceName: 'ref.mov' })), /unreliable|referenceFolderRoot/i);
  assert.equal(fake.state.offlineClip, null);
});

test('cross-project ghost is not matched when scoped to the target project', async () => {
  // only the ghost (project B) exists; scoping to project A finds nothing
  const fake = client([GHOST]);
  await assert.rejects(() => linkInProject(opts(fake, { referenceName: 'ref.mov', referenceFolderRoot: 'sA' })), /not found IN THIS PROJECT/i);
  assert.equal(fake.state.offlineClip, null);
});

test('explicit referenceDbId passes through (verified to exist)', async () => {
  const fake = client();
  const r = await linkInProject(opts(fake, { referenceDbId: '2c4eb2e5' }));
  assert.equal(r.linkedTo, '2c4eb2e5');
  assert.equal(fake.state.offlineClip, '2c4eb2e5');
});

test('referenceDbId that is cross-project is rejected when a scope is given', async () => {
  const fake = client();
  await assert.rejects(() => linkInProject(opts(fake, { referenceDbId: 'ghost99', referenceFolderRoot: 'sA' })), /NOT in the target project/i);
  assert.equal(fake.state.offlineClip, null);
});

test('referenceDbId that does not exist is rejected', async () => {
  const fake = client();
  await assert.rejects(() => linkInProject(opts(fake, { referenceDbId: 'nope' })), /not a media pool clip/i);
});

test('multiple in-project name matches refuse (no guess)', async () => {
  const dup = { Sm2MpMedia_id: 'dup', Name: 'ref.mov', Sm2MpFolder_id: 'mA' }; // also project A
  const fake = client([REF, dup, GHOST]);
  await assert.rejects(() => linkInProject(opts(fake, { referenceName: 'ref.mov', referenceFolderRoot: 'sA' })), /multiple in-project/i);
});

test('link refuses without iConfirmProjectClosed', async () => {
  const fake = client();
  await assert.rejects(() => linkInProject(opts(fake, { referenceDbId: '2c4eb2e5', iConfirmProjectClosed: false })), /close the project/i);
  assert.equal(fake.state.offlineClip, null);
});

test('schema guard refuses when OfflineClip column absent', async () => {
  const fake = client();
  fake.state.schemaOk = false;
  await assert.rejects(() => linkInProject(opts(fake, { referenceDbId: '2c4eb2e5' })), /unsupported Postgres schema/i);
});

test('unlink clears the link and verifies', async () => {
  const fake = client();
  fake.state.offlineClip = '2c4eb2e5';
  const r = await unlinkInProject(opts(fake));
  assert.equal(r.verified, true);
  assert.equal(fake.state.offlineClip, null);
});

test('pg backend requires host and database', async () => {
  await assert.rejects(() => listInProject({ postgres: { __client: client(), database: 'x' } }), /provide host/i);
});
