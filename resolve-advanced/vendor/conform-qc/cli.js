'use strict';

/**
 * cli.js — local/post-assistant entry for the verify pass (spec §13 P1).
 *
 * Usage:
 *   node cli.js verify <model.json> [--json]
 *
 * <model.json> is a ConformModel ({ sequence, ticksPerFrame, clips[] }) — e.g.
 * a golden_oracle.json or the synthetic fixture. (Parsing a raw turnover.xml into
 * a model is parse/; this CLI takes the already-parsed model so it runs anywhere.)
 * Tier C by default (no reference); a reference provider / vision validator are
 * wired by the surfaces, not the bare CLI.
 *
 * Prints a summary (+ per-cut lines with --json). Exit 0 on success.
 */

const fs = require('fs');
const { verify } = require('./ops/verify');

function formatSummary(report) {
  const s = report.summary;
  return (
    `conform-qc verify — target=${report.target} tier=${report.tier || 'C'}\n` +
    `  cuts: ${report.perCut.length}\n` +
    `  matched=${s.matched} offset=${s.offset} wrong=${s.wrong} ` +
    `review=${s.review} math-verified=${s.mathVerified} flagged=${s.flagged}`
  );
}

/**
 * Run the CLI programmatically (testable). Returns { code, report, output }.
 * @param {string[]} argv  args after `node cli.js`
 * @param {object} [io]    { readFile?, verifyFn? } for injection in tests
 */
async function runCli(argv, io = {}) {
  const readFile = io.readFile || ((p) => fs.readFileSync(p, 'utf8'));
  const verifyFn = io.verifyFn || verify;
  const [cmd, modelPath, ...rest] = argv;
  if (cmd !== 'verify' || !modelPath) {
    return { code: 2, output: 'usage: conform-qc verify <model.json> [--json]' };
  }
  let model;
  try {
    model = JSON.parse(readFile(modelPath));
  } catch (e) {
    return { code: 1, output: `error: cannot read model "${modelPath}": ${e.message}` };
  }
  const report = await verifyFn(model, {});
  const asJson = rest.includes('--json');
  const output = asJson ? JSON.stringify({ summary: report.summary, perCut: report.perCut }, null, 2) : formatSummary(report);
  return { code: 0, report, output };
}

module.exports = { runCli, formatSummary };

if (require.main === module) {
  runCli(process.argv.slice(2)).then((r) => {
    // eslint-disable-next-line no-console
    console.log(r.output);
    process.exit(r.code);
  });
}
