/**
 * RESOLVE_VERIFY helper.
 *
 * Test files that include Resolve-in-loop assertions (apply DRX via
 * davinci-resolve-mcp, frame-compare via export_frame_as_still, etc.)
 * gate themselves with this helper so CI environments without Resolve
 * don't fail spuriously, and local sessions can opt-in by setting
 * RESOLVE_VERIFY=1.
 *
 * Usage:
 *   const test = require('node:test');
 *   const { resolveVerifyTest } = require('./_resolve-verify');
 *   resolveVerifyTest('apply DRX matches direct render', async () => {
 *     // ... uses davinci-resolve-mcp via stdio ...
 *   });
 *
 * When RESOLVE_VERIFY is set to '1' or 'true', the test runs
 * normally. Otherwise it's marked skip with a clear reason.
 */

const test = require('node:test');

function isResolveVerifyEnabled() {
  const v = process.env.RESOLVE_VERIFY;
  return v === '1' || v === 'true' || v === 'yes';
}

function resolveVerifyTest(name, fn) {
  if (!isResolveVerifyEnabled()) {
    test.skip(`${name} (skipped — set RESOLVE_VERIFY=1 to enable)`, () => {});
    return;
  }
  test(name, fn);
}

module.exports = {
  isResolveVerifyEnabled,
  resolveVerifyTest,
};
