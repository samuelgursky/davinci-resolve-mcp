# V2 Per-Shot Analysis Schema — Working Spec

**Status:** Draft, iterating
**Authors:** Sam + Claude (drafted 2026-05-18)
**Purpose:** Define the shape of clip + per-shot analysis output that's optimized for LLMs (Claude, future models, third-party AI tools) to *create edits from*, not just describe footage.

This is a working document. Edit inline as we iterate. Once locked, it becomes the single target for the analysis pipeline rewrite (frame sampling, vision prompt, DB schema, commit flow). See also `~/.claude/projects/-Users-samuelgursky-davinci-resolve-mcp/memory/project_v2_architecture.md` for the surrounding architecture (DB-as-truth, dropped Resolve markers, four-layer brain).

---

## 1. Design principles

1. **Optimized for editorial assembly, not just description.** Every field should serve a question an editor or assembly LLM might ask: *"what could open this scene?" / "find clips that cut well to this one" / "what's the energy here?" / "where's the coverage gap?"*
2. **Conservative-by-default.** Trust-by-default means downstream consumers treat output as ground truth. Hedge identity, intent, and value claims when frame evidence is thin. Per-field confidence makes uncertainty machine-readable.
3. **Model-comparable.** Use closed enums where possible so different LLMs (Claude, GPT, Gemini, future models) produce comparable output. Open text fields are last resort.
4. **Provenance per subjective field.** Computed fields re-derive cleanly; subjective fields carry `{value, source, author, timestamp}` plus an append-only changelog so corrections survive re-runs.
5. **Composable, not monolithic.** Layers (technical / motion / audio / vision / cross-shot) are independently re-runnable so a model improvement on one layer doesn't invalidate the others.
6. **Vocabulary borrowed from film tradition.** Shot sizes, framing, camera motion use standard terms (wide/medium/close, single/two-shot/group, locked/pan/dolly) so editors recognize what's being said and existing editorial corpora (scripts, breakdowns, dailies notes) translate cleanly.

---

## 2. Top-level structure

```yaml
clip:
  id: uuid
  name: string
  source_file: path
  duration_seconds: float
  fps: float
  resolution: string

  technical: {...}                # computed, no provenance
  audio: {...}                    # computed
  transcript: {...}               # computed (whisper)
  motion: {...}                   # computed
  cuts: {...}                     # computed (ffmpeg + adaptive threshold)

  shots: [shot, ...]              # one per detected shot — see §3

  clip_summary: {...}             # vision, subjective, provenance
  editorial_classification: {...} # vision, subjective, provenance
  cross_shot: {...}               # vision (second pass) — coverage, continuity

  analysis_keyframes: [...]       # sparse notable moments outside shot regions
  qc: {...}                       # warnings, technical issues, coverage gaps

  analysis_metadata:
    schema_version: "2.0"
    analyzed_at: iso8601
    layers:
      technical: {version, run_at, signature_hash}
      audio: {...}
      transcript: {...}
      motion: {...}
      cuts: {...}
      vision: {version, run_at, model, prompt_hash, frames_used_count}
      cross_shot: {...}
```

---

## 3. Per-shot schema — the core of V2

All §9 decisions applied. This is the authoritative per-shot field list.

### 3.1 Computed fields (no provenance — re-derive on rerun)

| Field | Type | Description |
|---|---|---|
| `shot_index` | int (1-based) | Position in shot list |
| `shot_uuid` | string (content hash) | Stable ID surviving boundary jitter — hash of (rounded time region, representative frame phash) |
| `time_range` | `{start, end, duration}` (float seconds) | Time in source |
| `frame_range` | `{start, end}` (int) | Frame numbers (1-based at fps) |
| `representative_frame` | `{frame_index, path, time_seconds}` | Mandatory mid-shot frame |
| `additional_frames` | `[{frame_index, path, time_seconds, role}]` | Extra samples; `role` ∈ {shot_start, shot_end, shot_progress, motion_peak, dialogue_onset, dialogue_offset, flash_candidate} |
| `transcript_overlap` | `{text, segments: [{start, end, text, speaker_id?, confidence}]}` | Transcript intersection with this shot. `speaker_id` from Whisper diarization. |
| `motion_during_shot` | `{intensity: low\|medium\|high, peaks: [{time, intensity}]}` | Computed from motion analysis |
| `audio_character_computed` | enum (see §3.3) | First-pass computed; vision may override |
| `silence_during_shot` | `[{start, end}]` | Silence regions intersecting shot |

### 3.2 Vision-described — visual structure (subjective, provenance + confidence)

Each field carries `{value, source: "vision_v0.2"|"human", author, timestamp}`. Group-level confidence in §3.8.

| Field | Enum | Description |
|---|---|---|
| `shot_size` | wide \| medium_wide \| medium \| medium_close \| close \| extreme_close \| insert \| establishing \| other | How much of subject is in frame |
| `framing` | single \| two_shot \| group \| crowd \| empty \| insert \| establishing \| abstract | Compositional structure |
| `camera_height` | eye_level \| high_angle \| low_angle \| birds_eye \| dutch \| unknown | Camera relative to subject |
| `camera_motion` | locked \| pan \| tilt \| dolly \| handheld \| crane \| drone \| zoom \| composite \| other | Primary camera move |
| `motion_direction` | left \| right \| up \| down \| in \| out \| clockwise \| counter_clockwise \| none | Direction of dominant motion |
| `depth_of_field` | deep \| shallow \| rack_focus \| unknown | Focus characteristic |
| `lens_character` | wide \| normal \| tele \| fisheye \| unknown | Focal length feel |
| `lens_format` | spherical \| anamorphic \| fisheye \| unknown | Lens format / aperture style |
| `lighting` | natural \| high_key \| low_key \| practical \| backlit \| silhouette \| mixed \| unknown | Light quality |
| `color_mood` | warm \| cool \| neutral \| desaturated \| saturated \| monochrome \| unnatural \| unknown | Color palette character |
| `composition_notes` | string (short) | Free-text composition observations |

### 3.3 Vision-described — content

| Field | Type | Description |
|---|---|---|
| `primary_subject` | `{type, description, performance?}` — type ∈ person\|object\|landscape\|interior\|vehicle\|animal\|text_graphic\|abstract | What the shot is *of* |
| `primary_subject.performance` | `{eye_line, energy, emotional_register} \| null` | Populated only when `primary_subject.type == person`. Eye_line ∈ to_camera\|off_left\|off_right\|down\|up\|closed\|unknown. Energy ∈ low\|medium\|high. Emotional_register is freeform short string (NOT enum — avoids forcing categorical claims on ambiguous content). |
| `secondary_subjects` | `[{type, description}]` | Other notable elements |
| `action` | string (1 sentence) | What's happening |
| `location` | string (1 sentence) | Where this is |
| `visible_text` | `[string]` | Readable text on screen |
| `objects_of_note` | `[string]` | Notable props/elements |
| `audio_character` | silence \| sync_dialogue \| vo_dialogue \| music \| ambient \| sfx \| mixed \| unknown | Vision-confirmed (may override computed) |

### 3.4 Vision-described — production / composite

| Field | Type | Description |
|---|---|---|
| `composite_shot` | bool | True for split-screens, picture-in-picture, multi-angle composites |
| `composite_panels` | `[{region, primary_subject, action}] \| null` | When composite_shot is true: describe each panel separately. Null otherwise. |
| `vfx_present` | none \| minor \| major \| unknown | VFX involvement in this shot |

### 3.5 Vision-described — editorial

| Field | Type / enum | Description |
|---|---|---|
| `editorial_role` | establishing \| coverage \| reaction \| insert \| transition \| b_roll \| montage_element \| titles_or_graphics \| bumper \| other | What this shot is *for* editorially |
| `select_potential` | low \| medium \| high | Likelihood an editor will use this shot |
| `best_moment` | `{time_seconds, why} \| null` | Notable peak within the shot. Null if the shot is a sustained flat beat — see §9.4 §8.8 Q41 |
| `best_moment_present` | bool | Companion flag for quick filtering ("shots with notable moments") |
| `pacing` | still \| moderate \| kinetic \| variable | Energy character through the shot |
| `stillness_type` | held_tension \| quiet \| contemplative \| transitional \| dead_air \| unknown \| null | Used when `pacing` is still or variable; null otherwise |
| `pacing_note` | string \| null | Freeform nuance when `pacing` is still or variable |

### 3.6 Vision-described — cuttability

| Field | Type | Description |
|---|---|---|
| `cut_in` | `{quality: poor\|ok\|clean, notes: string}` | How well does the start of this shot receive an incoming cut |
| `cut_out` | `{quality: poor\|ok\|clean, notes: string}` | How well does the end of this shot lead into an outgoing cut |
| `match_action_in` | bool | Could be the receive side of a match cut |
| `match_action_out` | bool | Could be the send side of a match cut |
| `cut_compatibility_hints` | string | Free-text — "cuts well to interiors", "needs handle on either side", etc. |

### 3.7 Vision-described — transitions

| Field | Type | Description |
|---|---|---|
| `transition_in` | `{type, duration_seconds} \| null` | Type ∈ cut\|fade\|dissolve\|wipe\|unknown. Default `{type: cut, duration_seconds: 0}` |
| `transition_out` | `{type, duration_seconds} \| null` | Same enum. Boundary attribute, not a separate "transition shot" entity |

### 3.8 Vision-described — description & confidence

| Field | Type | Description |
|---|---|---|
| `description` | string (1-3 sentences) | Natural-language summary, editorially useful, colleague-style note |
| `qc_flags` | `[string]` | Per-shot QC flags (e.g. `no_in_shot_frame_sampled`) |
| `confidence` | `{visual, content, audio, editorial, cuttability}` | Each ∈ low\|medium\|high. Group-level granularity keeps annotation cost manageable while surfacing which dimensions are reliable. |

---

## 4. Cross-shot fields (second vision pass)

After all shots are individually analyzed, a second vision pass works on shot descriptions + representative frames (not the full frame samples — cheaper than per-shot analysis) and fills **pattern recognition** results only. No editorial suggestions (cut pairings, recommended sequences) are stored — those are runtime chat queries against the analysis, not schema fields. *(Decision per §9.)*

```yaml
relationships:                       # written into individual shots
  same_setup_as: [shot_index, ...]   # coverage group — same camera + framing of same action
  continues_from: [shot_index, ...]  # action continuation across cut
  alt_take_of: [shot_index, ...]     # different take of the same setup

cross_shot:                          # clip-level summary
  coverage_groups: [{label, shot_indices, setup_description}]
  continuity_chains: [{label, shot_indices, action_description}]
  alt_take_groups: [{label, shot_indices, why}]
  energy_arc: rising | falling | flat | spiky | varied
```

---

## 5. Clip-level fields

### 5.1 Computed

```yaml
technical:
  codec, container, bit_depth, color_space, color_primaries, transfer_function,
  pixel_aspect_ratio, scan_type, ...

audio:
  loudness: {integrated_lufs, true_peak, lra, short_term_peaks: [{time, lufs}]}
  silence_regions: [{start, end}]
  channel_layout, sample_rate, ...

transcript:
  full_text: string
  language: string
  segments: [{start, end, text, speaker?, confidence}]

motion:
  overall_level: low | medium | high
  peaks: [{time, intensity}]
  quiet_regions: [{start, end}]

cuts:
  detected_cut_count: int
  cut_points: [{time, score}]
  adaptive_threshold: float
  threshold_stats: {n, mean, sd, chosen, source}
  is_edited_sequence: bool
  cut_density_per_minute: float
```

### 5.2 Vision-described (provenance)

```yaml
clip_summary: string                  # Primary paragraph — colleague-style first impression, 2-4 sentences.
                                      # This is what becomes the clip's Description in Resolve.
clip_summary_oneliner: string         # Elevator-pitch single sentence.

editorial_classification:
  primary_use: action | interview | b_roll | insert | establishing | montage | screen_recording | titles | finished_video | other
  select_potential: low | medium | high
  energy_arc: rising | falling | flat | spiky | varied | unknown
  style: documentary | narrative | experimental | commercial | mixed_genre | unknown
  genre_indicators: [string]
  reason: string                      # why this classification

editing_notes:                        # Clip-level, complements per-shot fields
  best_moments: [string]              # Clip-wide notable moments (separate from per-shot best_moment)
  continuity_flags: [string]
  qc_flags: [string]
  search_tags: [string]               # Becomes the clip's Keywords in Resolve
```

### 5.3 QC observations

```yaml
qc:
  warnings: [{type, severity: info|warn|error, time?, shot_index?, message}]
  technical_issues: [{type, time?, message}]
  coverage_gaps: [{time_range, reason}]      # regions vision couldn't characterize
  shots_missing_frames: [shot_index]         # should be empty in V2 — frame sampler reform per §6
  continuity_observations:                    # cross-shot QC; framed as observations, not assertions
    - {kind: eye_line | screen_direction, shot_indices: [int, ...], observation: string, confidence: low|medium|high}
```

---

## 6. Frame sampling implications

To populate the schema, frame sampling must guarantee:

| Shot characteristic | Frames sampled |
|---|---|
| Every shot, regardless of duration | 1 mid-shot representative (mandatory) |
| Shot > 5s | +1 (2 total) |
| Shot > 15s | +1 (3 total) |
| Shot > 30s | +1 per additional 15s |
| Detected motion peak inside a shot | +1 |
| Transcript speech onset inside a shot (>1s of speech) | +1 |
| Shot boundaries (start frame, end frame) | for cuttability assessment |
| Every flash_candidate | mid-frame for vision adjudication (preserved as-is) |

**Budget model:**
- `required_frames = Σ (per-shot reservations) + Σ (flash_candidates) + Σ (cut boundary pairs)`
- `effective_budget = max(requested_budget, required_frames)`
- `HARD_FRAME_CAP = min(512, duration_seconds * 2)` — runaway-clip safety net only, scales with duration so short clips can't request hundreds of frames

For the CKY clip (152s, 34 shots, 47 flash_candidates): ~34 representative + ~34*2 boundary + 47 flash + ~3 motion + ~20 transcript-relevant ≈ 155 frames. Readable, not excessive.

---

## 7. Validation — how we know the schema works

The schema is sufficient when an LLM can do all of the following given **only the analysis output** (no source video access):

1. **Briefing:** Generate a useful 3-paragraph briefing on a bin. Tested by reading aloud to a human editor and asking "is this accurate, useful, and the kind of thing you'd want to know?"
2. **Search:** Answer "find every clip with [X]" using `search_tags` + `content` fields. Tested by hand-verifying retrievals against the source.
3. **Cuttability:** Given any two shots, predict whether they cut well together using `cuttability` + `cross_shot`. Tested against human editor judgment on a sample of pairs.
4. **Assembly:** Draft a 60-second rough cut from a bin given a brief, output as a Resolve-importable EDL with shot in/out points. Tested by importing, watching, and rating.
5. **Coverage analysis:** Identify gaps ("no coverage of the interior at sunset", "no reaction shot for moment X"). Tested by hand-verifying claims against the bin.

If those tasks succeed using only the analysis, the schema is sufficient. If they require re-watching the video, identify what was missing and iterate the schema.

---

## 8. Open questions (iterate here)

Organized by category. The first set (8.1) is granularity-of-vocabulary; the rest are structural / lifecycle / scope questions that affect what the schema *is*, not just what fields it has.

### 8.1 Granularity of vocabulary

1. **`shot_size` levels** — 8 is comprehensive but editors typically work in 5 (WS / MS / CU / ECU + insert). Collapse to 5 with `establishing` as a flag on framing rather than its own size?
2. **`camera_height` necessity** — useful for action / narrative, less so for documentary / interview. Keep optional, drop, or make conditional?
3. **`depth_of_field`** — distinguishes cinematic from observational. Sometimes inferrable, sometimes not. Worth attempting?
4. **Performance fields** — add per-shot `emotional_register` / `energy` / `eye_line` for shots with people? Useful for interview / narrative, overkill for action / b-roll.
5. **Lens characterization** — wide / normal / tele, anamorphic, fisheye. Sometimes inferrable, often not. Worth attempting?
6. **VFX / composite vs practical** — useful for finishing workflow planning. Add as a flag?
7. **Aesthetic descriptors** — genre-flavored fields like `cinematic_quality`, `production_value`, `style` (documentary / narrative / experimental / commercial)?
8. **Stillness sub-typing** — when `pacing: still`, is it "frozen tension" or "dead air"? Useful distinction for editorial?
9. **Speaker identification in `transcript_overlap`** — Whisper can diarize. Surface speaker IDs per shot, or keep transcript flat?

### 8.2 Structural — what counts as an analysis unit?

10. **What IS a "shot"?** The CKY clip showed 82 raw scene-detection cuts collapsed to 34 shots after short-shot / flash filtering. Which is the right unit for the schema — the 34, the 82, or *both* (shots + sub-shot beats as a hierarchy)?
11. **Sub-shot beats.** Within a long take (e.g., a 30s steadicam shot), should there be sub-shot units for "actor enters frame," "first line of dialogue," "exit"? Hierarchical units?
12. **Multi-shot sequences.** Should the schema support sequence units (a montage as one analyzable unit, an action beat as one) above the shot?
13. **Composite shots.** Split screens, picture-in-picture, multi-angle. One shot record with sub-frames, or several parallel shots?
14. **Transitions as first-class.** Cross-fades, dissolves, wipes — is the transition itself a unit, or just a boundary attribute on adjacent shots?

### 8.3 Identity & versioning

15. **Source identity.** Keyed to the file (content hash), the Resolve clip ID, or both? Same media file in two projects — same analysis or two?
16. **What `source: "vision_v0.2"` actually means.** Model version? Prompt hash? Schema version? All three? When does it bump?
17. **Vision provider abstraction.** Today it's Claude via host_chat_paths. What about GPT, Gemini, local LLMs? Does the schema commit to Claude-specific behavior or stay model-agnostic?
18. **Time precision.** Float seconds, frame numbers, SMPTE timecode (with drop-frame handling). Store all three? Just two? Which is the canonical reference?

### 8.4 Cross-shot & cross-clip scope

19. **Per-shot suggested pairs vs centralized cross_shot groups.** For a 100-shot bin the cross_shot pass needs all shots in context. Is per-shot `cuts_well_to: [top-K]` cheaper and more useful than centralized groups?
20. **`cuts_well_to` / `cuts_poorly_to` scaling.** N² explosion. Cap to top-K per shot, compute on-demand, or store full pairwise matrix?
21. **Cross-clip relationships.** Should `relationships` reference shots in *other* clips (same person across clips, same location, alt takes)? Huge payoff for collaboration, requires bin-level vision pass and probably embeddings.
22. **Project-level summary.** Above `clip_summary` and `editorial_classification` — a project-level "this is a CKY-style stunt comedy, recurring people are X and Y, tone is irreverent, primary location is suburban PA"? Where does that live and who generates it?
23. **Continuity errors as QC.** The cross_shot pass could flag screen-direction breaks, eye-line mismatches, prop position changes. In QC, or out of scope?

### 8.5 Lifecycle & re-analysis

24. **Auto-reanalysis triggers.** When does analysis re-run automatically — source file mtime change, schema version bump, vision model improvement, never (manual only)?
25. **Partial analysis.** New clip added to an existing bin mid-project — analyze in isolation, or trigger a bin-level re-run for cross-shot / cross-clip relationships?
26. **Schema-version migration.** When the schema bumps (v2.0 → v2.1), what happens to existing records — auto-migrate cleanly mappable fields, leave new fields null, or full reanalyze?
27. **Re-cut alignment / stable shot IDs.** If the editor cuts a timeline using shot 12, then we re-analyze and shot boundaries shift by 3 frames, does the timeline edit still reference the same beat? Need stable shot IDs that survive re-analysis (probably a content-based hash of the shot's time region + representative frame).
28. **Cache invalidation per layer.** With composable layers (technical / motion / transcript / vision / cross-shot) each has its own re-run signature. What's the right granularity?

### 8.6 Storage & retrieval

29. **Embeddings — text.** For semantic search over shot descriptions and clip summaries, we want vector embeddings. Stored in the schema, a separate index, or both? Which embedding model?
30. **Embeddings — visual.** CLIP-style embeddings of representative frames for visual similarity. Same questions.
31. **Storage scale.** A 100-clip project with rich V2 analyses + embeddings + frames is non-trivial. Local-first vs cloud, where does the bin's analysis live at scale, what's pruned?
32. **Frame retention policy.** Do we keep sampled JPEGs forever, or prune after vision commits? They're useful for human review and re-analysis but they accumulate.

### 8.7 Correction model

33. **Correction granularity.** Single field, field group, whole shot, whole clip? Each correction is its own changelog entry, or batched?
34. **Correction propagation.** If user corrects shot 12's `editorial_role`, does `cross_shot`, `clip_summary`, `editorial_classification` re-compute automatically, get marked stale, or stay frozen until user asks?
35. **Multi-user conflict resolution.** Provenance + recency handles human-vs-machine. For human-vs-human (two editors correcting differently), is it last-write-wins, lock-on-edit, or branching with merge?
36. **Audit trail visibility.** Surface the changelog in the UI ("last corrected by Sam on May 18, was 'medium' before"), keep it implicit, or summary-only?
37. **Confidence threshold policy.** If a field has `confidence: low`, do downstream tools (search, assembly) skip it, downweight it, or use it as-is?

### 8.8 Editorial / domain

38. **Coverage philosophy.** Does the schema express *desired* coverage (master + close + reverse expected), or only *observed*? Should there be "this scene is missing a wide" baked in for narrative work?
39. **Genre awareness.** Comedy vs drama vs documentary vs commercial value different things in editing. Does `editorial_classification` carry genre-aware modifiers, or stay genre-neutral and let downstream tools apply genre weighting?
40. **Spoiler / narrative abstraction.** For narrative work, literal shot descriptions might spoil the cut for the LLM driving assembly. Do we want a narrative-abstract mode that hides reveal moments?
41. **Best-moment salience.** Today every shot gets one `best_moment`. For a quiet shot with no notable beat, that field becomes noise. Make nullable + require justification, or auto-suppress for shots below some salience threshold?

### 8.9 Cross-format / scope expansion

42. **Audio-only clips.** Music tracks, VO recordings, SFX library items. What does the schema look like with no visual layer?
43. **Image / still clips.** Stills, graphics, title cards. Most fields don't apply; what's the minimal record?
44. **Subclips of a master.** Resolve supports subclips. Does analysis attach to the master clip, the subclip, or both? When the editor extends the subclip, does analysis re-run?
45. **Multicam clips.** Resolve multicam = several angles synced as one clip. Per-angle analysis with cross-angle relationships, or treat as single composite?
46. **Embedded timecode.** Source media with sync timecode (camera roll TC) — track it in the schema alongside elapsed-seconds-from-clip-start?
47. **External metadata ingestion.** ALE files, slate logs from set, EDL imports, script breakdowns. Ingest as additional provenance sources, or out of scope?

---

## 9. Decisions log

Resolved through discussion on 2026-05-18. Captured here so the open-questions list above stays as a working record of what was undecided at first cut, while this section is the source of truth for what's locked.

### 9.1 Perspective decisions (user-facing intent)

| Q | Decision | Why |
|---|---|---|
| §8.2 Q10-12 (shot vs beat vs hierarchy) | **Shot is the unit.** No hierarchical sub-shot beats; no multi-shot sequences as first-class units. | Adaptive cut detection produces shot ≈ beat. The "continuous take detected as N shots" case is captured by `relationships.continues_from` / `same_setup_as` instead of forcing a two-level data model. |
| §8.8 Q38 (coverage philosophy) | **Describe primarily; ask about gaps that are unusual for the detected editorial role.** Never assert "you're missing X" as fact. | Dialogue scene with no reverse → flag as question. B-roll grab bag → no flag. Conservative; surfaces as observation, never blocks. |
| §8.4 Q21 + behavior | **Recognize patterns across clips (same person, same location, alt takes), do NOT make editorial suggestions in the schema.** | Pattern recognition is data the user can ask about. Editorial suggestions ("you should cut these together") cross from observation into recommendation; those belong in runtime chat against the analysis, not stored fields. |
| §8.5 Q24 (auto-reanalysis) | **Default: notify on session start, execute on explicit ask. Opt-in autonomous mode is V2.1+ and requires explicit setup.** | Session-based reality of Claude Code / Codex makes daemon mode non-trivial; document the setup in §10 below. |
| §8.4 Q22 + §8.8 Q39 (genre/tone, project-level identity) | **Schema carries genre/tone via `editorial_classification`. Same schema serves raw clips AND finished-video analysis via `primary_use: finished_video` + optional extension fields.** | The `filmmaker-learning` skill is the finished-video case. One schema, two modes. |

### 9.2 Schema removals (consequence of perspective decisions)

- **`relationships.cuts_well_to`** — removed from schema. Editorial suggestion, not pattern recognition.
- **`relationships.cuts_poorly_to`** — removed from schema. Same reason.
- **Hierarchical sub-shot beats** — not added. Shot is the unit.

### 9.3 Technical decisions (resolved against principles)

| Q | Decision |
|---|---|
| §8.1 vocabulary granularity (Q1-9) | Include reasonable enums (keep 8-level `shot_size`, etc.); mark optional / nullable so vision can skip when not applicable. Better to have the slot than miss the info. |
| §8.3 Q15 (source identity) | Store **both** file content hash AND Resolve clip ID. Same file in two projects = two clip records linked by content hash. |
| §8.3 Q16 (vision version semantics) | `source` provenance is a triple: `{model, prompt_hash, schema_version}`. Bumps when any element changes. |
| §8.3 Q17 (provider abstraction) | Schema is model-agnostic. `source.model` field identifies which model produced subjective fields. |
| §8.3 Q18 (time precision) | Store all three: float seconds (canonical), frame number (1-based at fps), SMPTE timecode (drop-frame aware). Float seconds is the reference; others are derived but stored for convenience. |
| §8.5 Q25 (partial analysis) | New clip in existing bin triggers per-clip analysis + cross-clip pass. Don't re-run other clips' per-clip analysis. |
| §8.5 Q26 (schema migration) | Auto-migrate cleanly mappable fields on schema bump; leave new fields null pending re-vision. Migration is idempotent. |
| §8.5 Q27 (stable shot IDs) | **Critical.** Shot ID = content hash of (time region rounded to nearest second, representative frame perceptual hash). Survives ±N-frame boundary shifts on re-analysis so timeline references stay stable. |
| §8.5 Q28 (cache invalidation per layer) | Each layer carries its own signature `{layer_version, input_hashes}`. Re-runs only the layers whose signatures change. |
| §8.6 Q29-30 (embeddings) | Yes, text + visual embeddings, stored in separate index keyed by `(clip_id, shot_id)`. Computed at analysis time. Embedding model TBD (probably nomic-embed-text + CLIP) but pluggable. |
| §8.6 Q31-32 (storage / retention) | Frames retained by default; pruning is V2.1 work. Local-first storage; cloud is paid-tier per §V2-architecture memory. |
| §8.7 Q33-34 (correction granularity, propagation) | Per-field corrections, each its own changelog entry. Corrections mark derivative fields stale (don't auto-recompute); user decides when to re-run derivations. |
| §8.7 Q35 (multi-user conflicts) | Default: recency wins with audit trail. Sophisticated conflict resolution (locking, branching) is post-V2.1. |
| §8.7 Q36 (audit trail visibility) | Surface in correction UI. Each field shows last-corrected-by-whom-when on hover/expand. |
| §8.7 Q37 (low-confidence policy) | Downstream consumers receive the value with the confidence label; they choose whether to use it. Default policy: include with confidence weighting, don't hard-filter. |
| §8.9 (cross-format scope) | V2.0: raw clips, finished videos, stills (with field-applicability rules). V2.1: audio-only, multicam, subclips. |

### 9.4 Granular field decisions (deep dive 2026-05-18, revised after pushback)

Principle reset: the schema's defense against noise is **confidence + nullable**, not field absence. Include the capability; let vision return `unknown` / `null` when evidence is thin. The earlier pass was inconsistently conservative — these are the revised decisions.

| Q | Decision | Notes |
|---|---|---|
| §8.1 Q2 `camera_height` | **Include, nullable.** Enum: eye_level / high_angle / low_angle / birds_eye / dutch / unknown | High inferrability for shots with clear subject; `unknown` for landscapes / abstracts |
| §8.1 Q3 `depth_of_field` | **Include, nullable.** Enum: deep / shallow / rack_focus / unknown | Expect mostly `unknown` at 352×262 sampled-frame resolution; becomes useful when sampling upgrades |
| §8.1 Q4 performance fields | **Include conditionally** when `primary_subject.type == person`: `eye_line` (closed enum: to_camera / off_left / off_right / down / up / closed / unknown), `energy` (low/medium/high), `emotional_register` (short free-form string, NOT enum — avoids forcing categorical claims on ambiguous content) | Skip entirely when subject isn't a person |
| §8.1 Q5 lens characterization | **Include both** `lens_character` (wide / normal / tele / fisheye / unknown) AND `lens_format` (spherical / anamorphic / fisheye / unknown), nullable | Anamorphic has distinctive horizontal flares + aspect cues visible at 352×262; `unknown` is a valid answer when cues are absent |
| §8.1 Q6 VFX / composite | **Include both** `composite_shot: bool` AND `vfx_present` (none / minor / major / unknown), nullable | Major VFX is detectable (clear CG, environment build, greenscreen capture). Minor VFX correctly returns `unknown` / `none`; that's the confidence system working |
| §8.1 Q7 aesthetic descriptors | **Include `style`** (documentary / narrative / experimental / commercial / mixed_genre / unknown), nullable. **Skip `cinematic_quality` and `production_value`** | `style` is industry-standard vocabulary, useful for retrieval and editorial calibration; value-judgment fields genuinely risk bias and add nothing over free-form prose in `clip_summary` |
| §8.1 Q8 stillness sub-typing | **Include both** `stillness_type` enum (held_tension / quiet / contemplative / transitional / dead_air / unknown) AND `pacing_note: string \| null` | Enum gives filterability; freeform note gives nuance. Both populated when `pacing: still` or `variable` |
| §8.1 Q9 speaker IDs | **Include `speaker_id: string \| null`** in transcript segments | Whisper diarization is deterministic and cheap; speaker-to-name mapping is a UI affordance |
| §8.2 Q13 composites | **Include `composite_shot: bool` AND `composite_panels: [{region, primary_subject, action}] \| null`** in V2.0 | Composites are common in finished-video analysis (music videos, multi-angle commercial work); cheap field, valuable when present |
| §8.2 Q14 transitions | **Boundary attributes**: `transition_in: {type, duration_seconds} \| null` and `transition_out: {type, duration_seconds} \| null` on each shot. Type enum: cut / fade / dissolve / wipe / unknown. Default `{type: cut, duration: 0}` | No separate "transition shot" entity in V2.0 |
| §8.4 Q23 continuity QC | **Include in V2.0** as QC warnings, scope: eye-line breaks + screen direction reversals. Skip prop continuity (needs object tracking we don't have). Frame as "observations the machine asks about" not "errors the machine asserts" | Fits the user's "describe + ask about gaps" framing; confidence system handles false-positive risk |
| §8.8 Q40 narrative spoiler abstraction | **Skip for V2.0.** When needed, layer a "narrative summary view" on top of the analysis, don't bake into per-shot descriptions | View-layer concern, not schema; analysis stays full-fidelity |
| §8.8 Q41 best-moment salience | **`best_moment` nullable with explicit prompt guidance**: "Only populate if there's a moment an editor would naturally point to. Return null if the shot is a sustained flat beat." Add `best_moment_present: bool` for quick filtering | Trust honest null over forced noise |

### 9.5 Still open (intentionally deferred to V2.1+)

These are noted for tracking; not blocking V2.0 lock.

- **§8.1** higher-resolution frame sampling so `depth_of_field` and `lens_format` become more reliable
- **§8.4 Q23** prop continuity tracking (separate from eye-line/screen-direction, needs object tracking we don't have)
- **§8.8 Q40** narrative spoiler-free view (a transform over the analysis, not a schema change)
- **§8.9** audio-only clips, image/still clips, subclips, multicam (per §9.3)

---

## 10. Auto-mode and re-analysis triggers — practical setup

Per §9.1 Q24 decision: V2.0 defaults to notify-and-ask; true autonomous mode is opt-in and V2.1+. Documenting the practical options here because the session-based reality of Claude Code / Codex makes "auto-reanalyze when source changes" non-trivial.

### 10.1 Default (V2.0): notify-on-session-start

When a chat session starts in a project, the MCP server checks the `heartbeat.json` and the project's media against last-known signatures:

```
You're back. Since last session:
  • 3 clips have new mtimes — content may have changed
  • 1 clip has stale vision (model improved 0.2 → 0.3)
  • 0 clips have failed analyses needing retry
Re-analyze now, on demand, or skip?
```

User answers in chat; the machine acts on the choice. No background daemon required.

### 10.2 Opt-in semi-auto: persistent chat session

If the user keeps a Claude Code / Codex session alive in the background (e.g., a dedicated "analysis assistant" session), the MCP server can periodically re-check and trigger analysis with no prompt — the session is the daemon.

Tradeoffs:
- **Pro:** zero extra infrastructure; just leave the session running.
- **Con:** session can accumulate stale state, may consume tokens for periodic checks even when nothing changed, doesn't survive system restarts unless deliberately restored.
- **Practical:** works fine for "leave it running overnight to catch new clips"; less suited to multi-day uninterrupted operation.

### 10.3 Opt-in full-auto: separate daemon (V2.1+)

A standalone process that watches the project's media directories with `fsevents`/`inotify`, debounces changes, and triggers `analyze_clip` calls against the MCP server without requiring a chat session.

Required to build:
- Daemon binary or system service (launchd / systemd plist)
- Per-project preference file declaring what triggers auto-mode
- Explicit user permission gate at first-use ("daemon will run analysis when source files change; OK?")
- Notification surface (heartbeat updates, optional desktop notification, optional Slack/email)
- Failure handling (don't auto-retry indefinitely on broken sources)

Deferred to V2.1 because it's real infrastructure work and most users will be fine with §10.1.

### 10.4 Hybrid: scheduled checks

A simpler middle ground — a cron / launchd job that runs `media_analysis(action="plan", target="project")` periodically and updates `heartbeat.json` with what would need re-analysis. Doesn't trigger analyses, just keeps the heartbeat fresh so §10.1's session-start prompt is accurate.

Possible V2.0 nice-to-have if §10.1 alone feels lacking.

---



---

## 11. Implementation notes (tracking, not part of the schema)

- **Vocabulary stability:** once an enum is locked, it cannot change without a `schema_version` bump and migration. Draft loosely, lock late.
- **Provenance source strings:** versioned (`vision_v0.2`, `vision_v0.3`) so historical data is interpretable after vision improvements.
- **Confidence calibration:** vision should default `medium` unless evidence is clearly strong (`high`) or thin (`low`). Calibration measurable over time by sampling human review.
- **Field-level required / optional:** most fields nullable so partial analyses are valid. Required minimums per shot: `shot_index`, `time_range`, `frame_range`, `representative_frame`, `description`.
- **Migration from V1:** existing `analysis.json` records carry the old shape; a migration pass extracts what maps cleanly (shot_descriptions → shots[].description, editorial_classification → clip-level, shot_table → shots[].time_range/frame_range) and leaves new V2 fields null pending re-vision.

---

*End of draft. Edit inline. Open questions get answered as we iterate.*
