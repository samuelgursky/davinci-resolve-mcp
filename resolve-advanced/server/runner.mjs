/**
 * Pipeline runner (B1) — the orchestration spine. Reads an episode's RESOLVED `pipeline:`
 * from the canonical DB and runs the stages in order: gates pause for sign-off, every
 * action writes provenance, deterministic stages execute now, Resolve-apply stages emit
 * an action plan for the live agent (Node can't drive Resolve). Idempotent + re-runnable.
 *
 *
 * The executor is INJECTED — the runner owns ordering/gates/provenance/status; the caller
 * owns "actually run this tool with these frames" (and live apply). That boundary keeps
 * the spine testable offline and honest about what Node can and can't do.
 */
import { getEntity, createRun, setRunStatus, upsertRunStage, getRun, recordProvenance, hashConfig } from './project-db.mjs';
import { STAGE_PLAN } from './tool-catalog.mjs';
import { deepMerge } from './spec-compile.mjs';
import { toApplyContract } from './runner-apply-contract.mjs';

// Where each stage reads its config block out of the resolved episode config — keyed to
// the real authoring schema (the `grade:` block holds color/groups/leveling).
const STAGE_CONFIG_PATH = {
  ingest: 'ingest',
  conform: 'conform',
  offline_ref: 'offline_ref',
  color_groups: 'grade.groups',
  leveling: 'grade.leveling',
  grade: 'grade',
  audio_sync: 'audio',
  qc: 'qc',
  deliver: 'deliverables',
};
const getByPath = (o, p) =>
  String(p)
    .split('.')
    .reduce((x, k) => (x == null ? undefined : x[k]), o);

function normalizeStage(st) {
  return typeof st === 'string' ? { stage: st, gate: null } : { stage: st.stage, gate: st.gate ?? null, ...st };
}

/**
 * Plan a run: create the run + one pending row per pipeline stage with its resolved
 * config + execution mode. No mutation of Resolve. Returns the ordered plan.
 */
export function planRun(db, episodeSlug, { profile = null, now = null } = {}) {
  const ep = getEntity(db, episodeSlug);
  if (!ep) throw new Error(`planRun: unknown episode '${episodeSlug}'`);
  if (ep.kind !== 'episode') throw new Error(`planRun: '${episodeSlug}' is a ${ep.kind}, not an episode`);
  let resolved = ep.resolved || {};
  if (profile && resolved.profiles && resolved.profiles[profile]) resolved = deepMerge(resolved, resolved.profiles[profile]);
  const pipeline = resolved.pipeline;
  if (!Array.isArray(pipeline) || !pipeline.length) throw new Error(`planRun: episode '${episodeSlug}' has no pipeline:`);

  const specHash = hashConfig({ pipeline, profile });
  const runId = createRun(db, { episodeSlug, profile, specHash, now });
  const stages = pipeline.map(normalizeStage).map((st, i) => {
    const plan = STAGE_PLAN[st.stage] || { mode: 'resolve' };
    const config = getByPath(resolved, STAGE_CONFIG_PATH[st.stage] ?? st.stage) ?? null;
    const gate = st.gate || (plan.mode === 'deterministic' ? null : null); // gate only if authored
    upsertRunStage(db, {
      runId,
      stageIndex: i,
      stage: st.stage,
      gate,
      status: 'pending',
      tool: (plan.tools && plan.tools.join(',')) || plan.tool || null,
      config,
      now,
    });
    return { stageIndex: i, stage: st.stage, mode: plan.mode, gate, tools: plan.tools || (plan.tool ? [plan.tool] : []), note: plan.note, config };
  });
  recordProvenance(db, { runId, episodeSlug, stage: 'plan', tool: 'runner', config: { pipeline }, actor: 'system', result: 'planned', now });
  setRunStatus(db, runId, 'planned', now);
  return { runId, episodeSlug, profile, stages };
}

const stageRow = (run, idx) => run.stages.find((s) => s.stage_index === idx);

/** Mark a gated stage approved so executeStage can proceed. */
export function approveGate(db, runId, stageIndex, { actor = 'human', now = null } = {}) {
  const run = getRun(db, runId);
  if (!run) throw new Error(`approveGate: no run ${runId}`);
  const st = stageRow(run, stageIndex);
  if (!st) throw new Error(`approveGate: no stage ${stageIndex}`);
  upsertRunStage(db, { runId, stageIndex, stage: st.stage, gate: st.gate, status: 'gate_approved', tool: st.tool, result: st.result, now });
  recordProvenance(db, { runId, episodeSlug: run.episode_slug, stage: st.stage, tool: 'gate', actor, result: 'approved', target: `stage:${stageIndex}`, now });
  return { stageIndex, status: 'gate_approved' };
}

/**
 * Execute one stage.
 * - gate present & not yet approved → status 'awaiting_gate' (pauses for sign-off).
 * - deterministic → calls executor(stageInfo) → records result + provenance, status 'done'.
 * - resolve → emits the action plan (resolved config), status 'planned_resolve' (live apply
 * is the agent's job), provenance.
 * @param {(stage:object)=>Promise<any>} executor — runs a deterministic stage's tool.
 */
export async function executeStage(db, runId, stageIndex, { executor, actor = 'system', now = null } = {}) {
  const run = getRun(db, runId);
  if (!run) throw new Error(`executeStage: no run ${runId}`);
  const st = stageRow(run, stageIndex);
  if (!st) throw new Error(`executeStage: no stage ${stageIndex}`);
  if (st.status === 'done') return { stageIndex, status: 'done', result: st.result, cached: true };

  const plan = STAGE_PLAN[st.stage] || { mode: 'resolve' };
  // Stage config is re-derived from the resolved episode (the DB is truth) rather than
  // cached on the stage row — so a recompile is always reflected on the next execute.
  const ep = getEntity(db, run.episode_slug);
  const stageConfig = getByPath(ep.resolved || {}, STAGE_CONFIG_PATH[st.stage] ?? st.stage) ?? null;

  // Gate handling.
  if (st.gate && st.status !== 'gate_approved') {
    upsertRunStage(db, { runId, stageIndex, stage: st.stage, gate: st.gate, status: 'awaiting_gate', tool: st.tool, config: stageConfig, now });
    recordProvenance(db, {
      runId,
      episodeSlug: run.episode_slug,
      stage: st.stage,
      tool: 'runner',
      actor,
      result: 'awaiting_gate',
      target: `stage:${stageIndex}`,
      now,
    });
    return { stageIndex, status: 'awaiting_gate', gate: st.gate };
  }

  if (plan.mode === 'deterministic') {
    if (typeof executor !== 'function') throw new Error(`stage '${st.stage}' is deterministic but no executor was provided`);
    const result = await executor({
      stage: st.stage,
      stageIndex,
      tools: plan.tools || (plan.tool ? [plan.tool] : []),
      config: stageConfig,
      episodeSlug: run.episode_slug,
    });
    upsertRunStage(db, { runId, stageIndex, stage: st.stage, gate: st.gate, status: 'done', tool: st.tool, config: stageConfig, result, now });
    recordProvenance(db, {
      runId,
      episodeSlug: run.episode_slug,
      stage: st.stage,
      tool: st.tool || 'tool',
      config: stageConfig,
      actor,
      result: 'done',
      target: `stage:${stageIndex}`,
      now,
    });
    return { stageIndex, status: 'done', result };
  }

  // resolve-apply stage: emit the plan + the directly-consumable apply CONTRACT (P2b), mark
  // awaiting live apply. The contract maps 1:1 to the Python live server's actions — no glue.
  const actionPlan = { mode: 'resolve', stage: st.stage, note: plan.note, config: stageConfig, apply: toApplyContract({ stage: st.stage, config: stageConfig }) };
  upsertRunStage(db, {
    runId,
    stageIndex,
    stage: st.stage,
    gate: st.gate,
    status: 'planned_resolve',
    tool: st.tool,
    config: stageConfig,
    result: actionPlan,
    now,
  });
  recordProvenance(db, {
    runId,
    episodeSlug: run.episode_slug,
    stage: st.stage,
    tool: 'runner',
    config: stageConfig,
    actor,
    result: 'planned_resolve',
    target: `stage:${stageIndex}`,
    now,
  });
  return { stageIndex, status: 'planned_resolve', plan: actionPlan };
}

/**
 * Drive the run from the first not-done stage, executing deterministic stages until it
 * hits a gate (awaiting sign-off) or a Resolve-apply stage (awaiting live apply). Returns
 * progress + where it stopped and why. Re-runnable: call again after a gate approval / live
 * apply marks the blocking stage done.
 */
export async function runAll(db, runId, { executor, now = null } = {}) {
  let run = getRun(db, runId);
  if (!run) throw new Error(`runAll: no run ${runId}`);
  setRunStatus(db, runId, 'running', now);
  const progressed = [];
  for (const st of run.stages) {
    const idx = st.stage_index;
    const cur = getRun(db, runId).stages.find((s) => s.stage_index === idx);
    if (cur.status === 'done') {
      progressed.push({ stageIndex: idx, status: 'done' });
      continue;
    }
    const r = await executeStage(db, runId, idx, { executor, now });
    progressed.push(r);
    if (r.status === 'awaiting_gate') {
      setRunStatus(db, runId, 'awaiting_gate', now);
      return { runId, stopped: 'awaiting_gate', at: idx, progressed };
    }
    if (r.status === 'planned_resolve') {
      setRunStatus(db, runId, 'awaiting_apply', now);
      return { runId, stopped: 'planned_resolve', at: idx, progressed };
    }
  }
  setRunStatus(db, runId, 'done', now);
  return { runId, stopped: 'complete', progressed };
}

/**
 * Stage resume / partial re-run (Cluster P, PROMOTED to core). Reset a stage (and optionally all
 * downstream stages) back to 'pending' so a subsequent runAll re-executes from there — after a
 * spec edit, a failed apply, or a rejected gate. Idempotent; records provenance.
 * @param {boolean} [resetDownstream=true] also reset every later stage (a spec change invalidates them)
 */
export function rerunStage(db, runId, stageIndex, { resetDownstream = true, actor = 'human', now = null } = {}) {
  const run = getRun(db, runId);
  if (!run) throw new Error(`rerunStage: no run ${runId}`);
  const target = run.stages.find((s) => s.stage_index === stageIndex);
  if (!target) throw new Error(`rerunStage: no stage ${stageIndex}`);
  const reset = run.stages.filter((s) => s.stage_index === stageIndex || (resetDownstream && s.stage_index > stageIndex));
  for (const st of reset) {
    upsertRunStage(db, { runId, stageIndex: st.stage_index, stage: st.stage, gate: st.gate, status: 'pending', tool: st.tool, result: null, now });
  }
  recordProvenance(db, { runId, episodeSlug: run.episode_slug, stage: target.stage, tool: 'runner', actor, result: 'rerun_reset', target: `stage:${stageIndex}${resetDownstream ? '+downstream' : ''}`, now });
  setRunStatus(db, runId, 'planned', now);
  return { runId, reset: reset.map((s) => s.stage_index), from: stageIndex, resetDownstream };
}

/** Resume a paused run from its first not-done stage (thin alias over runAll — the run is re-runnable). */
export async function resumeRun(db, runId, { executor, now = null } = {}) {
  return runAll(db, runId, { executor, now });
}

/** Mark a Resolve-apply stage applied (after the live agent did it), with optional readback result. */
export function markStageApplied(db, runId, stageIndex, { result = null, actor = 'system', now = null } = {}) {
  const run = getRun(db, runId);
  if (!run) throw new Error(`markStageApplied: no run ${runId}`);
  const st = run.stages.find((s) => s.stage_index === stageIndex);
  if (!st) throw new Error(`markStageApplied: no stage ${stageIndex}`);
  upsertRunStage(db, { runId, stageIndex, stage: st.stage, gate: st.gate, status: 'done', tool: st.tool, result: result ?? st.result, now });
  recordProvenance(db, { runId, episodeSlug: run.episode_slug, stage: st.stage, tool: 'live', actor, result: 'applied', target: `stage:${stageIndex}`, now });
  return { stageIndex, status: 'done' };
}
