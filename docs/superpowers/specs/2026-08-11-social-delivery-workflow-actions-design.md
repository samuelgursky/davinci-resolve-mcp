# Social Delivery Workflow Actions Design

## Goal

Add six generic compound actions that let an agent prepare, grade, render, verify, and package short-form vertical video with fewer fragile round trips. Instagram-specific policy remains in the `ig-post` skill; the MCP accepts named delivery profiles such as `instagram_reels`.

## Constraints

- Extend existing `project_manager`, `timeline`, and `render` tools; add no new MCP tool.
- Reuse existing safety guards, confirmation tokens, delivery targets, snapshots, and serializers.
- Preserve all existing action behavior and parameter aliases.
- Mutating compound actions default to dry-run or require an explicit execution flag.
- Partial success is always explicit and includes per-stage or per-item results.
- Add no required third-party dependency.

## Actions

### `render.delivery_preflight`

Read-only. Parameters: `profile` (default `instagram_reels`) and optional `include_cover_samples`. It returns project/timeline identity, timeline settings and duration, `list_items_detailed` inventory, gap/overlap findings, offline-media blockers, Fairlight preset visibility, resolved delivery target and QC spec, plus normalized `blockers`, `warnings`, and `ready`.

The action reports unavailable evidence as a warning unless that evidence is required to produce the requested profile. It never changes the current page, timeline, render settings, or queue.

### `project_manager.ensure_project_timeline`

Idempotent setup for one source. Parameters: `project_name`, `timeline_name`, `source_path`, `settings`, optional `fairlight_preset_name`, and `execute` (default false). Dry-run reports planned versus already-satisfied stages. Execution creates or loads the project, applies settings with persistent readback, imports or reuses the source by normalized file path, creates or reuses the named timeline, applies the optional Fairlight preset only when needed, saves, and returns stage evidence.

Conflicting existing state is a blocker, not something silently overwritten. The action does not delete or rename projects, timelines, or media.

### `timeline.apply_drx_and_cdls_bulk`

Applies a shared DRX followed by an optional per-item CDL in one confirmed operation. Parameters: `path`, `items: [{timeline_item_id, cdl?}]`, `require_temp_path`, `dry_run` (default true), and `confirm_token`. The dry-run resolves every item and validates every CDL. Execution refuses if any target is unresolved, obtains one confirmation for the complete plan, creates and verifies a recoverable local grade version for every target before the first DRX mutation, applies DRX then CDL per item, and returns ordered per-item results. It stops on the first failed mutation and identifies completed versus untouched items; it does not claim rollback.

### `timeline.exposure_plan`

Read-only. Parameters: optional explicit `items`, otherwise enabled video items from `list_items_detailed`; sampling controls; and `analyzer` defaulting to the existing lightweight exposure implementation. It uses each source clip's reported frame rate (falling back to `source_fps`) and deduplicates identical `(file_path, source_start, source_end, source_fps)` ranges, checks online/readable sources, and returns per-item stats and proposed CDLs. Missing analyzer capability or source evidence produces structured blockers. It does not apply grades.

### `render.complete_delivery_job`

Resumable render lifecycle wrapper. Parameters: `profile`, `target_dir`, `custom_name`, `execute` (default false), optional `job_id`, and bounded polling controls. Dry-run resolves the delivery target and validates the job. Execution prepares or resumes a job, starts it when needed, polls to a terminal state within the caller’s bound, and returns the output path plus the delivery target’s QC spec. Verification uses the existing local ffprobe-shaped checker when available; unavailable QC is explicit and never converted into success. The action never uploads media.

### `timeline.cover_frame_candidates`

Read-only by default. Parameters: optional frames, `max_samples`, `analysis_root`, `selected_frame`, and `export_path`. It builds on the existing thumbnail sampler, uses marker frames or uniform timeline samples when no markers exist, scores candidates using deterministic image signals (blankness, clipping, and sharpness when available), and returns ranked timecodes with contact-sheet evidence. With an explicitly selected frame and export path, it exports only to a new supported still-image path inside the generated analysis root and refuses source-media conflicts. It does not use semantic face or subject recognition.

## Data Flow

`ensure_project_timeline` establishes idempotent project state. After the human edit, `delivery_preflight` collects a single readiness report. `exposure_plan` produces per-item CDL proposals, which `apply_drx_and_cdls_bulk` applies after confirmation. `cover_frame_candidates` prepares the approval choice. `complete_delivery_job` renders and returns machine-verifiable delivery evidence.

Every action returns stable identifiers (`project_name`, `timeline_id`, `timeline_item_id`, `job_id`) so a caller can persist progress outside the MCP and safely resume.

## Error Model

- Invalid inputs use existing structured `invalid_input` errors.
- Missing Resolve methods use existing version/capability errors.
- Compound results contain `stages` or `items` with explicit statuses.
- Mutating actions refuse execution if preflight resolution is incomplete.
- Timeouts return the current job state and `retryable: true`; they do not delete jobs.
- Existing state is reused only after identity/readback checks.

## Testing

Each action gets contract tests with fake Resolve objects. Tests cover default dry-run behavior, idempotent reuse, conflicts, confirmation-token flow, per-item ordering, DRX-before-CDL ordering, deduped analysis, offline sources, render resume/timeout/failure, deterministic cover ranking, and action-help registration. Existing focused timeline, render, project-manager, and action-help suites remain green.

## Skill Migration

Update `ig-post` to:

1. Use `project_manager.ensure_project_timeline` for Phase 1 while retaining its manifest as the durable cross-application journal.
2. Use `timeline.list_items_detailed` in Step 14.
3. Use `render.delivery_preflight` before grading/rendering.
4. Use `timeline.exposure_plan` and `timeline.apply_drx_and_cdls_bulk` for grading.
5. Use `timeline.cover_frame_candidates` at the thumbnail confirmation gate.
6. Use `render.complete_delivery_job(profile="instagram_reels")` and its returned QC evidence.

Ozone Master Assistant remains a verified UI-assisted step because Resolve’s public API does not expose third-party Fairlight plug-in controls.
