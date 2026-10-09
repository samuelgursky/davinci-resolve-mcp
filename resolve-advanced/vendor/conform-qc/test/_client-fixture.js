'use strict';

/**
 * The full-reel answer key (`__fixtures__/sample-reel-01/golden_oracle.json` and
 * `golden_compare.json`) is derived from client material, so it is not in the
 * repository; `index.js#reelFixtureDir` documents that its dependent tests skip
 * when it is absent. The client-free synthetic fixture (`__fixtures__/synthetic/`,
 * built by `synthetic/generate.js`) is committed and always runs.
 *
 * Not a test file: `node --test` only picks up `*.test.js`.
 */

const fs = require('node:fs');
const path = require('node:path');
const pkg = require('../index');

const DIR = pkg.reelFixtureDir();
const REASON = 'client answer key __fixtures__/sample-reel-01 is not in the repository';

function present() {
  return ['golden_oracle.json', 'golden_compare.json'].every((f) => fs.existsSync(path.join(DIR, f)));
}

/**
 * For a file whose every test needs the answer key: registers one skipped test
 * that says why, and returns true so the caller can `return` before loading it.
 */
function skipFile(test, label) {
  if (present()) return false;
  test(`${label}: needs the client answer key`, { skip: REASON }, () => {});
  return true;
}

module.exports = { present, skipFile, REASON };
