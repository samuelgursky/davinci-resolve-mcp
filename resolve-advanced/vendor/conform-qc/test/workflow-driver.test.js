'use strict';

/** ResolveDriver interface + conformQcWorkflow (activity unit-invoked, no cluster). */

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const pkg = require('../index');
const { ResolveDriver, FakeResolveDriver, isResolveDriver } = require('../adapters/resolve-driver');
const { conformQcActivity, conformQcWorkflow } = require('../ops/workflow');
const { verify } = require('../ops/verify');

const GOLDEN = JSON.parse(fs.readFileSync(path.join(pkg.reelFixtureDir(), 'golden_oracle.json'), 'utf8'));

test('ResolveDriver: interface throws until implemented; fake conforms + reads back', async () => {
  const base = new ResolveDriver();
  assert.equal(isResolveDriver(base), true);
  await assert.rejects(() => base.clipWhere(), /must be implemented/);
  const fake = new FakeResolveDriver({ 192: 47962, 240: 24263 });
  await fake.importTimeline('/tmp/conform.xml');
  const rows = await fake.clipWhere();
  assert.equal(rows.find((r) => r.seqstart === 192).source_start, 47962);
  assert.equal(isResolveDriver(fake), true);
});

test('conformQcWorkflow: activity is unit-invokable and equals a direct verify()', async () => {
  // The activity (heavy work) over the Tier-C golden reel.
  const direct = await verify(GOLDEN, {});
  const viaActivity = await conformQcActivity(GOLDEN, {});
  assert.deepEqual(viaActivity.summary, direct.summary, 'activity report must match a direct verify()');

  // The workflow returns the store-ready metadata.editorial.qc shape.
  const out = await conformQcWorkflow({ model: GOLDEN });
  for (const k of ['runAt', 'target', 'oracleVersion', 'tier', 'summary', 'perCut', 'packageKeys']) {
    assert.ok(k in out.qc, `workflow qc output must have "${k}"`);
  }
  assert.equal(out.qc.summary.mathVerified, 327);

  // The activity is injectable (the Temporal worker provides it via proxyActivities).
  let injected = false;
  const out2 = await conformQcWorkflow({ model: GOLDEN }, { conformQcActivity: async (m, o) => { injected = true; return verify(m, o); } });
  assert.equal(injected, true);
  assert.equal(out2.qc.summary.mathVerified, 327);
});
