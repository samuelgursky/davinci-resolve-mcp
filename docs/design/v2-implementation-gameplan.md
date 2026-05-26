# V2 Implementation Gameplan

**Purpose:** Durable record of work pending after the initial V2 push. Designed so a fresh Claude session can read this cold and execute without re-litigating decisions.

**Companion docs:**
- `docs/design/v2-shot-schema-spec.md` — the locked V2 schema (authoritative for field names / enums)
- `docs/design/v2-db-schema.sql` — the V2 DB DDL (source-of-truth migration target)
- `~/.claude/projects/-Users-samuelgursky-davinci-resolve-mcp/memory/MEMORY.md` — auto-memory index pointing at architecture decisions

**Last updated:** 2026-05-19 (fourth push: corrections merge + Phase B UI shipped)

---

## 0. How to use this document

A fresh session should:

1. Read `MEMORY.md` to load the architecture context — `project-v2-architecture`, `project-frame-sampling-fix`, `project-v2-first-run-findings`, `feedback-conversational-ux`, `feedback-conservative-descriptions`.
2. Skim §1 below for the status snapshot.
3. Pick a task from §2-§4 that is not blocked.
4. Read the per-task detail in §5 before touching code.
5. Verify against the acceptance criteria before marking done.
6. Do NOT re-litigate decisions already locked in the spec or memory — those are settled.

Pacing: bundle related fixes when they touch the same code path; restart Claude Code between phases to pick up MCP server changes.

---

## 1. Status snapshot

### Done in the V2 pushes (do NOT redo)

| ID | Title | Where landed |
|---|---|---|
| **P0** | Frame sampling: demand-driven, per-shot reservation | `src/utils/media_analysis.py` `_compute_demand_driven_budget`, `_sample_times`, `HARD_FRAME_CAP=512` |
| **P1** | Drop machine markers from Resolve writeback | `src/server.py` `V2_MACHINE_MARKER_WRITEBACK_ENABLED=False` gates `_media_analysis_timed_marker_decision` |
| **P2** | Spec §3 + §5 regenerated coherent with §9.4 | `docs/design/v2-shot-schema-spec.md` |
| **P3** | DB schema design (per-field provenance + changelog) | `docs/design/v2-db-schema.sql` (14 tables, 25 indexes, 3 views) |
| **P4** | Memory + heartbeat infrastructure + auto-init on analyze | `src/utils/analysis_memory.py`, wired in `media_analysis.py` |
| **P5** | Soul layer scaffolded | `~/Documents/davinci-resolve-mcp-analysis/_soul/` |
| **P6** | V2 vision prompt | `src/utils/media_analysis.py` `DEFAULT_VISION_ANALYSIS_PROMPT`, `VISION_SCHEMA_REFERENCE="...v2"` |
| **P9** | Compact analyze response (verbose: true for full) | `src/server.py` `_compact_manifest_for_response`, `_compact_clip_row_for_response`, `_compact_metadata_publish_for_response` |
| **P10** | commit_vision auto-publish silent-lie fix | `src/server.py` `_publish_clip_metadata_from_analysis` — row.success defaults False, top-level `success` reflects `auto_dry_run_flip`, `status` field added per row |
| **P11** | `source_trust` parameter (auto/filename/low/medium/high) | `src/utils/media_analysis.py` `_build_vision_prompt_with_source_trust`, wired into `build_host_chat_paths_payload` |
| **P12** | `resolve_control.open_control_panel` + status + close | `src/server.py` `_open_control_panel`, `_control_panel_status`, `_close_control_panel` (subprocess + pidfile) |
| **P13** | `resolve_output_root` nested-path bug | `src/utils/media_analysis.py` — skip slug append when base already terminates in slug |
| **P14** | `media_pool_item.open_in_viewer` action | `src/server.py` (verified empirically: `OpenPage("media") + SetSelectedClip` auto-loads source viewer) |
| **B4** | Extend `open_in_viewer` with mark_in/out + resolve_control.save_state/restore_state | `src/server.py` |
| **B6** | Chat ↔ panel state sharing via panel_state.json | `src/utils/analysis_memory.py` (`read_panel_state`, `write_panel_state`); `src/server.py` actions `get_panel_state`, `set_panel_state`, `session_start_context` |
| **C4** | Correction MCP tools (per-clip sidecar JSON) | `src/server.py` actions: `update_shot_field`, `update_clip_field`, `get_field_history`, `revert_field`, `list_corrections`. Writes to `{clip_dir}/corrections.json` with provenance + append-only changelog (mirrors V2 DB schema) |
| **B1** | Control panel design doc | `docs/design/v2-control-panel-design.md` — 6 implementable steps, informed by actual dashboard.py structure |
| **C2 v2.0** | Bin summary aggregator (smart aggregation; V2.1 will replace with vision-synthesized briefing) | `src/utils/analysis_memory.py` `regenerate_bin_summary_from_manifest` — aggregates primary_use, select_potential, style, energy_arc, top tags, top locations, top-N clips |
| **CORR-MERGE** | Read-merge corrections.json in commit_visual_analysis (V2 trust-but-fix-optionally contract) | `src/utils/media_analysis.py` `preserve_human_corrections`, wired into `commit_visual_analysis`. Test: `test_commit_visual_analysis_preserves_human_corrections` |
| **B2** | Bin grid + thumbnail serving | `src/analysis_dashboard.py` `list_analyzed_clips`, `get_clip_frame_path`, `/api/clips`, `/api/clips/<id>/frames/<n>`. UI: `<main id="panel-review">` bin view, `.review-grid`. |
| **B3 part 1** | Clip detail view | `src/analysis_dashboard.py` `get_analyzed_clip`, `get_analyzed_clip_shots`, `/api/clips/<id>`, `/api/clips/<id>/shots`. UI: clip view + shot strip. |
| **B3 part 2** | Shot detail view | `src/analysis_dashboard.py` `get_analyzed_clip_shot`, `/api/clips/<id>/shots/<index>`. UI: two-column V2-fields-by-group + frame grid. |
| **B4 wiring** | Open-in-Resolve bridge from panel | `src/analysis_dashboard.py` `_v2_open_clip_in_resolve`, `POST /api/resolve/open_clip`. Wired to shot-detail "Open in Resolve" button. |
| **B5** | Inline correction UI | `src/analysis_dashboard.py` `apply_clip_correction` (proxies to `_v2_update_field`), `POST /api/clips/<id>/corrections`. UI: per-field editors with save buttons; "human-edited" tag on edited fields. |
| **B6 wiring** | Chat ↔ panel state polling | 2-second polling in dashboard HTML for `GET /api/panel_state`; click events `POST /api/panel_state` with `__written_by__: control_panel` so the loop doesn't echo. |

### Pending (after the fourth push that landed corrections merge + Phase B UI)

- **Phase C remainder**:
  - **C1** — DB migration (SQLite as canonical source-of-truth); existing analysis.json + corrections.json sidecars get ingested into the V2 DB schema. Major refactor.
  - **C2 v2.1** — replace the aggregator (already shipping) with a true vision-synthesized briefing. Follows the same deferred-payload pattern as per-clip vision: server prepares evidence (all per-clip summaries + representative frames), host chat synthesizes the briefing paragraph, calls `commit_bin_summary`.
  - **C3** — text + visual embeddings, similarity search action.
  - **C5** — cross-clip vision pass (recurring people/places/props across the bin).
- **P7 / P8** are now subsumed: P7 = the Phase B UI work (shipped); P8 = the correction tools landed as part of C4.

---

## 2. Phase A — Stability + foundations

Order matters: P10 first (worst-of-the-bunch silent lie), then unblock workflow with P9, then data-correctness with P13, then ergonomics.

| Task | Priority | Blocks |
|---|---|---|
| P10 — Fix commit_vision auto-publish | 1 | Trust-by-default; user must manually publish |
| P9 — Compact analyze_clip response | 2 | File-shovel workaround on every call |
| P13 — Nested-path bug | 3 | Real disk-layout bug |
| P11 — source_trust parameter | 4 | Description quality for archival clips |
| P12 — open_control_panel MCP action | 5 | Phase B foundation |
| P7 — Control panel sidecar UX | 6 | Most of Phase B |
| P8 — Correction MCP tools | 7 | Phase B B5 (inline corrections) |

---

## 3. Phase B — Control panel as analysis review surface

The control panel becomes a **chat-first review surface** with thumbnails, drill-down, and a one-click bridge into Resolve via the `open_in_viewer` action (P14, already done).

| ID | Title | Effort | Depends on |
|---|---|---|---|
| **B1** | Architecture + chat-first layout decision | M | P12 |
| **B2** | Thumbnail rendering (bin grid, shot strip, frame grid) | M | B1 |
| **B3** | Shot review UX (full V2 fields, transcript, relationships) | M | B2 |
| **B4** | Open-in-Resolve bridge — extend P14 with timecode + mark in/out | S | P14 |
| **B5** | Inline correction UI per subjective field | M | B3, P8 |
| **B6** | Chat ↔ panel state sharing | M | B1-B5 |

---

## 4. Phase C — V2.1 follow-ups

Don't start until Phase A + B are stable.

| ID | Title | Notes |
|---|---|---|
| **C1** | DB migration (SQLite source-of-truth) | DDL ready at `docs/design/v2-db-schema.sql`; need ingest of existing analysis.json + read/write code paths refactor |
| **C2** | Bin summary synthesis via vision pass | Replace structured listing in `bin_summary.md` with synthesized colleague-style briefing paragraph |
| **C3** | Embeddings + similarity search | Text (nomic-embed-text) + visual (CLIP) per V2 DB schema; powers "find clips like this" |
| **C4** | Correction MCP tool expansion | Per-field update_shot_field / update_clip_field with provenance + changelog writes |
| **C5** | Cross-clip vision pass | Identify recurring people/places/props across bin; cheap because works on summaries not pixels |

---

## 5. Per-task detail

### P10 — Fix commit_vision auto-publish

**Why:** `commit_vision` returns `metadata_publish.success: true` but no `Description` / `Keywords` / `Comments` are actually written to the Resolve clip. The user has to manually call `publish_clip_metadata` afterward. The docs at `src/server.py` (look for the commit_vision tool description) explicitly say "Metadata writeback will run automatically when commit_vision finalizes." It's a silent lie.

**Investigate:**
- Find the `commit_vision` handler in `src/server.py` (search for `def.*commit_vision` or `action == "commit_vision"`)
- Trace where `metadata_publish` field is set in its return
- Find the call (or missing call) to `_publish_clip_metadata_from_analysis`
- Verify `publish_metadata=true, confirm=true` flags pass through

**Fix options:**
- Option A (preferred): wire `_publish_clip_metadata_from_analysis` to actually run when commit_vision finalizes vision. Honors the existing API contract.
- Option B: change the response to honest `{publish_pending: true, action_required: "call publish_clip_metadata"}`.

Pick A. It matches the documented behavior and is what the user reasonably expects.

**Also fix in the same edit:**
- `commit_vision` silently accepts `publish_metadata: true, confirm: true` — these flags should either be honored (Option A above) or rejected with a clear error message ("publish flags require explicit publish_clip_metadata call").

**Files:** `src/server.py` (search `commit_vision`)

**Acceptance:**
- After `commit_vision` with `publish_metadata: true, confirm: true`, `get_metadata(clip_id)` returns populated `Description` and `Keywords` without a subsequent `publish_clip_metadata` call
- Response field `metadata_publish.success` reflects actual write success
- Explicit flag rejection has a clear error message if Option B is chosen

**Risk:** Touching commit_vision is high-risk — it's the merge boundary between deferred vision and persisted analysis. Add a small test that runs commit_vision in a dry-run mode if possible.

---

### P9 — Compact analyze_clip response

**Why:** Tool result responses are 139-150k chars, far above the 25k token cap. Forces every consumer (chat or future control panel) to read from disk via jq. Inefficient and brittle.

**Design:**

Default response (no flag, ~5-10k chars):
```json
{
  "success": true,
  "status": "pending_host_vision_analysis",
  "vision_token": "...",
  "clip_dir": "...",
  "analysis_json": "...",
  "frame_count": 170,
  "frame_paths_summary": {
    "first": "/full/path/sampled_0001.jpg",
    "last": "/full/path/sampled_0170.jpg",
    "directory": "/full/path/frames/",
    "count": 170
  },
  "shot_count": 34,
  "manifest_summary": {
    "clip_id": "...", "clip_name": "...",
    "duration_seconds": 152.7, "fps": 29.97,
    "analysis_version": "0.2"
  }
}
```

Verbose response (`verbose: true`): current full payload.

**Files:** `src/server.py` (search analyze_clip handler), possibly `src/utils/media_analysis.py` if response is built there.

**Acceptance:**
- Default `analyze_clip` returns under 10k chars
- `verbose: true` returns the full manifest (current behavior)
- Compact response carries everything a consumer needs to call commit_vision without re-reading the analysis_json

---

### P13 — Nested-path bug

**Why:** Found a duplicate analysis tree at `~/Documents/davinci-resolve-mcp-analysis/20260517_sample-fc314309e4/20260517_sample-fc314309e4/...` with capabilities.json and partial `clips/`. `resolve_output_root` double-appends `project_dir` when called with an `analysis_root` that already ends in the project slug.

**Reproduction:**
- Call any analyze action with `params.analysis_root` set to a path that already ends in `{project_slug}` (e.g., a previous run's project_root passed as the new analysis_root)
- Observe new files written to `{old_project_root}/{project_slug}/...`

**Fix:** In `resolve_output_root` (`src/utils/media_analysis.py` ~line 341), before appending `project_dir`, check if `base_root` already ends with `project_dir` or is exactly the target output_root. If so, skip the append.

```python
project_dir = project_directory_name(project_name, project_id)
base_root = normalize_path(analysis_root) if analysis_root else normalize_path(Path.home() / "Documents" / ANALYSIS_DIR_NAME)

# Don't double-append if base_root already terminates in project_dir.
if os.path.basename(base_root.rstrip("/")) == project_dir:
    output_root = base_root
else:
    output_root = normalize_path(os.path.join(base_root, project_dir))
```

**Files:** `src/utils/media_analysis.py` (`resolve_output_root`)

**Acceptance:**
- Calling with `analysis_root="~/Documents/davinci-resolve-mcp-analysis/{slug}"` returns the same path, not `~/Documents/davinci-resolve-mcp-analysis/{slug}/{slug}`
- Existing callers (no `analysis_root` passed) get the same path they got before
- Add a unit test if there's a test harness for this module

**Cleanup:** Manually rm the duplicate tree at `~/Documents/davinci-resolve-mcp-analysis/20260517_sample-fc314309e4/20260517_sample-fc314309e4/` after the fix lands.

---

### P11 — source_trust / filename_trust parameter

**Why:** For archival / known-source clips (e.g., `CKY - Bam and The Rental Car.mp4`), vision currently must hedge identity claims even when the filename literally names the subject. Conservative-by-default is the right default but should be tunable when context is known.

**Design:** Add to analysis plan params:

```python
source_trust: "auto" | "filename" | "low" | "medium" | "high"
```

- `auto` (default): vision uses frame evidence only; ignores filename for identity claims
- `filename`: vision can cite the filename as supporting evidence; still hedge when frames don't corroborate
- `low/medium/high`: explicit trust level for ALL signals (filename, prior context, cultural recognition)

The V2 prompt (`DEFAULT_VISION_ANALYSIS_PROMPT`) gets a templated section that includes the trust level. The prompt builder injects guidance based on the level.

**Files:**
- `src/utils/media_analysis.py` — add `source_trust` to plan signature, wire into prompt builder
- The prompt itself needs a conditional section that's added when trust > auto

**Acceptance:**
- Default behavior unchanged (conservative)
- With `source_trust: "filename"` on the CKY clip, vision output identifies Bam Margera with appropriate confidence rather than "young man with shoulder-length dark hair"
- Per-field confidence still reflects actual evidence — high trust isn't a license to assert everything as `high` confidence

---

### P12 — open_control_panel MCP action

**Why:** Current SKILL.md tells users to launch the control panel via bash. Chat-first UX needs an MCP action.

**Design:** Add to `resolve_control` namespace:

```python
resolve_control(action="open_control_panel", params={
    "background": true,  # default
    "port": null  # null = auto-pick or use saved preference
}) -> {success, url, pid?, port}
```

**Files:** `src/server.py` (`resolve_control` tool function)

**Implementation notes:**
- Find how `src/analysis_dashboard.py` is currently launched (probably via `subprocess.Popen` of a python -m or similar)
- Wrap that in a single MCP action
- Track the PID in a temp file (e.g. `~/Documents/davinci-resolve-mcp-analysis/_control_panel.pid`) so subsequent calls can detect "already running" and return the URL instead of re-launching
- Return `{success, url: "http://localhost:PORT", pid, port}`

**Acceptance:**
- Calling `resolve_control(action="open_control_panel")` from chat starts the panel and returns a URL
- Calling again returns the existing URL/pid, doesn't double-launch
- An additional `close_control_panel` action or similar to terminate the process cleanly

---

### P7 / P8 — Control panel UX + correction MCP tools

These are large enough to be Phase B work. See §3 (B1-B6) below.

---

### B1 — Control panel architecture + chat-first layout

**Goal:** Decide the stack, lay out the panes, define how chat and panel share state.

**Investigate first:**
- What's already in `src/analysis_dashboard.py`? Read it. Streamlit? Flask? Custom?
- How does it currently render analysis data?
- Is there a state-sync mechanism with chat / MCP today?

**Layout (chat-first):**
```
+---------------------+--------------------+
| Chat                | Bin grid (clips)   |
| (full height)       | -- clip detail --  |
|                     | -- shot strip --   |
|                     | -- shot detail --  |
|                     | -- frame grid --   |
+---------------------+--------------------+
| Status / heartbeat / current project     |
+------------------------------------------+
```

Chat is the persistent left pane. Right pane shows whichever view the conversation needs — bin overview by default, drilling down as the user asks.

**State-sharing approach (recommendation):**
- Control panel is a separate process talking to the same MCP server Claude uses
- Both write/read from a small `panel_state.json` file under the analysis root (current_clip, current_shot, page_history)
- When the chat says "show me shot 22," it writes to panel_state.json; the panel polls or watches for changes
- When the user clicks in the panel, it writes to panel_state.json; the chat can read it on next turn

This avoids websockets / IPC complexity and uses files as the integration substrate (consistent with the rest of the architecture).

**Deliverable:** A design doc at `docs/design/v2-control-panel-design.md` covering: stack choice, pane layout, state-sharing mechanism, MCP integration points. Then B2-B6 implement against it.

**Files:** `docs/design/v2-control-panel-design.md` (new), `src/analysis_dashboard.py` (read for current state)

**Acceptance:** A coherent design doc that B2 can implement against without further architecture discussion.

---

### B2 — Thumbnail rendering

**Goal:** Make the V2 frame sampler's JPEGs visible in the panel.

**Three thumbnail views:**

1. **Bin grid** — one card per clip, thumbnail is the clip's middle shot's `representative_frame`. Grid view, clickable.

2. **Shot strip** — horizontal scrolling strip of all shots in a clip. Each shot's thumbnail is its `representative_frame`. Click a shot → opens shot detail.

3. **Frame grid** — all sampled frames for one shot, in a grid, labeled with `selection_reason` (`shot_start`, `shot_progress`, `shot_end`, `flash_candidate`, etc.). Hover shows time_seconds and any vision-described tags.

**Implementation notes:**
- Thumbnails are already at `{project_root}/clips/{slug}/frames/sampled_NNNN.jpg` — mount that directory in the panel's webserver
- For the bin grid's "clip thumbnail," use the middle shot's representative frame: `shot_table[len(shots)//2].frame_indices[0]`
- Lazy-load thumbnails as the user scrolls
- Cache in browser; flush on `analyzed_at` timestamp change

**Files:** Control panel code (TBD by B1 stack choice)

**Acceptance:**
- Bin grid renders all analyzed clips with representative thumbnails
- Shot strip renders all 34 CKY shots with representative thumbnails
- Frame grid for a shot renders all sampled frames with selection_reason labels

---

### B3 — Shot review UX

**Goal:** Full V2 schema review surface — the thing the user sits down to in the morning to review the bin.

**Per clip:**
- Header: clip_name, duration, fps, resolution, primary_use, energy_arc, style
- Description (`clip_summary`) and `clip_summary_oneliner`
- Search tags as chips
- Slate data if present
- Editorial classification
- Shot strip (B2)
- Transcript view with shot boundaries marked (clicking a shot in the strip jumps the transcript)
- Audio waveform (optional, post-V2.1)
- Cross-shot relationships visualized as arcs/links between shots

**Per shot (when one is selected from the strip):**
- All V2 fields organized by group: visual, content, production, editorial, cuttability, performance (if person), transition_in/out
- Frame grid (B2)
- Inline transcript excerpt (`transcript_overlap`)
- Cross-shot relationships: "same setup as: [shot 3, shot 7]", "continues from: [shot 22]"
- Per-group confidence shown as colored badges
- **"Open in Resolve at this timecode" button** — triggers B4

**Files:** Control panel UI

**Acceptance:**
- Reviewing the CKY clip's analysis in the panel feels like reading a colleague's notes
- Every V2 field is readable; high-cardinality fields (enums) are presented with friendly labels
- Confidence is visually surfaced (color or icon) so the user knows where to look closer
- The "Open in Resolve" button works (B4)

---

### B4 — Open-in-Resolve bridge (extending P14)

**Already done (P14):** `media_pool_item(action="open_in_viewer", params={clip_id, page})` selects the clip on Media page; source viewer auto-loads.

**Extensions for B4:**
1. **Pre-mark a shot's time range** before opening:
   - Optional params: `mark_in_seconds`, `mark_out_seconds`
   - Before calling `SetSelectedClip`, call `MediaPoolItem.SetMarkInOut(in_frame, out_frame, "all")`
   - Once the clip loads in source viewer, the editor sees the shot's region highlighted

2. **Save/restore Resolve state** for the "back to my work" experience:
   - New action `resolve_control.save_state()` → captures current page, timeline, timecode
   - New action `resolve_control.restore_state(state_token)` → returns to that state
   - The panel pairs these around an "Open in Resolve" click

**Files:**
- `src/server.py` — extend `open_in_viewer` to accept `mark_in_seconds` / `mark_out_seconds`; add `resolve_control.save_state` / `restore_state`

**Acceptance:**
- Clicking a shot's "Open in Resolve" button: clip loads in source viewer, mark in/out are set to the shot's start/end, editor can press space to play just that beat
- Clicking "back" returns Resolve to the editor's prior state

---

### B5 — Inline correction UI

**Goal:** Every subjective field in the shot detail pane is editable in place. Edits write to the DB with provenance + changelog.

**Per-field affordance:**
- Enums (shot_size, editorial_role, etc.) → dropdown
- Booleans → toggle
- Short strings (composition_notes, action) → inline text edit
- Long strings (description) → expanding textarea
- Confidence → small "low / medium / high" segmented control
- Each field shows a small "human-edited by sam@bradfordoperations.com on 2026-05-19" tag once edited
- Hovering the tag reveals the changelog (previous value, when, by whom, why)

**Backed by P8 (correction MCP tools):**
```python
media_analysis(action="update_shot_field", params={
    "shot_uuid": "...",
    "field_path": "visual.shot_size",
    "new_value": "medium_close",
    "author": "sam@bradfordoperations.com",
    "reason": "wider than it looked"
}) -> {success, changelog_entry_id}
```

The MCP action writes to the `subjective_fields` table (current value) and appends to `field_changelog` per the V2 DB schema.

**Files:** Control panel UI (B1 stack), `src/server.py` (`update_shot_field` / `update_clip_field` actions), backed by the DB (C1 or interim file-based).

**Acceptance:**
- Editing a shot's shot_size in the panel writes to the DB (or interim analysis.json + sidecar)
- The change persists across panel reloads
- The changelog shows the previous value and the timestamp
- Re-running analysis on this clip does NOT overwrite human-edited fields

---

### B6 — Chat ↔ panel state sharing

**Goal:** The panel and chat feel like a single tool. Things said in chat surface in the panel and vice versa.

**Through `panel_state.json` (B1 mechanism):**
- Chat says "show me shot 22" → writes `panel_state.json` with `{current_clip: <id>, current_shot: 22}` → panel updates view
- User clicks shot 14 in panel → writes to panel_state.json → next chat turn reads it and treats it as context ("user is now looking at shot 14, which is...")
- Chat says "preview that in Resolve" → reads current_shot from panel_state.json, calls B4's preview action
- "What did we just decide about shot 22's eye_line?" → chat reads corrections.md / decisions.md for context

**Files:**
- Control panel UI — write panel_state.json on user actions
- Chat-side: an MCP action `media_analysis.get_panel_state()` so any LLM can read the current panel context
- Auto-read panel state at session start as part of `session_start_context`

**Acceptance:**
- "Show me shot 22" in chat updates the panel's view
- "Open the current shot in Resolve" works without me re-saying which shot
- The panel feels like an extension of the conversation

---

### C1 — DB migration (SQLite source of truth)

**Goal:** Flip from analysis.json-as-canonical to DB-as-canonical. analysis.json becomes a derived export.

**Steps:**
1. Apply `docs/design/v2-db-schema.sql` to a new `analysis.sqlite` under each project's analysis root
2. Write an ingest script that walks existing `clips/{slug}/analysis.json` files and populates the DB (computed layers + subjective_fields with `source: "vision_v0.2", author: "system"`)
3. Refactor read paths in `media_analysis.py` to query the DB instead of reading analysis.json
4. Refactor write paths (commit_vision, etc.) to write through to the DB; export analysis.json as a side artifact
5. Old `index.sqlite` derived index can be removed once `analysis.sqlite` is canonical

**Files:** Lots. Major refactor.

**Acceptance:**
- `media_analysis(action="query_index", ...)` queries `analysis.sqlite` directly
- Per-field provenance + changelog work end-to-end
- Existing analysis.json files are still produced (as exports)
- No regression in analyze_clip / commit_vision

---

### C2 — Bin summary synthesis

**Goal:** `bin_summary.md` becomes a real synthesized briefing, not a structured listing.

**Implementation:**
- After analyze_project (or after vision commits for the last pending clip), call a separate vision pass that reads all per-clip `clip_summary` + `editorial_classification` and produces a synthesized paragraph: "This bin contains X clips of Y total runtime, primarily Z type of content. Recurring people: ... Recurring locations: ... Through-line: ..."
- Replace the structured listing in `analysis_memory.regenerate_bin_summary_from_manifest` with this synthesized output
- Keep the structured listing as a supplementary section

**Files:** `src/utils/analysis_memory.py`, possibly a new vision pass module

**Acceptance:** Reading `bin_summary.md` feels like a colleague's morning briefing, not a database listing.

---

### C3 — Embeddings + similarity search

**Goal:** "Find clips like this one" queries work in chat.

**Implementation:**
- Add embedding generation step after vision commit:
  - Text embeddings (nomic-embed-text via API or local) of: clip_summary, each shot.description, search_tags
  - Visual embeddings (CLIP via local model) of: each shot.representative_frame
- Store in V2 DB `embeddings` table
- Add `media_analysis(action="find_similar", params={entity_uuid, kind})` that does cosine similarity

**Files:** New `src/utils/embeddings.py`, wire into commit_vision, new MCP action

**Acceptance:** "Find clips visually similar to clip X's shot 12" returns a ranked list. "Find clips with similar editorial role" works on text embeddings.

---

### C4 — Correction MCP tool expansion (P8 done properly)

**Goal:** Full per-field update API backed by the V2 DB.

**Actions to add:**
- `update_shot_field(shot_uuid, field_path, new_value, author, reason?, confidence?)`
- `update_clip_field(clip_uuid, field_path, new_value, author, reason?, confidence?)`
- `get_field_history(entity_uuid, field_path)` → returns changelog entries
- `revert_field(entity_uuid, field_path, to_changelog_id?)` → restores a previous value (still creates a new changelog entry)
- `lock_field(entity_uuid, field_path, locked_by)` / `unlock_field` — optional; for multi-user

**Files:** `src/server.py` actions, backed by the DB.

**Acceptance:** B5's inline correction UI calls these actions. Changelog is queryable.

---

### C5 — Cross-clip vision pass

**Goal:** Identify recurring people / places / props across the bin so the machine can reason about coverage holistically.

**Implementation:**
- After all clips analyzed: a vision pass that reads bin-level summaries + a representative frame from each clip
- Identifies: same person across clips, same location across clips, alt-take groupings across clips
- Writes results into `shot_relationships` table with cross-clip references
- Optionally produces a "recurring entities" section in `bin_summary.md`

**Acceptance:** "Find every clip Bam appears in" works by querying cross-clip relationships, not by re-running per-clip vision.

---

## 6. Cross-cutting concerns

### Schema evolution

V2.0 schema is locked per `v2-shot-schema-spec.md` §9. When V2.1 adds fields (e.g., higher-res sampling enables better `depth_of_field` inference), the protocol is:

1. Add the field to the spec with `Decided in §9.x V2.1` annotation
2. Update the vision prompt with the new field
3. Bump `VISION_SCHEMA_REFERENCE` (e.g., `...v2.1`)
4. Bump `schema_version` in source provenance (`vision_v0.3` etc.)
5. Migration: existing records auto-fill new fields as `null`; vision repopulates on re-run

### Test methodology

For each task, validate against the CKY rental-car clip end-to-end:
- `analyze_clip(selected=true)` → `commit_vision` → re-read analysis.json + heartbeat + bin_summary
- Confirm Resolve clip metadata matches what was committed
- Confirm no Resolve markers were written (V2 architecture)
- Confirm `_soul/` and `memory/` got initialized / updated

### Docs to update

- `docs/SKILL.md` — V2 operating guidance; add `open_in_viewer` and other new actions
- `docs/reference/api-coverage.md` — new MCP actions list
- `AGENTS.md` — note V2 architecture decisions if relevant
- This gameplan — keep status section current as tasks complete

### Commit hygiene

- Per memory `feedback-no-coauthor`: never add Co-Authored-By Claude lines to commits
- Per memory `feedback-version-tagging`: version bumps require a git tag + GitHub release
- Bundle related fixes (e.g. P10 + P9 in one commit if they touch the same code path)
- Each Phase A task is probably one commit; each Phase B / C task is probably multiple

---

## 7. Session restart protocol

Between Phase A and Phase B (and ideally between each task that touches MCP server code), restart Claude Code so the MCP server picks up code changes. Test the change in a fresh session before moving on.

The frame-sampling fix (P0) and the V2 vision prompt (P6) are already live as of 2026-05-19. The `open_in_viewer` action (P14) is in code but requires a restart to be callable.

---

*End of gameplan. Edit inline as the plan evolves; treat status table in §1 as ground truth.*
