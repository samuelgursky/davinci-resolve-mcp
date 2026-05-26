# Control Panel Polish — Gameplan

Tracks the round of UI/UX work that started 2026-05-19 after removing Batch
Jobs / Job Detail from the Analysis menu. The work is sequenced so that the
visual-design system from Phase 1 gets reused by every later phase, and so that
schema/server changes land before the UI that consumes them.

Source-of-truth: the user. This doc is a living checklist — strike items as
they ship, append new ones surfaced during execution.

---

## Findings worth knowing before we start

- **`analysis_summary_style` and `report_format` are dead code today.** Both
  prefs are validated and threaded through the request envelope
  (`src/server.py:5695,5696,7364-7369,8709-8710`), but nothing in
  `src/utils/media_analysis.py` or anywhere downstream branches on them. We can
  rename the enum values without breaking behavior because there is no behavior
  to break. The cost: renaming alone won't make summaries *act* different;
  that's follow-up work.

- **Two transcription settings exist and they don't sync.**
  `Preferences › Analysis › Transcription default` (`prefTranscriptionDefault`,
  server-wide, default `"yes"` at `src/server.py:5676`) is the real default.
  `Preferences › Dashboard Convenience › Transcription` (`prefTranscription`,
  browser-local checkbox, default off) was the per-run override for the
  now-deleted batch composer. The browser-local one no longer has a UI
  consumer; it only feeds the generated MCP prompt in `promptPayload()`
  (`src/analysis_dashboard.py`).

- **`timed_markers_default` defaults to `"yes"`** (`src/server.py:5673`). The
  dropdown showing "yes" is not a UI bug — it reflects the actual server
  default. The user has asked to flip this to `"ask"`.

- **Resolve product/version are not in the boot payload.** `/api/boot` returns
  capabilities, project info, output roots, but does not call
  `GetProductName() / GetVersionString() / GetCurrentPage()` on the Resolve
  handle. `_connect_resolve_read_only()` already returns the handle — easy to
  extend.

- **Package version source** is `package.json:3` (`"2.23.1"`).
  `src/utils/update_check.py` already has `check_for_updates()` and writes to
  `update_state.json`. The plumbing exists; the dashboard just doesn't surface
  it yet.

- **Browser file-system picker reality check.** `showDirectoryPicker()` exists
  but is Chromium-only and requires HTTPS or `localhost`. The dashboard runs on
  `localhost` so it's usable, but we need a graceful fallback for
  Firefox/Safari users — keep the text input as source of truth.

---

## Phases

### Phase 0 — Server-side flips (small, foundational)

These are tiny but they unblock Phase 1's data and Phase 3's correctness.

- [ ] **Flip `timed_markers_default` to `"ask"`** in
      `_MEDIA_ANALYSIS_DEFAULT_PREFS` (`src/server.py:5673`). Existing
      user-saved prefs are untouched; this only affects fresh installs and
      `Reset Defaults`. Validate by running the dashboard, hitting Reset, and
      confirming the dropdown lands on "ask".
- [ ] **Add Resolve identity to `/api/boot`.** Extend the boot route in
      `src/analysis_dashboard.py` to call `GetProductName()`,
      `GetVersionString()`, `GetCurrentPage()` against the read-only Resolve
      handle (use `_connect_resolve_read_only`). Add a `resolve` block to the
      response. Null-tolerant when Resolve is offline.
- [ ] **Add `/api/update/status` route.** Wraps
      `src/utils/update_check.py:check_for_updates` and exposes
      `{ current, latest, update_available, last_checked, snoozed_until }`.
      Cache result for at least 5 minutes; never block the dashboard on
      network.

**Exit criteria:** Boot payload includes `resolve.product`,
`resolve.version_string`, `resolve.page`. `/api/update/status` returns a
sensible payload offline (no exceptions). Fresh server prefs file shows
`timed_markers_default: ask`.

---

### Phase 1 — Status-pill design system + Diagnostics restyle

This is the foundation for every later visual change. We build the components
once on Diagnostics, then reuse them in Overview rows and (later) the Analyze
header.

- [ ] **Define status-pill primitives.** Three classes:
      `pill-ok` (green, var(--accent-success)), `pill-warn` (amber,
      var(--accent-warning)), `pill-err` (red, var(--accent-error)). A
      `pill-icon` slot for an inline 12px SVG.
- [ ] **Define `diagnostic-card`.** Compact card with: header (icon + title
      + status pill), 2–4 KV rows beneath, optional bottom action row. Reuses
      the existing `--lab-panel-bg` / `--lab-panel-elevated` tokens.
- [ ] **Restyle Resolve diagnostics.** Replace the single `info-list` with a
      grid of cards:
      - **Connection** card: status pill + product name + version + page
      - **Project** card: name + clip counts + warnings
      - **Inventory** card: total / source / hidden / sequences
- [ ] **Restyle Storage diagnostics** as cards (Analysis root / Index DB /
      Jobs DB) with pills for "indexed / stale / missing".
- [ ] **Restyle Tools diagnostics** so each detected tool is a chip with a
      version line and a status pill — denser than today's `tool-row` layout.

**Exit criteria:** Diagnostics page scans at a glance. Color encodes
correctness; the eye can find a problem without reading every label.

---

### Phase 2 — Overview rows visual upgrade

Reuses Phase 1 primitives. No new components needed.

- [ ] Convert the four overview metric cards to use the diagnostic-card
      shell (consistent visual language).
- [ ] Replace the flat `info-list` below the cards with a status-pill
      grid: every row gets a leading icon and a pill that reflects health
      (e.g. *Search index: indexed* in green, *Clip media status: 3 missing*
      in amber).
- [ ] Add a tiny meter for "X analyzed of Y source clips" so progress is
      visible without math.

**Exit criteria:** Overview communicates state without requiring the user to
read every word. Green/amber/red dominates the scan path.

---

### Phase 3 — Untangle Preferences (the big consolidation)

Touches Analysis, Dashboard Convenience, Storage, and Paths & Workflow.

- [ ] **Delete `Preferences › Dashboard Convenience` as a separate page.**
      Keep only the fields that still feed live UI:
      - `prefPollInterval` and `prefAutoPoll` → move to the Analyze page
        header as inline controls.
      - `prefDepth`, `prefFrames` → optional; consider moving to Analysis prefs
        as "Default depth" / "Default sample frames" since they feed the
        prompt and arguably *are* analysis defaults.
      - `prefJobName`, `prefRecursive`, `prefTranscription` → delete. Job
        name can default to "Editorial analysis pass" without a pref.
        Recursive is no longer surfaced. Transcription is owned by
        Preferences › Analysis.
- [ ] **Merge `Preferences › Storage` into `Preferences › Paths & Workflow`.**
      The Storage page becomes a "Where files live" section at the bottom of
      Paths & Workflow, rendered as diagnostic cards (reuses Phase 1).
- [ ] **Add a "Browse..." button** next to `prefPreferredAnalysisRoot` and
      `prefPreferredGeneratedMediaFolder`. Uses `showDirectoryPicker()` when
      available; falls back to plain text input. Show a dropdown of recently
      used project roots sourced from `state.projects.related_project_roots`.
- [ ] **Rename summary-style enum**: `concise / assistant_editor / qc /
      producer / full` → `full / concise / creative / technical`. Update:
      - `_MEDIA_ANALYSIS_DEFAULT_PREFS` (`src/server.py:5695`)
      - normalizer at `src/server.py:5923`
      - schema enum at `src/server.py:8709`
      - error message at `src/server.py:8917`
      - dashboard `<select>` options (`src/analysis_dashboard.py:2408`)
      - dashboard help text (`src/analysis_dashboard.py:2788`)
      - default value: `"concise"` is fine to keep.
- [ ] **Discuss/add new Analysis prefs.** Open questions for the user:
      - Default source-trust mode (the conservative-descriptions feature
        flagged in `feedback_conservative_descriptions.md`). Worth a UI
        toggle?
      - Default analysis depth (would replace the Dashboard-Convenience
        depth).
      - Default sample frame budget (same).

**Exit criteria:** One Transcription setting, in one place. Paths & Workflow
shows where files live. Storage page is gone from the menu. Dashboard
Convenience is gone from the menu. Summary-style dropdown reads
`full / concise / creative / technical`.

**Follow-up (not blocking this phase):** wire the renamed summary styles into
actual prompt construction so they produce distinguishable output. Today they
are stored and forgotten; renaming alone changes nothing downstream.

---

### Phase 4 — Navbar version badge + update flow

- [ ] **Read `package.json` at server start**, expose `version` on the
      `/api/boot` payload.
- [ ] **Render version as a navbar badge** next to the wordmark. Style: pill
      with `--accent-brand-muted` background; chevron when an update is
      available.
- [ ] **Poll `/api/update/status` on dashboard boot** and at most once per
      hour after that. Render a small "Update available → 2.24.0" decoration
      on the badge when applicable.
- [ ] **Click on the badge opens a brand-styled modal** (clone of
      `projectSwitchModal` at `src/analysis_dashboard.py:2556`). Modal shows
      current → next version, release notes link (if available), and
      Cancel / Update buttons. **Defer** the actual `pip install -U` /
      `npm install -g` kickoff — for v1, the modal can offer a "Copy update
      command" button. Self-updating a running server is a footgun; we'll
      design that separately.

**Exit criteria:** Users see the current version at all times, get a clear
indicator when a release is available, and have a one-click path to learn
how to update.

---

### Phase 5 — Polish pass

Stuff we'll likely find as we work through the above.

- [ ] Audit `setText('promptSourceSummary'/'promptSelectedSummary'/...)` no-op
      calls left over from the Batch Jobs removal. Either re-attach them to a
      surface on the Analyze page or delete them.
- [ ] Verify the post-Batch-Jobs `promptPayload()` still works end-to-end
      after Dashboard Convenience moves. Run the Analyze page's
      "Copy Prompt" / "Analyze in Codex" once and confirm the generated
      prompt is well-formed.
- [ ] Add a small status-pill legend somewhere on Diagnostics so the
      green/amber/red language is discoverable.

---

## Out of scope (intentionally)

- Wiring the renamed summary styles into actual prompt construction
  (separate engineering task — needs prompt-engineering work, not UI work).
- Self-updating the running MCP server from the dashboard
  (separate safety design).
- Touching the V2 Review surface — already shipped in the fourth push.
- Any change to the Analyze page's clip table — out of scope for this round.

## Open questions

1. **Source-trust default as a pref?** You flagged conservative descriptions
   in `feedback_conservative_descriptions.md` and it's now a `source_trust`
   param. Should this surface as a UI default in Preferences › Analysis?
2. **Depth and Sample Frames — move them or delete them?** They feed the
   generated MCP prompt but the user can also pass them per-call in chat.
   Are these worth keeping as UI prefs?
3. **Brand styling for the update modal.** We have one modal pattern
   (`projectSwitchModal`). Do you want a distinct visual treatment for
   update prompts, or keep them visually consistent with project switching?
