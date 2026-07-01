/**
 * pipeline tool — the agent-facing surface of the DB-as-truth foundation (A1–B1).
 *
 * Actions: compile (YAML/specs → canonical DB), list_entities/get_entity/ancestry (read
 * resolved intent), catalog (agent-routable tool descriptors), plan (build a run from the
 * episode's resolved pipeline), execute_stage (run one stage — deterministic stages
 * dispatch to the drx tool with agent-supplied inputs; Resolve stages return an apply
 * plan), approve_gate / mark_applied (lifecycle), readback (record actual + detect drift),
 * get_run / list_runs / provenance / drift (audit).
 *
 * The agent ROUTES (which stage, what inputs, approve gates); the deterministic tools DO
 * the work locally. No Resolve here — Resolve-apply stages emit plans for the live agent.
 */
import { openProjectDb, getEntity, listEntities, ancestry, getRun, listRuns, listProvenance, listDrift } from '../project-db.mjs';
import { compileSpecs, loadYamlDir } from '../spec-compile.mjs';
import { reconcile, driftReport } from '../readback.mjs';
import { CATALOG, listCatalog, getDescriptor } from '../tool-catalog.mjs';
import { planRun, executeStage, approveGate, markStageApplied } from '../runner.mjs';
import { drxTool } from './drx.mjs';

const need = (v, name) => {
  if (v === undefined || v === null) throw new Error(`${name} required`);
  return v;
};

/** Deterministic executor: dispatch a stage to its catalog tool via agent-supplied args. */
function makeExecutor(toolArgs) {
  return async (stage) => {
    const id = (toolArgs && toolArgs.tool) || stage.tools[0];
    const desc = getDescriptor(id);
    if (!desc) throw new Error(`stage '${stage.stage}': no catalog tool '${id}' (choose from ${stage.tools.join('|')})`);
    if (!toolArgs || !toolArgs.args) throw new Error(`stage '${stage.stage}' (${id}) needs toolArgs.args (e.g. {clips, outDir}) — the agent supplies inputs`);
    const out = await drxTool.handler({ action: desc.action, args: toolArgs.args });
    return { tool: id, action: desc.action, ...out };
  };
}

export const pipelineTool = {
  name: 'pipeline',
  description:
    "DB-as-truth pipeline foundation (canonical SQLite project DB). Actions: compile (YAML dir or inline specs → resolved entity tree w/ type→series→episode→deliverable inheritance + validation), list_entities, get_entity, ancestry, catalog (agent-routable tool descriptors + when_to_use/not_for), plan (build a run from an episode's resolved pipeline:), execute_stage (deterministic stages dispatch to the drx tool with agent-supplied inputs; Resolve-apply stages return a plan — Node can't drive Resolve), approve_gate, mark_applied, readback (record decoded actual + detect intent↔actual drift), get_run, list_runs, provenance, drift. Pass `now` (ISO) — this runtime has no clock.",
  async handler({ action, args = {} }) {
    const dbPath = () => need(args.dbPath, 'dbPath');
    const withDb = (fn) => {
      const db = openProjectDb(dbPath());
      try {
        return fn(db);
      } finally {
        db.close();
      }
    };

    switch (action) {
      case 'catalog':
        return args.full ? { catalog: CATALOG } : { catalog: listCatalog() };

      case 'compile':
        return withDb((db) => {
          const specs = args.yamlDir ? loadYamlDir(args.yamlDir) : need(args.specs, 'specs or yamlDir');
          const r = compileSpecs(db, specs, { now: args.now ?? null });
          return { compiled: r.compiled, count: r.compiled.length, from: args.yamlDir ? `yaml:${args.yamlDir}` : 'inline' };
        });

      case 'list_entities':
        return withDb((db) => ({
          entities: listEntities(db, { kind: args.kind, parentSlug: args.parentSlug }).map((e) => ({
            slug: e.slug,
            kind: e.kind,
            parent: e.parent_slug,
            resolve_ref: e.resolve_ref,
          })),
        }));

      case 'get_entity':
        return withDb((db) => getEntity(db, need(args.slug, 'slug')) || { error: `no entity '${args.slug}'` });

      case 'ancestry':
        return withDb((db) => ({ chain: ancestry(db, need(args.slug, 'slug')).map((e) => e.slug) }));

      case 'plan':
        return withDb((db) => planRun(db, need(args.episodeSlug, 'episodeSlug'), { profile: args.profile ?? null, now: args.now ?? null }));

      case 'execute_stage':
        return await (async () => {
          const db = openProjectDb(dbPath());
          try {
            return await executeStage(db, need(args.runId, 'runId'), need(args.stageIndex, 'stageIndex'), {
              executor: makeExecutor(args.toolArgs),
              actor: args.actor ?? 'system',
              now: args.now ?? null,
            });
          } finally {
            db.close();
          }
        })();

      case 'approve_gate':
        return withDb((db) =>
          approveGate(db, need(args.runId, 'runId'), need(args.stageIndex, 'stageIndex'), { actor: args.actor ?? 'human', now: args.now ?? null }),
        );

      case 'mark_applied':
        return withDb((db) =>
          markStageApplied(db, need(args.runId, 'runId'), need(args.stageIndex, 'stageIndex'), {
            result: args.result ?? null,
            actor: args.actor ?? 'system',
            now: args.now ?? null,
          }),
        );

      case 'readback':
        return withDb((db) =>
          reconcile(db, need(args.entitySlug, 'entitySlug'), {
            facts: need(args.facts, 'facts'),
            pushFields: args.pushFields ?? [],
            source: args.source ?? null,
            now: args.now ?? null,
          }),
        );

      case 'drift':
        return withDb((db) => (args.entitySlug ? driftReport(db, args.entitySlug) : { drift: listDrift(db, { status: args.status ?? 'open' }) }));

      case 'get_run':
        return withDb((db) => getRun(db, need(args.runId, 'runId')) || { error: `no run '${args.runId}'` });

      case 'list_runs':
        return withDb((db) => ({ runs: listRuns(db, need(args.episodeSlug, 'episodeSlug')) }));

      case 'provenance':
        return withDb((db) => ({ events: listProvenance(db, { episodeSlug: args.episodeSlug, runId: args.runId }) }));

      default:
        throw new Error(`Unknown pipeline action: ${action}`);
    }
  },
};
