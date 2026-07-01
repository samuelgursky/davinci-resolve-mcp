/**
 * E0 — the doc-interview type-default blocks (leveling / audio / deliverables / qc /
 * pipeline) compile through inheritance and drive a runnable plan. Hermetic: writes a
 * representative type+episode YAML to a temp dir (the real authoring file is not
 * committed, so a committed test can't depend on it).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { openProjectDb, getEntity } from '../server/project-db.mjs';
import { loadYamlDir, compileSpecs } from '../server/spec-compile.mjs';
import { planRun } from '../server/runner.mjs';

const T = '2026-06-29T00:00:00Z';

const TYPE_YML = `
type: doc-iv
grade:
  color_science: acescct
  output_transform: "Rec.709"
  leveling:
    mode: within_camera_mean
    groups: [guest, host, wide]
    clamp_gain: [0.5, 2.0]
    over_correction_warn: 0.12
    apply: false
audio:
  sync: { method: timecode, fallback: waveform }
  loudness_default: "-14 LUFS"
deliverables:
  - id: prores_master
    video: { codec: "ProRes 422 HQ", res: "1920x1080", fps: 23.976 }
    audio: { loudness: "-16 LUFS" }
  - id: youtube_main
    inherits: prores_master
    video: { codec: "H.264" }
    audio: { loudness: "-14 LUFS" }
qc:
  conform: { structure_min: 0.90 }
  loudness: { tolerance: "1.0 LU" }
pipeline:
  - conform
  - offline_ref
  - color_groups
  - { stage: leveling, gate: review }
  - grade
  - audio_sync
  - { stage: qc, gate: pass }
  - deliver
`;

const EP_YML = `
kind: episode
type: doc-iv
guest: TestGuest
`;

test('E0: type-default blocks compile via inheritance and drive a runnable plan', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'e0-'));
  fs.mkdirSync(path.join(dir, '_types'));
  fs.writeFileSync(path.join(dir, '_types', 'doc-iv.yml'), TYPE_YML);
  fs.writeFileSync(path.join(dir, 'ep.yml'), EP_YML);

  const db = openProjectDb(path.join(dir, 'project.db'));
  const specs = loadYamlDir(dir);
  const typeSpec = specs.find((s) => s.kind === 'type');
  assert.equal(typeSpec.slug, 'doc-iv', 'type slug from `type:` field');
  const epSpec = specs.find((s) => s.kind === 'episode');
  assert.equal(epSpec.parent, 'doc-iv', 'episode inherits its `type:` as parent');

  compileSpecs(db, specs, { now: T });

  // Episode inherits ALL the type-default blocks.
  const ep = getEntity(db, 'ep').resolved;
  assert.equal(ep.grade.color_science, 'acescct');
  assert.deepEqual(ep.grade.leveling.groups, ['guest', 'host', 'wide']);
  assert.equal(ep.audio.loudness_default, '-14 LUFS');
  assert.equal(ep.deliverables.length, 2);
  const yt = ep.deliverables.find((d) => d.id === 'youtube_main');
  assert.equal(yt.video.codec, 'H.264', 'own codec override');
  assert.equal(yt.video.fps, 23.976, 'fps INHERITED from prores_master sibling');
  assert.equal(yt.video.res, '1920x1080', 'res inherited');
  assert.ok(!('inherits' in yt), 'inherits key dropped (not an inert field)');
  assert.equal(ep.qc.conform.structure_min, 0.9);
  assert.equal(ep.guest, 'TestGuest', 'episode override preserved');

  // The inherited pipeline drives a plan with correct modes/gates/config wiring.
  const plan = planRun(db, 'ep', { now: T });
  assert.deepEqual(
    plan.stages.map((s) => s.stage),
    ['conform', 'offline_ref', 'color_groups', 'leveling', 'grade', 'audio_sync', 'qc', 'deliver'],
  );
  const leveling = plan.stages.find((s) => s.stage === 'leveling');
  assert.equal(leveling.mode, 'deterministic');
  assert.equal(leveling.gate, 'review');
  assert.deepEqual(leveling.config.groups, ['guest', 'host', 'wide'], 'leveling stage reads grade.leveling');
  assert.equal(plan.stages.find((s) => s.stage === 'qc').gate, 'pass');
  assert.equal(plan.stages.find((s) => s.stage === 'deliver').mode, 'resolve');
  assert.equal(plan.stages.find((s) => s.stage === 'deliver').config.length, 2, 'deliver reads the deliverables list');
  db.close();
});
