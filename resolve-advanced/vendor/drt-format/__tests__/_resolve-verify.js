// See packages/drp-format/__tests__/_resolve-verify.js for the full docstring.
// This is a copy so each package's test file doesn't reach across package
// boundaries. The contract is shared and documented in
// docs/design/drp-drx-drt-closeout-harness/knowledge/resolve-verifications.md.

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

module.exports = { isResolveVerifyEnabled, resolveVerifyTest };
