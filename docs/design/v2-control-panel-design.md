# V2 Control Panel — Design

**Purpose:** Concrete design for extending `src/analysis_dashboard.py` into a V2 analysis review surface with thumbnails, shot detail, inline corrections, and chat ↔ panel state sharing.

**Companion docs:**
- `docs/design/v2-shot-schema-spec.md` — the V2 schema being reviewed
- `docs/design/v2-implementation-gameplan.md` — the broader task list (B1-B6, C1-C5)
- `docs/design/v2-db-schema.sql` — the eventual source-of-truth backing store

**Last updated:** 2026-05-19

---

## 1. Current state

The existing dashboard (`src/analysis_dashboard.py`, ~5000 lines):

- **Single-page HTML app** — embedded `HTML` string at the top of the file, served at `GET /`. CSS is inline (Bradford Operations design tokens defined in `:root`).
- **Stack:** native Python `http.server.ThreadingHTTPServer` + `BaseHTTPRequestHandler` (`Handler` class). No framework.
- **State:** `DashboardState` class holds project name/id/root; reads project contexts; lists projects across the analysis base root.
- **API routes** (under `/api/`):
  - `GET /api/boot` — initial state + capabilities
  - `GET /api/projects`, `GET /api/projects/all` — project listings
  - `GET /api/resolve/media` — media inventory from Resolve
  - `GET /api/jobs`, `POST /api/jobs`, `GET /api/jobs/<id>` — batch job management
  - `GET /api/index/status`, `GET /api/index/query` — SQLite index queries
  - `GET /api/docs` — doc viewer
  - `GET /api/setup/schema`, `GET /api/setup/defaults` — setup defaults
- **Launch:** `python -m src.analysis_dashboard` with `--host`, `--port`, `--project-name`, `--project-id`, `--analysis-root`, `--open`. Also launchable via P12's `resolve_control(open_control_panel)` MCP action.

**What it does NOT have yet (V2 gaps):**
- No thumbnail rendering (does not serve `frames/sampled_NNNN.jpg`)
- No per-clip analysis review (clip_summary, editorial_classification visible)
- No per-shot detail view (V2 schema fields invisible)
- No inline correction UI (cannot edit subjective fields)
- No chat-panel state sharing (cannot react to chat saying "show shot 22")
- No "Open in Resolve" affordance per clip / shot
- No bin-grid representative thumbnails

---

## 2. Design principles

1. **Stay with the existing stack.** No framework migration. Native http.server is fine for single-user local; if multi-user lands (C1 + cloud), revisit.
2. **Chat-first UX** ([[feedback-conversational-ux]]) — the dashboard's primary value is *review with thumbnails*. Reading prose / asking questions / making cuts happens in chat. Panels are summoned by the conversation.
3. **State-sharing via files**, not websockets. `panel_state.json` (already implemented in B6) is the substrate. Panel polls every ~2s; chat updates it via MCP actions. Lossy but simple and consistent with the rest of the architecture (heartbeat.json, corrections.json).
4. **One additional view per release**. Don't ship a half-baked everything-view; ship one view at a time and validate.

---

## 3. Architecture additions

### 3.1 New API endpoints

| Endpoint | Returns |
|---|---|
| `GET /api/clips` | List of analyzed clips with `{clip_id, clip_name, duration, analyzed_at, representative_frame_path}` for the bin grid |
| `GET /api/clips/<clip_id>` | Full V2 analysis for one clip (clip_summary, classification, shots[], cross_shot, qc) |
| `GET /api/clips/<clip_id>/shots` | Just the shots array (lighter than the full clip endpoint) |
| `GET /api/clips/<clip_id>/shots/<shot_index>` | Single shot's V2 fields + frame_indices |
| `GET /api/clips/<clip_id>/frames/<frame_index>` | Serves the actual JPEG file from `{clip_dir}/frames/sampled_NNNN.jpg` |
| `GET /api/clips/<clip_id>/corrections` | Read corrections.json for a clip |
| `POST /api/clips/<clip_id>/corrections` | Apply a correction (proxies to `media_analysis(update_shot_field)` or `update_clip_field` via direct function call) |
| `GET /api/panel_state` | Read panel_state.json |
| `POST /api/panel_state` | Update panel_state.json (merge by default) |
| `POST /api/resolve/open_clip` | Proxy to `media_pool_item(open_in_viewer)` so the UI can show "Open in Resolve" buttons |

All read endpoints read from disk (analysis.json + corrections.json sidecar) — no DB dependency. When C1 lands, swap to DB queries; UI doesn't change.

### 3.2 New view: bin grid (B2 — first deliverable)

```
+----------------------------------------+
| Project: 20260517_Sample               |
| 47 clips · ~3h2m · last analyzed 9am   |
+--+--+--+--+--+--+--+--+--+
|🎬|🎬|🎬|🎬|🎬|🎬|🎬|🎬|🎬|  ← thumbnail cards
+--+--+--+--+--+--+--+--+--+
| CKY - Bam     2:32  ⭐    |
| select potential: high     |
+---------------------------+
```

Each card:
- Thumbnail = clip's middle shot's `representative_frame`
- Name, duration
- `select_potential` indicator (color or icon)
- Click → opens clip detail view (B3)

### 3.3 New view: clip detail (B3 — second deliverable)

```
+--------------------------------------+
| ← Back        CKY - Bam and Rental Car
+--------------------------------------+
| clip_summary paragraph here...       |
| Tags: cky, bam, stunt, ...           |
+--------------------------------------+
| Shot strip (horizontal scroll):       |
| [s1][s2][s3]...[s34] thumbnails       |
+--------------------------------------+
| Cross-shot: coverage groups visualized
| Continuity chains drawn as arcs       |
+--------------------------------------+
```

Click a shot in the strip → opens shot detail (B3 cont.)

### 3.4 New view: shot detail (B3 — third deliverable)

Two-column layout:

**Left column — V2 fields:**
- Visual: shot_size, framing, camera_height, camera_motion, lens, lighting, color_mood
- Content: primary_subject (with performance if person), action, location, audio_character
- Editorial: editorial_role, select_potential, pacing, best_moment
- Cuttability: cut_in, cut_out, match_action_in/out
- Relationships: same_setup_as, continues_from, alt_take_of (with links to other shots)
- Confidence badges per group

**Right column — frame grid:**
- All sampled frames for the shot
- Labels: shot_start / shot_progress / shot_end / flash_candidate / motion_peak
- Click frame → enlarged preview with time + delta_from_previous

**Header actions:**
- "Open in Resolve at this timecode" → triggers `media_pool_item(open_in_viewer)` with `mark_in_seconds`, `mark_out_seconds`
- "Edit" → flips fields to inline editing mode (B5)

### 3.5 Inline correction UI (B5 — fourth deliverable)

When the user clicks "Edit" on a shot detail:
- Enum fields → dropdowns
- Strings → inline text input
- Booleans → toggles
- "Save" button per field group; "Cancel" reverts
- Saved changes call `POST /api/clips/<clip_id>/corrections` which writes to `corrections.json` via the C4 helpers
- After save, the field shows a small "human-edited by sam on May 19" tag; hover reveals changelog

### 3.6 Chat ↔ panel state sync (B6 — DONE, wire up here)

The panel polls `GET /api/panel_state` every 2 seconds. When the chat (via MCP) writes to `panel_state.json` with `{current_clip_id, current_shot_index, current_view}`, the panel updates its view on the next poll.

Conversely, when the user clicks something in the panel, the panel writes back to `panel_state.json` via `POST /api/panel_state`. Chat reads it at the start of its next turn via `media_analysis(action="session_start_context")` (which already includes `panel_state`).

---

## 4. Implementation order (each step shippable on its own)

| Step | Adds | Validation |
|---|---|---|
| **Step 1** | `GET /api/clips`, `GET /api/clips/<id>/frames/<n>` endpoints + bin grid view (B2) | Open dashboard → see clips with thumbnails |
| **Step 2** | `GET /api/clips/<id>`, `GET /api/clips/<id>/shots/<n>` + clip detail view (B3 part 1) | Click a clip → see summary + shot strip |
| **Step 3** | Shot detail view (B3 part 2) | Click a shot → see all V2 fields + frame grid |
| **Step 4** | "Open in Resolve at this timecode" button wiring (B4 already done server-side) | Click → clip loads in source viewer with marks |
| **Step 5** | Inline correction UI (B5) + `POST /api/clips/<id>/corrections` | Edit a field → corrections.json updates → reload reflects change |
| **Step 6** | Chat ↔ panel state polling (B6 server-side done) — add 2s polling in HTML | Chat says "show shot 22" → panel scrolls to shot 22 |

Each step is 1-2 sessions of focused work. Steps 1-3 are mostly mechanical (read JSON, render HTML). Step 4 is small. Step 5 is the most involved (inline editing UX + provenance display). Step 6 is small.

---

## 5. Not in scope for V2.0

- Audio waveform rendering in shot detail
- Embedding-based similarity search visualization (depends on C3)
- Cross-clip / project-level views beyond the bin grid (depends on C5)
- Real-time multi-user collaboration (depends on C1 + cloud)
- Authoring tools (timeline drafts, EDL export from chat suggestions)

Defer to V2.1+ unless a specific use case bubbles up.

---

## 6. Open design questions

1. **Thumbnail cache.** Do we serve JPEGs directly from `{clip_dir}/frames/` or pre-resize for grid views? Likely: direct serve for V2.0, resize later if performance demands.
2. **Pagination on the bin grid.** Above what clip count do we paginate vs. infinite-scroll? Probably > 100 clips.
3. **Cross-shot relationships rendering.** Arcs between shots in the strip? Connection lines? Group highlights? Needs a UX iteration once data is real.
4. **Confidence visualization.** Color (red/yellow/green)? Icon? Faded text? Test with real users.

---

*End of design. Step 1 (bin grid + thumbnail serving) is the smallest demoable slice — recommend starting there.*
