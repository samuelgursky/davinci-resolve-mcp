/**
 * Cluster D — deliverable ENTITY modeling `[cap]`. A "deliverable" is not one file: it's a
 * family of entities each with its own compliance rules — texted (final) + textless (clean,
 * for localization) + stems/M&E (music & effects, audio-only) + slate + leader. Modeling them
 * as first-class entities lets deliverable_qc run the RIGHT rules per entity (a textless master
 * must carry NO burned-in titles; an M&E stem is audio-only with a fixed layout; a slate has a
 * duration rule) instead of one flat spec.
 *
 * PURE: expands a base deliverable spec into concrete entities, each with a merged QC spec +
 * named rules deliverable_qc / loudness_qc consume. No Resolve, no LLM. Tenant-ready: no globals.
 */

// Per-entity defaults layered onto the base master spec. `notes` are human rules a tool can't
// fully verify offline (e.g. "no burned-in text") — surfaced so online/producer check them.
export const ENTITY_DEFAULTS = {
  texted: {
    kind: 'texted',
    describe: 'Final program master with titles/lower-thirds/graphics.',
    specOverride: {},
    rules: ['video_compliance', 'audio_compliance', 'duration'],
    notes: [],
  },
  textless: {
    kind: 'textless',
    describe: 'Clean master for localization — identical picture spec, NO burned-in text.',
    specOverride: {},
    rules: ['video_compliance', 'audio_compliance', 'duration', 'no_burned_in_text'],
    notes: ['no_burned_in_text is not auto-verifiable offline — online must eyeball for residual titles/lower-thirds'],
  },
  stems_ME: {
    kind: 'stems_ME',
    describe: 'Music & Effects stem — audio-only deliverable, dialogue removed.',
    // Audio-only: drop the video spec; keep/override the audio layout.
    dropVideo: true,
    specOverride: {},
    rules: ['audio_compliance', 'loudness', 'no_dialogue'],
    notes: ['no_dialogue is not auto-verifiable offline — mix/online confirms dialogue is absent'],
  },
  slate: {
    kind: 'slate',
    describe: 'Slate/ident — fixed short duration with programme metadata.',
    specOverride: {},
    rules: ['duration', 'video_compliance'],
    notes: ['slate content (title/ep/date) is a human check'],
  },
  leader: {
    kind: 'leader',
    describe: 'Countdown/black leader ahead of programme start.',
    specOverride: {},
    rules: ['duration'],
    notes: [],
  },
};

/** Shallow-merge a spec override onto a base spec (per top-level block). */
function mergeSpec(base = {}, override = {}, dropVideo = false) {
  const out = { ...base, ...override };
  if (base.video || override.video) out.video = { ...(base.video || {}), ...(override.video || {}) };
  if (base.audio || override.audio) out.audio = { ...(base.audio || {}), ...(override.audio || {}) };
  if (dropVideo) delete out.video;
  return out;
}

/**
 * Expand a base deliverable into its entities.
 * @param {{name?:string, spec:object, entities?:string[]}} deliverable
 *   spec = the master compliance spec (video/audio/container/duration/...); entities = kinds to emit.
 * @returns {{name:string, entities:Array<{kind, name, describe, spec, rules, notes}>}}
 */
export function expandDeliverable(deliverable) {
  const name = deliverable.name || 'deliverable';
  const kinds = deliverable.entities && deliverable.entities.length ? deliverable.entities : ['texted'];
  const entities = kinds.map((k) => {
    const def = ENTITY_DEFAULTS[k];
    if (!def) throw new Error(`expandDeliverable: unknown entity kind '${k}' (known: ${Object.keys(ENTITY_DEFAULTS).join(', ')})`);
    return {
      kind: def.kind,
      name: `${name}.${def.kind}`,
      describe: def.describe,
      spec: mergeSpec(deliverable.spec || {}, def.specOverride, def.dropVideo),
      rules: def.rules,
      notes: def.notes,
    };
  });
  return { name, entities };
}
