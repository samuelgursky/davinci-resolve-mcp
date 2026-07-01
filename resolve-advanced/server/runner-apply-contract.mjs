/**
 * runner→apply CONTRACT (P2b) — formalize each resolve-mode stage plan `{mode:'resolve', stage,
 * config}` into a clean, documented, directly-consumable shape that maps 1:1 to the Python live
 * server's apply actions, so an orchestrator dispatches with NO glue. The runner EMITS this; it
 * NEVER calls it (Node can't drive Resolve — apply lives in the Python live server).
 *
 * Deterministic stages produce ARTIFACTS (drx paths, reports) the apply stages consume; where an
 * arg is a runtime artifact (per-clip drxPath from leveling), the contract names its source via
 * `argsFrom` rather than inventing a value.
 *
 * VERIFY against the live server's real action names/args before finalizing (first real-footage session).
 */

// stage → the Python action(s) + how each action's args derive from the resolved config.
export const APPLY_CONTRACT = {
  ingest: [{ action: 'media_storage.copy_verify', argsFrom: (c) => ({ cards: c?.cards ?? null, checksum: c?.checksum ?? 'mhl' }) }],
  conform: [
    {
      action: 'media_pool.import_timeline',
      argsFrom: (c) => ({ pathMaps: c?.path_maps ?? c?.pathMaps ?? null, xml: c?.xml ?? null, importSourceClips: true, sanitize: true }),
    },
  ],
  offline_ref: [{ action: 'offline_ref.attach', argsFrom: (c) => ({ picref: c?.picref ?? c?.reference ?? null, timeline: c?.timeline ?? null }) }],
  color_groups: [
    { action: 'color_group.create', argsFrom: (c) => ({ groups: c?.taxonomy ?? c?.groups ?? null }) },
    { action: 'color_group.assign', argsFrom: (c) => ({ sourceCameraToGroup: c?.source_map ?? c?.assign ?? null }) },
  ],
  grade: [
    {
      action: 'timeline_item_color.safe_apply_drx',
      argsFrom: (c) => ({ gradeMode: c?.gradeMode ?? c?.mode ?? 'group', perClipDrx: 'ARTIFACT:leveling/grade stage drxPath[]' }),
    },
  ],
  leveling: [
    // Leveling is deterministic in Node (it produces the drx artifacts); its APPLY is the grade stage.
    { action: 'timeline_item_color.safe_apply_drx', argsFrom: () => ({ perClipDrx: 'ARTIFACT:leveling stage grades[].drxPath', gradeMode: 'clip' }) },
  ],
  audio_sync: [
    { action: 'timeline.auto_sync_audio', argsFrom: (c) => ({ method: c?.sync ?? 'waveform' }) },
    { action: 'fairlight.route', argsFrom: (c) => ({ busMap: c?.bus_map ?? c?.busMap ?? null }) },
    { action: 'fairlight.loudness', argsFrom: (c) => ({ target: c?.loudness ?? c?.target ?? null }) },
  ],
  qc: [{ action: 'noop', argsFrom: () => ({ note: 'qc is deterministic in Node (gamut_legal/deliverable_qc/verify_grade) — no live apply' }) }],
  deliver: [
    {
      action: 'render.add_job',
      argsFrom: (c) => ({ deliverables: c?.deliverables ?? c ?? null, note: 'expand deliverable entities → render preset + naming' }),
    },
  ],
};

/**
 * Turn a runner resolve-stage plan into the directly-consumable apply contract.
 * @param {{stage:string, config?:object}} plan
 * @returns {{stage:string, actions:Array<{action:string, args:object}>}}
 */
export function toApplyContract(plan) {
  const spec = APPLY_CONTRACT[plan.stage];
  if (!spec) return { stage: plan.stage, actions: [{ action: 'unknown', args: {} }], unmapped: true };
  return {
    stage: plan.stage,
    actions: spec.map((s) => ({ action: s.action, args: s.argsFrom(plan.config || {}) })),
  };
}
