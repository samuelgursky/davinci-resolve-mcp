# Social Delivery Workflow Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add six generic compound Resolve MCP actions and migrate `ig-post` to use them.

**Architecture:** Add private helpers beside the existing project, timeline, color, thumbnail, and render helpers in `src/server.py`, then expose them through their existing compound tool dispatchers and action help. Compose existing primitives rather than duplicating Resolve API policy. Keep the external skill manifest as the durable workflow journal.

**Tech Stack:** Python 3.12, FastMCP, `unittest`, fake Resolve objects, standard-library image/ffprobe helpers.

## Global Constraints

- Add no new MCP tool and no required third-party dependency.
- Keep Instagram-specific decisions outside the MCP.
- Mutating compound actions default to dry-run or require explicit execution.
- Preserve existing action behavior and aliases.
- Use structured errors and per-stage/per-item evidence.

---

### Task 1: Delivery preflight

**Files:**
- Modify: `src/server.py`
- Create: `tests/test_delivery_preflight.py`
- Modify: `tests/test_action_help.py`

**Interfaces:**
- Consumes: `_timeline_list_items_detailed`, `_timeline_conform_snapshot`, `_detect_gaps_overlaps_from_snapshot`, `_fairlight_boundary_report`, `_resolve_delivery_target_live`.
- Produces: `_render_delivery_preflight(proj, p) -> dict`; `render(action="delivery_preflight")`.

- [ ] Write tests asserting a ready vertical timeline, offline-media blocker, unavailable Fairlight preset warning, invalid profile error, and action help.
- [ ] Run `python -m unittest tests.test_delivery_preflight tests.test_action_help -v`; verify failures are missing-action failures.
- [ ] Implement the smallest read-only aggregator with normalized `ready`, `blockers`, `warnings`, and evidence sections.
- [ ] Re-run the tests and existing `tests.test_timeline_items_detailed`; require zero failures.
- [ ] Commit `feat(render): add delivery preflight`.

### Task 2: Idempotent project/timeline setup

**Files:**
- Modify: `src/server.py`
- Create: `tests/test_ensure_project_timeline.py`
- Modify: `tests/test_action_help.py`

**Interfaces:**
- Consumes: project-manager lookup/create/load/save APIs, project setting setters, media-pool import and timeline creation APIs.
- Produces: `_ensure_project_timeline(pm, p) -> dict`; `project_manager(action="ensure_project_timeline")`.

- [ ] Write tests for dry-run default, fresh setup, exact-state reuse, path-normalized media reuse, conflicting timeline refusal, missing preset failure, and action help.
- [ ] Run the focused tests and verify missing-action failures.
- [ ] Implement staged planning/execution with `execute=False` default and stage statuses `planned`, `created`, `reused`, `applied`, `saved`, or `blocked`.
- [ ] Re-run focused project-manager and import/timeline regression tests.
- [ ] Commit `feat(project): add idempotent timeline setup`.

### Task 3: Exposure planning

**Files:**
- Create: `src/utils/exposure_plan.py`
- Modify: `src/server.py`
- Create: `tests/test_exposure_plan.py`
- Modify: `tests/test_action_help.py`

**Interfaces:**
- Consumes: detailed item dictionaries containing `timeline_item_id`, `file_path`, `online_status`, `source_start`, and `source_end`.
- Produces: `build_exposure_plan(items, analyzer) -> dict`; `timeline(action="exposure_plan")`.

- [ ] Write pure tests for deduplicated source ranges, stable result fan-out, offline/missing paths, degenerate analysis, and analyzer errors; add dispatcher/help tests.
- [ ] Run tests and verify the helper/action are absent.
- [ ] Implement the standard-library orchestration helper and an injectable default analyzer adapter; do not apply mutations.
- [ ] Re-run exposure and timeline inventory tests.
- [ ] Commit `feat(timeline): add exposure planning`.

### Task 4: Bulk DRX plus per-item CDL

**Files:**
- Modify: `src/server.py`
- Create: `tests/test_bulk_drx_cdls.py`
- Modify: `tests/test_action_help.py`

**Interfaces:**
- Consumes: `_find_timeline_item_by_id`, `_validate_cdl`, `_safe_apply_drx`, `_safe_set_cdl`, confirmation-token helpers.
- Produces: `_timeline_apply_drx_and_cdls_bulk(proj, tl, p) -> dict`; `timeline(action="apply_drx_and_cdls_bulk")`.

- [ ] Write tests for dry-run default, complete preflight refusal, one-token flow, DRX-before-CDL ordering, optional CDL, stop-on-first-failure evidence, and action help.
- [ ] Run tests and verify missing-action failures.
- [ ] Implement validation, one compound confirmation, per-item grade snapshot attempt, ordered mutation, and explicit partial results.
- [ ] Re-run bulk tests plus existing color and `apply_look_to_items` suites.
- [ ] Commit `feat(color): add bulk DRX and CDL workflow`.

### Task 5: Cover-frame candidates

**Files:**
- Create: `src/utils/cover_candidates.py`
- Modify: `src/server.py`
- Create: `tests/test_cover_frame_candidates.py`
- Modify: `tests/test_action_help.py`

**Interfaces:**
- Consumes: thumbnail samples from `_timeline_thumbnail_contact_sheet` and optional guarded still export.
- Produces: `rank_cover_candidates(samples) -> list`; `timeline(action="cover_frame_candidates")`.

- [ ] Write pure ranking tests for blank, clipped, blurred, and deterministic tie ordering; add action tests for contact-sheet passthrough and explicit selected-frame export.
- [ ] Run tests and verify missing helper/action failures.
- [ ] Implement dependency-free RGB scoring and wrapper behavior; semantic recognition is out of scope.
- [ ] Re-run cover and existing thumbnail tests.
- [ ] Commit `feat(timeline): add cover frame candidates`.

### Task 6: Complete delivery job

**Files:**
- Modify: `src/server.py`
- Create: `tests/test_complete_delivery_job.py`
- Modify: `tests/test_action_help.py`

**Interfaces:**
- Consumes: `_resolve_delivery_target_live`, existing job preparation/start/status APIs, and returned QC spec.
- Produces: `_render_complete_delivery_job(proj, p) -> dict`; `render(action="complete_delivery_job")`.

- [ ] Write tests for dry-run default, prepare/start/complete, existing-job resume, failed job, bounded timeout, missing output, and unavailable QC evidence.
- [ ] Run tests and verify missing-action failures.
- [ ] Implement a bounded synchronous lifecycle wrapper with `execute=False` default, stable `job_id`, explicit terminal state, output path, and QC evidence.
- [ ] Re-run render lifecycle, delivery-target, and action-help tests.
- [ ] Commit `feat(render): add resumable delivery completion`.

### Task 7: Skill migration and documentation

**Files:**
- Modify: `D:/Dropbox/claude-skills/ig-post/SKILL.md`
- Modify: `docs/kernels/render-deliver-kernel.md`
- Modify: `docs/SKILL.md`
- Create: `tests/test_social_delivery_action_docs.py`

**Interfaces:**
- Consumes: all six new actions and existing `timeline.list_items_detailed`.
- Produces: an updated two-phase Resolve workflow retaining manifest checkpoints and approval gates.

- [ ] Write drift tests asserting all action names are documented and registered; run and verify failures.
- [ ] Update MCP documentation and action help examples.
- [ ] Update `ig-post` Steps 6–10 and 14–18 to use the new compound actions while retaining source probing, manifests, Ozone UI verification, render/publish confirmation gates, and fallbacks.
- [ ] Re-run documentation tests and validate the skill contains no stale three-call inventory loop or fixed-preset-only render path.
- [ ] Commit MCP documentation changes; report the external skill edit separately because it is outside this repository.

### Task 8: Final verification

**Files:**
- No production changes expected.

**Interfaces:**
- Consumes: final repository state.
- Produces: verification evidence and clean Git state.

- [ ] Run every new test module plus adjacent timeline, project-manager, render, color, thumbnail, and action-help suites.
- [ ] Run full repository discovery on both the pre-feature base and final branch when the upstream Windows baseline remains red; compare exact failure names.
- [ ] Run `git diff --check`, inspect the complete diff, and verify `git remote -v` remains empty.
- [ ] Obtain an independent code review, address actionable findings, and repeat focused verification.
