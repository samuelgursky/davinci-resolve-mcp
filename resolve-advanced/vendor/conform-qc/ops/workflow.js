'use strict';

/**
 * ops/workflow.js — the cloud `conformQcWorkflow` (spec §12, P1), a sibling to
 * editorialParseWorkflow on the render node. The heavy work runs as an ACTIVITY
 * (not in the API route). Authored as plain async functions so the activity is
 * unit-invokable without a live Temporal cluster (the feature's acceptance);
 * the render node wires these into its Temporal worker.
 */

const { verify } = require('./verify');
const report = require('../report');

/** The heavy activity: run the verify pass. (Wrapped as a Temporal activity on the node.) */
async function conformQcActivity(model, options = {}) {
  return verify(model, options);
}

/**
 * The workflow: orchestrate the activity and return the store-ready
 * metadata.editorial.qc shape (§11). `deps.conformQcActivity` is injected by the
 * Temporal worker (proxyActivities); defaults to the in-process activity for unit runs.
 */
async function conformQcWorkflow(input, deps = {}) {
  const activity = deps.conformQcActivity || conformQcActivity;
  const rep = await activity(input.model, input.options || {});
  return { qc: report.toMetadataQc(rep), report: rep };
}

module.exports = { conformQcActivity, conformQcWorkflow };
