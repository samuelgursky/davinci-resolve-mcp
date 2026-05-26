-- ==============================================================
-- V2 Analysis Database Schema (source-of-truth)
-- ==============================================================
-- Source-of-truth store for clip analysis with per-field provenance
-- and append-only changelog. Designed for SQLite local; portable to
-- Postgres for cloud / multi-user (paid tier).
--
-- Companion document: docs/design/v2-shot-schema-spec.md
-- Related memory:    project_v2_architecture.md
--
-- Design principles:
--   1. Computed fields (technical, motion, cuts, audio, transcript) do NOT
--      carry provenance — they re-derive cleanly from source media.
--   2. Subjective fields (visual, content, editorial, cuttability, relationships,
--      slate, clip_summary, classification) carry per-field provenance
--      {value, source, author, timestamp} plus append-only changelog.
--   3. Multi-user safe from day one: every write records author + timestamp.
--   4. Stable shot IDs (content-hash-based) survive small boundary shifts on
--      re-analysis, so timeline references and human corrections persist.
--   5. Embeddings live in a separate table keyed by (entity, kind, model).
--
-- Migration plan (V1 derived index → V2 source of truth):
--   - V1 index.sqlite is built FROM analysis.json reports (one-way).
--   - V2 analysis.sqlite is canonical; analysis.json becomes an EXPORT/snapshot.
--   - During transition: both written in parallel; V1 index can be removed
--     once V2 is reliable and all consumers have been updated.
--   - Existing analysis.json files can be ingested into V2 via a migration
--     script that maps V1 paths to V2 tables (technical → technical, vision
--     fields → subjective_fields rows, marker_plan → shots + qc_observations).
-- ==============================================================


-- ============ Core entities ============

CREATE TABLE clips (
    clip_uuid TEXT PRIMARY KEY,             -- stable UUID; primary identity
    file_content_hash TEXT NOT NULL,        -- SHA-256 of source media; cross-project identity
    resolve_clip_id TEXT,                   -- current Resolve media pool ID (may change)
    clip_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    fps REAL,
    resolution TEXT,
    media_type TEXT,
    bin_path TEXT,                          -- last-known bin location in Resolve
    project_id TEXT,
    project_name TEXT,
    created_at TEXT NOT NULL,               -- ISO 8601 UTC
    updated_at TEXT NOT NULL,
    -- Per-layer cache signatures: each layer re-runs only if its signature changes
    technical_signature TEXT,
    audio_signature TEXT,
    transcript_signature TEXT,
    motion_signature TEXT,
    cuts_signature TEXT,
    vision_input_signature TEXT,
    vision_committed_at TEXT,
    schema_version TEXT NOT NULL DEFAULT '2.0'
);

CREATE INDEX idx_clips_file_content_hash ON clips(file_content_hash);
CREATE INDEX idx_clips_resolve_clip_id ON clips(resolve_clip_id);
CREATE INDEX idx_clips_project_id ON clips(project_id);


-- shot_uuid = content hash of (time_region rounded to nearest second,
--                              representative_frame_phash truncated).
-- This makes shot IDs stable across re-analysis when boundaries shift by a
-- few frames. Timeline references and human corrections survive boundary
-- jitter. See spec §9.3 §8.5 Q27.
CREATE TABLE shots (
    shot_uuid TEXT PRIMARY KEY,
    clip_uuid TEXT NOT NULL,
    shot_index INTEGER NOT NULL,            -- 1-based position within clip
    time_seconds_start REAL NOT NULL,
    time_seconds_end REAL NOT NULL,
    frame_start INTEGER,
    frame_end INTEGER,
    representative_frame_path TEXT,
    representative_frame_phash TEXT,
    transition_in_type TEXT,                -- cut|fade|dissolve|wipe|unknown
    transition_in_duration_seconds REAL,
    transition_out_type TEXT,
    transition_out_duration_seconds REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (clip_uuid) REFERENCES clips(clip_uuid) ON DELETE CASCADE
);

CREATE INDEX idx_shots_clip_uuid ON shots(clip_uuid);
CREATE INDEX idx_shots_time_range ON shots(clip_uuid, time_seconds_start);
CREATE UNIQUE INDEX idx_shots_clip_index ON shots(clip_uuid, shot_index);


-- ============ Computed layers (no provenance — re-derive cleanly) ============

CREATE TABLE technical (
    clip_uuid TEXT PRIMARY KEY,
    codec TEXT,
    container TEXT,
    bit_depth INTEGER,
    color_space TEXT,
    color_primaries TEXT,
    transfer_function TEXT,
    pixel_aspect_ratio REAL,
    scan_type TEXT,
    sample_rate INTEGER,
    channel_layout TEXT,
    full_json TEXT NOT NULL,                -- complete payload for fields not normalized
    layer_signature TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    FOREIGN KEY (clip_uuid) REFERENCES clips(clip_uuid) ON DELETE CASCADE
);


CREATE TABLE motion (
    clip_uuid TEXT PRIMARY KEY,
    overall_level TEXT,                     -- low|medium|high
    peaks_json TEXT,                        -- [{time, intensity, direction?}]
    quiet_regions_json TEXT,                -- [{start, end}]
    average_frame_delta REAL,
    max_frame_delta REAL,
    layer_signature TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    FOREIGN KEY (clip_uuid) REFERENCES clips(clip_uuid) ON DELETE CASCADE
);


CREATE TABLE cuts (
    clip_uuid TEXT PRIMARY KEY,
    detected_cut_count INTEGER,
    cut_points_json TEXT,                   -- [{time, score}]
    adaptive_threshold REAL,
    threshold_stats_json TEXT,              -- {n, mean, sd, chosen, source}
    is_edited_sequence INTEGER,             -- bool as 0/1
    cut_density_per_minute REAL,
    layer_signature TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    FOREIGN KEY (clip_uuid) REFERENCES clips(clip_uuid) ON DELETE CASCADE
);


CREATE TABLE audio (
    clip_uuid TEXT PRIMARY KEY,
    integrated_lufs REAL,
    true_peak_dbfs REAL,
    lra REAL,                               -- loudness range
    silence_regions_json TEXT,              -- [{start, end}]
    loudness_peaks_json TEXT,               -- [{time, lufs}]
    layer_signature TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    FOREIGN KEY (clip_uuid) REFERENCES clips(clip_uuid) ON DELETE CASCADE
);


CREATE TABLE transcript (
    clip_uuid TEXT PRIMARY KEY,
    full_text TEXT,
    language TEXT,
    backend TEXT,                           -- 'whisper_cli', 'mlx_whisper', etc.
    layer_signature TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    FOREIGN KEY (clip_uuid) REFERENCES clips(clip_uuid) ON DELETE CASCADE
);


CREATE TABLE transcript_segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_uuid TEXT NOT NULL,
    segment_index INTEGER NOT NULL,
    start_seconds REAL NOT NULL,
    end_seconds REAL NOT NULL,
    text TEXT NOT NULL,
    speaker_id TEXT,                        -- anonymous from diarization; user labels separately
    segment_confidence REAL,
    FOREIGN KEY (clip_uuid) REFERENCES clips(clip_uuid) ON DELETE CASCADE
);

CREATE INDEX idx_transcript_segments_clip ON transcript_segments(clip_uuid, start_seconds);
CREATE INDEX idx_transcript_segments_speaker ON transcript_segments(clip_uuid, speaker_id);


-- ============ Subjective fields (with per-field provenance) ============
--
-- Single normalized table for ALL subjective fields across clips and shots.
-- field_path uses dot notation matching the V2 schema in v2-shot-schema-spec.md:
--   Clip-level:  "clip_summary", "clip_summary_oneliner", "editorial_classification.primary_use", ...
--   Shot-level:  "visual.shot_size", "visual.framing", "content.action", "editorial.select_potential", ...
--
-- Current values: WHERE superseded_at IS NULL (one current row per field_path per entity)
-- Historical:     all rows with superseded_at NOT NULL = changelog tail
--
-- Why one table instead of one column per field:
--   - V2 has ~40+ subjective fields per shot. Schema-per-field is wide and brittle.
--   - Adding new fields in V2.1+ becomes a code change, not a schema migration.
--   - Provenance per field is uniform.
--   - Trade-off: queries need JSON extraction; that's fine for SQLite with `json_extract`.

CREATE TABLE subjective_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('clip', 'shot')),
    entity_uuid TEXT NOT NULL,
    field_path TEXT NOT NULL,
    value_json TEXT NOT NULL,               -- string, number, bool, object — always JSON-encoded
    confidence TEXT,                        -- low|medium|high (group-level, often null at field level)
    source TEXT NOT NULL,                   -- e.g. 'vision_v0.2', 'human', 'computed_initial'
    source_model TEXT,                      -- e.g. 'claude-opus-4-7' for vision sources
    source_prompt_hash TEXT,                -- prompt hash for vision sources
    author TEXT NOT NULL,                   -- 'system', 'sam@bradfordoperations.com', etc.
    timestamp TEXT NOT NULL,                -- ISO 8601 UTC
    superseded_at TEXT,                     -- when replaced; NULL if current value
    UNIQUE(entity_type, entity_uuid, field_path, timestamp)
);

CREATE INDEX idx_sf_entity ON subjective_fields(entity_type, entity_uuid);
CREATE INDEX idx_sf_field_path ON subjective_fields(field_path);
-- Current-values index for the most-common query
CREATE INDEX idx_sf_current ON subjective_fields(entity_type, entity_uuid, field_path)
    WHERE superseded_at IS NULL;


-- Append-only changelog: every change creates a row here.
-- This is the audit trail; `subjective_fields` is the queryable current/historical store.
CREATE TABLE field_changelog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_uuid TEXT NOT NULL,
    field_path TEXT NOT NULL,
    previous_value_json TEXT,               -- NULL on first write
    new_value_json TEXT NOT NULL,
    previous_source TEXT,
    new_source TEXT NOT NULL,
    previous_author TEXT,
    new_author TEXT NOT NULL,
    change_reason TEXT,                     -- optional commit message
    timestamp TEXT NOT NULL
);

CREATE INDEX idx_changelog_entity ON field_changelog(entity_type, entity_uuid, timestamp);
CREATE INDEX idx_changelog_author ON field_changelog(new_author, timestamp);
CREATE INDEX idx_changelog_field ON field_changelog(field_path, timestamp);


-- ============ Cross-shot relationships (subjective, vision-described) ============
--
-- Pattern recognition only — no editorial suggestions (no cuts_well_to / cuts_poorly_to).
-- Per spec §9.4 §8.4 Q21.

CREATE TABLE shot_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_shot_uuid TEXT NOT NULL,
    target_shot_uuid TEXT NOT NULL,
    relationship_type TEXT NOT NULL CHECK(relationship_type IN
        ('same_setup_as', 'continues_from', 'alt_take_of')),
    confidence TEXT,
    source TEXT NOT NULL,
    author TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    superseded_at TEXT,
    UNIQUE(source_shot_uuid, target_shot_uuid, relationship_type, timestamp),
    FOREIGN KEY (source_shot_uuid) REFERENCES shots(shot_uuid) ON DELETE CASCADE,
    FOREIGN KEY (target_shot_uuid) REFERENCES shots(shot_uuid) ON DELETE CASCADE
);

CREATE INDEX idx_relationships_source ON shot_relationships(source_shot_uuid)
    WHERE superseded_at IS NULL;
CREATE INDEX idx_relationships_target ON shot_relationships(target_shot_uuid)
    WHERE superseded_at IS NULL;
CREATE INDEX idx_relationships_type ON shot_relationships(relationship_type)
    WHERE superseded_at IS NULL;


-- ============ Frames sampled for vision ============

CREATE TABLE frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_uuid TEXT NOT NULL,
    shot_uuid TEXT,                         -- may be null for clip-level frames (first_usable, etc.)
    frame_index INTEGER NOT NULL,           -- index within frame_metadata array (1-based)
    time_seconds REAL NOT NULL,
    frame_path TEXT,
    selection_reason TEXT,                  -- shot_representative, shot_start, etc.
    delta_from_previous REAL,
    perceptual_hash TEXT,
    motion_peak INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (clip_uuid) REFERENCES clips(clip_uuid) ON DELETE CASCADE,
    FOREIGN KEY (shot_uuid) REFERENCES shots(shot_uuid) ON DELETE SET NULL
);

CREATE INDEX idx_frames_clip ON frames(clip_uuid, frame_index);
CREATE INDEX idx_frames_shot ON frames(shot_uuid);
CREATE INDEX idx_frames_time ON frames(clip_uuid, time_seconds);


-- ============ QC observations ============
--
-- Continuity observations from cross-shot pass (eye-line, screen direction),
-- coverage gaps, technical issues, etc. Surfaced as questions the machine
-- asks, not assertions. Humans can resolve them.

CREATE TABLE qc_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_uuid TEXT NOT NULL,
    shot_uuid TEXT,                         -- null if clip-level or cross-shot
    observation_type TEXT NOT NULL,
    -- e.g. 'eye_line', 'screen_direction', 'coverage_gap', 'technical_warning',
    --      'no_in_shot_frame_sampled', 'flash_frame_candidate', etc.
    severity TEXT NOT NULL CHECK(severity IN ('info', 'warn', 'error')),
    message TEXT NOT NULL,
    related_shot_indices_json TEXT,         -- for cross-shot observations
    confidence TEXT,
    source TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    resolved_by TEXT,
    resolved_at TEXT,
    resolution_note TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (clip_uuid) REFERENCES clips(clip_uuid) ON DELETE CASCADE,
    FOREIGN KEY (shot_uuid) REFERENCES shots(shot_uuid) ON DELETE SET NULL
);

CREATE INDEX idx_qc_clip ON qc_observations(clip_uuid);
CREATE INDEX idx_qc_unresolved ON qc_observations(clip_uuid, resolved)
    WHERE resolved = 0;
CREATE INDEX idx_qc_type ON qc_observations(observation_type, resolved);


-- ============ Embeddings ============
--
-- Separate table keyed by (entity, kind, model_version) so:
--   - We can store multiple embedding models per entity (text + visual + audio)
--   - Old embeddings stay around when we upgrade models
--   - Similarity queries use vector ops (vss_search if vss extension loaded, else cosine in app)

CREATE TABLE embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('clip', 'shot', 'frame')),
    entity_uuid TEXT NOT NULL,
    embedding_kind TEXT NOT NULL,           -- 'text_description', 'visual_clip', 'audio_clap'
    model_name TEXT NOT NULL,
    model_version TEXT,
    vector BLOB NOT NULL,                   -- raw float32 array
    dimension INTEGER NOT NULL,
    computed_at TEXT NOT NULL,
    UNIQUE(entity_type, entity_uuid, embedding_kind, model_name, model_version)
);

CREATE INDEX idx_embeddings_entity ON embeddings(entity_type, entity_uuid, embedding_kind);
CREATE INDEX idx_embeddings_kind ON embeddings(embedding_kind, model_name, model_version);


-- ============ DB metadata ============

CREATE TABLE db_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO db_metadata (key, value) VALUES
    ('schema_version', '2.0'),
    ('schema_created_at', strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    ('source_of_truth', 'true'),
    ('multi_user_safe', 'true');


-- ============ Helpful views ============

-- Current values per (entity, field_path), JSON-decoded for convenience.
-- Use json_extract() on value_json for typed access.
CREATE VIEW current_subjective_fields AS
SELECT
    entity_type,
    entity_uuid,
    field_path,
    value_json,
    confidence,
    source,
    author,
    timestamp
FROM subjective_fields
WHERE superseded_at IS NULL;


-- Open (unresolved) QC observations per clip.
CREATE VIEW open_qc_observations AS
SELECT
    clip_uuid,
    shot_uuid,
    observation_type,
    severity,
    message,
    confidence,
    source,
    created_at
FROM qc_observations
WHERE resolved = 0
ORDER BY clip_uuid, severity DESC, created_at;


-- Current cross-shot relationships, both directions denormalized for easy traversal.
CREATE VIEW current_shot_relationships AS
SELECT
    source_shot_uuid AS shot_a,
    target_shot_uuid AS shot_b,
    relationship_type,
    confidence,
    source,
    author,
    timestamp
FROM shot_relationships
WHERE superseded_at IS NULL;
