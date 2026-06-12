"""Per-project SQLite store for timeline versioning + brain edits (C6).

Lives at `<project_root>/_soul/timeline_brain.sqlite`. Tracks:

- `timeline_versions`     — every archived timeline duplicate (one row per archive)
- `brain_edits`           — every destructive edit, with target metric + before/after
- `timeline_clip_usage`   — which media pool items are placed where on which timeline

This DB is the **source of truth** for the timeline-mutation history of a project.
It coexists with the existing `jobs.sqlite` (operational job tracking) and
`index.sqlite` (rebuildable cache over JSON reports). When the V2 source-of-truth
migration (C1) lands, these tables move into the unified DB; until then, this is
a dedicated standalone store.

Concurrency: single-process access expected (Resolve is single-user). WAL mode
enabled to make reads from the control panel non-blocking against writes from
the MCP server.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Callable, Dict, Iterator, Optional, Tuple

logger = logging.getLogger("resolve-mcp.timeline-brain-db")

SCHEMA_VERSION = 12
DB_FILENAME = "timeline_brain.sqlite"
SOUL_DIRNAME = "_soul"

# How long SQLite waits internally for a busy lock before raising
# SQLITE_BUSY (in ms). Set high enough to absorb the dashboard's read traffic.
BUSY_TIMEOUT_MS = 5000

# Application-level retry settings on top of busy_timeout, used by transaction().
# These guard against rare cases where the timeout is exhausted under load.
_BUSY_RETRY_BACKOFF_SECONDS = (0.1, 0.3, 0.5)

_CONNECTION_LOCK = threading.Lock()
_CONNECTIONS: Dict[str, sqlite3.Connection] = {}


def db_path_for_project(project_root: str) -> str:
    """Return the on-disk path to the timeline-brain DB for a project."""
    return os.path.join(project_root, SOUL_DIRNAME, DB_FILENAME)


def _ensure_parent_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def _init_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")


# ── Migration registry ───────────────────────────────────────────────────────
#
# Each entry is keyed by the *target* version. The function receives an open
# connection and runs any schema changes required to advance from
# (target_version - 1) to target_version. Connect() walks this dict in order
# until the DB reaches SCHEMA_VERSION.
#
# Conventions:
# - Migrations are additive when possible (ADD COLUMN, CREATE TABLE IF NOT
#   EXISTS, CREATE INDEX IF NOT EXISTS). Destructive changes need an explicit
#   data-preserving copy-and-rename sequence.
# - Migration functions must be idempotent — if a column already exists (e.g.
#   from a partial prior run), the migration should detect that and continue.
# - Bump SCHEMA_VERSION at the top of this module + register the migration
#   here in the same edit. The runner will detect the bump and apply it.

_MIGRATIONS: Dict[int, Callable[[sqlite3.Connection], None]] = {}


def register_migration(target_version: int) -> Callable[[Callable[[sqlite3.Connection], None]], Callable[[sqlite3.Connection], None]]:
    """Decorator: registers a migration that advances the schema to `target_version`."""
    def decorator(fn: Callable[[sqlite3.Connection], None]) -> Callable[[sqlite3.Connection], None]:
        if target_version in _MIGRATIONS:
            raise RuntimeError(f"Duplicate migration for v{target_version}")
        _MIGRATIONS[target_version] = fn
        return fn
    return decorator


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    row = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in row)


def _read_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()
    except sqlite3.OperationalError:
        # Tables don't exist yet — treat as version 0.
        return 0
    if row is None:
        return 0
    try:
        return int(row["value"] if isinstance(row, sqlite3.Row) else row[0])
    except (TypeError, ValueError):
        return 0


def _write_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO schema_metadata(key, value) VALUES (?, ?)",
        ("schema_version", str(version)),
    )


def _run_pending_migrations(conn: sqlite3.Connection) -> None:
    """Bring the DB from its current schema_version up to SCHEMA_VERSION."""
    current = _read_schema_version(conn)
    if current >= SCHEMA_VERSION:
        return
    for target in sorted(_MIGRATIONS):
        if target <= current:
            continue
        if target > SCHEMA_VERSION:
            break
        migration = _MIGRATIONS[target]
        logger.info("Running timeline_brain_db migration: v%d → v%d", target - 1, target)
        migration(conn)
        _write_schema_version(conn, target)
        conn.commit()
        current = target


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS timeline_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timeline_name TEXT NOT NULL,
            version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            analysis_run_id TEXT,
            archived_timeline_name TEXT NOT NULL,
            archived_bin_path TEXT NOT NULL,
            drt_export_path TEXT,
            reason TEXT,
            UNIQUE(timeline_name, version)
        );

        CREATE INDEX IF NOT EXISTS ix_timeline_versions_name
            ON timeline_versions(timeline_name);
        CREATE INDEX IF NOT EXISTS ix_timeline_versions_run
            ON timeline_versions(analysis_run_id);

        CREATE TABLE IF NOT EXISTS brain_edits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_run_id TEXT NOT NULL,
            timeline_before TEXT,
            timeline_after TEXT,
            edit_type TEXT NOT NULL,
            tool_name TEXT,
            action_name TEXT,
            target_metric TEXT,
            metric_direction TEXT,
            before_value REAL,
            after_value REAL,
            rationale TEXT,
            params_json TEXT,
            result_summary_json TEXT,
            created_at TEXT NOT NULL,
            rolled_back_at TEXT
        );

        CREATE INDEX IF NOT EXISTS ix_brain_edits_run
            ON brain_edits(analysis_run_id);
        CREATE INDEX IF NOT EXISTS ix_brain_edits_timeline
            ON brain_edits(timeline_after);
        CREATE INDEX IF NOT EXISTS ix_brain_edits_type
            ON brain_edits(edit_type);

        CREATE TABLE IF NOT EXISTS timeline_clip_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_pool_item_id TEXT NOT NULL,
            timeline_name TEXT NOT NULL,
            timeline_version INTEGER,
            track_type TEXT NOT NULL,
            track_index INTEGER NOT NULL,
            in_frame INTEGER NOT NULL,
            out_frame INTEGER NOT NULL,
            analysis_run_id_at_placement TEXT,
            observed_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS ix_clip_usage_media
            ON timeline_clip_usage(media_pool_item_id);
        CREATE INDEX IF NOT EXISTS ix_clip_usage_timeline
            ON timeline_clip_usage(timeline_name, timeline_version);
        """
    )
    # Only stamp the version on a *fresh* DB. On an existing DB the recorded
    # version must be preserved so the migration runner can advance it from
    # whatever schema actually exists on disk. Overwriting unconditionally
    # would block every migration by making the DB always look up-to-date.
    if _read_schema_version(conn) == 0:
        _write_schema_version(conn, 1)
    conn.commit()


def connect(project_root: str) -> sqlite3.Connection:
    """Return a cached, schema-initialised connection for `project_root`.

    On first open: creates the tables if missing, then runs any pending
    migrations to bring the schema up to SCHEMA_VERSION.
    """
    if not project_root:
        raise ValueError("project_root is required")
    path = db_path_for_project(project_root)
    with _CONNECTION_LOCK:
        existing = _CONNECTIONS.get(path)
        if existing is not None:
            return existing
        _ensure_parent_dir(path)
        conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        _init_pragmas(conn)
        _create_schema(conn)
        _run_pending_migrations(conn)
        _CONNECTIONS[path] = conn
        return conn


def close_all() -> None:
    """Close every cached connection. Intended for tests + shutdown."""
    with _CONNECTION_LOCK:
        for conn in _CONNECTIONS.values():
            try:
                conn.close()
            except sqlite3.Error:
                pass
        _CONNECTIONS.clear()


@contextmanager
def transaction(project_root: str) -> Iterator[sqlite3.Connection]:
    """Context manager wrapping a write transaction.

    Uses BEGIN IMMEDIATE so concurrent dashboard readers don't trigger SQLITE_BUSY
    when a write is in flight. Retries on `database is locked` with exponential
    backoff so that contention between the MCP server and the dashboard doesn't
    surface as a user-visible error.
    """
    conn = connect(project_root)
    last_exc: Optional[sqlite3.OperationalError] = None
    began = False
    for delay in (0.0, *_BUSY_RETRY_BACKOFF_SECONDS):
        if delay > 0:
            time.sleep(delay)
        try:
            conn.execute("BEGIN IMMEDIATE")
            began = True
            break
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            last_exc = exc
            logger.debug("BEGIN IMMEDIATE saw busy lock (%s), retrying after %.2fs", exc, delay)
    if not began:
        assert last_exc is not None
        raise last_exc
    try:
        yield conn
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
        raise
    else:
        conn.execute("COMMIT")


def reset_for_test(project_root: str) -> None:
    """Drop + recreate every table. Tests only."""
    path = db_path_for_project(project_root)
    with _CONNECTION_LOCK:
        conn = _CONNECTIONS.pop(path, None)
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


# ── v2 migration: analysis_runs table + initiator columns ───────────────────


@register_migration(2)
def _migrate_v2_analysis_runs(conn: sqlite3.Connection) -> None:
    """Add analysis_runs table + initiator columns on existing tables.

    `analysis_runs` groups a sequence of brain_edits / timeline_versions under
    a single user- or brain-initiated operation. begin_run inserts a row,
    end_run updates ended_at + summary_json with the cumulative metric deltas.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS analysis_runs (
            id TEXT PRIMARY KEY,
            label TEXT,
            initiator TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            summary_json TEXT
        );

        CREATE INDEX IF NOT EXISTS ix_analysis_runs_started
            ON analysis_runs(started_at);
        """
    )
    # Add initiator column on brain_edits + timeline_versions for provenance.
    if not _column_exists(conn, "brain_edits", "initiator"):
        conn.execute("ALTER TABLE brain_edits ADD COLUMN initiator TEXT")
    if not _column_exists(conn, "timeline_versions", "initiator"):
        conn.execute("ALTER TABLE timeline_versions ADD COLUMN initiator TEXT")


# ── v3 migration: media_pool_changes table ───────────────────────────────────


@register_migration(3)
def _migrate_v3_media_pool_changes(conn: sqlite3.Connection) -> None:
    """Track destructive media-pool ops (delete clips/folders, replace, relink).

    These don't mutate a timeline directly but can offline clips referenced by
    timelines. Separate table from brain_edits because the addressable entity
    is a media_pool_item, not a timeline.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS media_pool_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_run_id TEXT,
            action TEXT NOT NULL,
            target_id TEXT,
            target_name TEXT,
            before_state_json TEXT,
            after_state_json TEXT,
            params_json TEXT,
            initiator TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS ix_media_pool_changes_run
            ON media_pool_changes(analysis_run_id);
        CREATE INDEX IF NOT EXISTS ix_media_pool_changes_target
            ON media_pool_changes(target_id);
        CREATE INDEX IF NOT EXISTS ix_media_pool_changes_action
            ON media_pool_changes(action);
        """
    )


# ── v4 migration: thumbnail_path on timeline_versions ───────────────────────


@register_migration(4)
def _migrate_v4_thumbnail_path(conn: sqlite3.Connection) -> None:
    """Add thumbnail_path column so the History view can render per-version stills."""
    if not _column_exists(conn, "timeline_versions", "thumbnail_path"):
        conn.execute("ALTER TABLE timeline_versions ADD COLUMN thumbnail_path TEXT")


# ── v5 migration: analysis_token_usage table for caps enforcement ───────────


# ── v6 migration: caps_events for refusal logging ───────────────────────────


@register_migration(6)
def _migrate_v6_caps_events(conn: sqlite3.Connection) -> None:
    """Log every caps refusal so the dashboard can show recent denials.

    Distinct from `analysis_token_usage` because refusals never spend tokens —
    we record the *intent* and the cap that blocked it, for debugging "why
    didn't my analysis run".
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS caps_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,           -- 'refusal' | 'timeout' | other
            reason TEXT,                         -- 'over_clip_cap' | 'over_day_cap' | ...
            preset TEXT,
            estimated_vision_tokens INTEGER,
            current_usage_json TEXT,
            cap_json TEXT,
            headroom_json TEXT,
            clip_id TEXT,
            job_id TEXT,
            occurred_at TEXT NOT NULL,
            day_bucket TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS ix_caps_events_day ON caps_events(day_bucket);
        CREATE INDEX IF NOT EXISTS ix_caps_events_type ON caps_events(event_type);
        """
    )


# ── v7 migration: resolve_ai_op_usage ledger for Resolve 21 GPU/AI ops ──────


@register_migration(7)
def _migrate_v7_resolve_ai_op_usage(conn: sqlite3.Connection) -> None:
    """Ledger for Resolve-local AI ops (audio classification, IntelliSearch,
    slate, motion-deblur, speech generation).

    These run on Resolve's own GPU/AI engine and do NOT consume the Claude-side
    analysis token budget tracked in `analysis_token_usage`, so they get their
    own ledger. The value is the wall-clock + file/byte accounting for the two
    media-creating ops (remove_motion_blur, generate_speech). `op_class` is
    'analysis' (no media produced) or 'render' (new media file written).
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS resolve_ai_op_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op TEXT NOT NULL,
            op_class TEXT NOT NULL DEFAULT 'analysis',
            clip_id TEXT,
            session_id TEXT,
            success INTEGER NOT NULL DEFAULT 0,
            wall_clock_ms INTEGER NOT NULL DEFAULT 0,
            output_path TEXT,
            output_bytes INTEGER,
            extra_required TEXT,
            error TEXT,
            occurred_at TEXT NOT NULL,
            day_bucket TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS ix_resolve_ai_op_usage_op
            ON resolve_ai_op_usage(op);
        CREATE INDEX IF NOT EXISTS ix_resolve_ai_op_usage_session
            ON resolve_ai_op_usage(session_id);
        CREATE INDEX IF NOT EXISTS ix_resolve_ai_op_usage_day
            ON resolve_ai_op_usage(day_bucket);
        """
    )


@register_migration(8)
def _migrate_v8_actor_identity(conn: sqlite3.Connection) -> None:
    """Instance-level actor provenance (design decision 2026-06-09).

    Stamps which process kind performed an op — "<instance>:<pid>" where
    instance is stdio / network-sse / network-http / control-panel /
    batch-cli. Complements `initiator` (auto vs manual) on the versioning
    tables: initiator says WHY a row exists, actor says WHO wrote it.
    """
    for table in ("resolve_ai_op_usage", "brain_edits", "timeline_versions"):
        if not _column_exists(conn, table, "actor"):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN actor TEXT")


@register_migration(5)
def _migrate_v5_analysis_token_usage(conn: sqlite3.Connection) -> None:
    """Track real vendor token + frame upload usage so caps can enforce budgets.

    `scope` is 'clip' | 'job' | 'session' | 'global'. `scope_key` is the entity
    id within that scope (clip_id, job_id, session_id, or empty for global).
    `day_bucket` (YYYY-MM-DD) is indexed for fast per-day rollup queries.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS analysis_token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            scope_key TEXT,
            vision_tokens INTEGER NOT NULL DEFAULT 0,
            transcription_tokens INTEGER NOT NULL DEFAULT 0,
            frames_uploaded INTEGER NOT NULL DEFAULT 0,
            wall_clock_ms INTEGER NOT NULL DEFAULT 0,
            preset_at_call TEXT,
            occurred_at TEXT NOT NULL,
            day_bucket TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS ix_analysis_token_usage_scope
            ON analysis_token_usage(scope, scope_key);
        CREATE INDEX IF NOT EXISTS ix_analysis_token_usage_day
            ON analysis_token_usage(day_bucket);
        """
    )


@register_migration(9)
def _migrate_v9_analysis_core(conn: sqlite3.Connection) -> None:
    """C1 — DB-canonical clip analysis (Phase A of the analysis/edit-engine program).

    The DB becomes the source of truth for clip analysis; analysis.json becomes
    a derived export written in lockstep. Shape is hybrid: a canonical
    full-report blob per clip (`analysis_reports`) plus normalized tables for
    what downstream phases query (shots, subjective fields with per-field
    provenance, transcript segments, sampled frames, QC observations).
    Computed layers (technical/motion/cuts/audio) stay inside the blob — they
    re-derive cleanly from source media and nothing queries them row-wise.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS clips (
            clip_uuid TEXT PRIMARY KEY,          -- rename-stable canonical hash (12-hex)
            clip_dir TEXT,                       -- report folder name under clips/
            resolve_clip_id TEXT,
            media_id TEXT,
            clip_name TEXT,
            file_path TEXT,
            bin_path TEXT,
            duration_seconds REAL,
            fps REAL,
            resolution TEXT,
            media_type TEXT,
            summary TEXT,
            overall_motion_level TEXT,
            cut_count INTEGER,
            shot_count INTEGER,
            analysis_version TEXT,
            depth TEXT,
            signature_hash TEXT,
            analyzed_at TEXT,
            vision_status TEXT,
            vision_committed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS ix_clips_clip_name ON clips(clip_name);
        CREATE INDEX IF NOT EXISTS ix_clips_file_path ON clips(file_path);

        -- Every stable id a clip is known by (legacy hashes, clip_id, media_id,
        -- folder hash, normalized file path) → clip_uuid. Lookup table only.
        CREATE TABLE IF NOT EXISTS clip_aliases (
            alias TEXT NOT NULL,
            clip_uuid TEXT NOT NULL,
            kind TEXT,
            PRIMARY KEY (alias, clip_uuid)
        );

        CREATE INDEX IF NOT EXISTS ix_clip_aliases_clip ON clip_aliases(clip_uuid);

        -- Canonical full analysis payload. analysis.json is exported FROM this.
        CREATE TABLE IF NOT EXISTS analysis_reports (
            clip_uuid TEXT PRIMARY KEY,
            report_json TEXT NOT NULL,
            signature_hash TEXT,
            analyzed_at TEXT,
            written_at TEXT NOT NULL,
            FOREIGN KEY (clip_uuid) REFERENCES clips(clip_uuid) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS shots (
            shot_uuid TEXT PRIMARY KEY,          -- short_hash(clip_uuid + rounded time region)
            clip_uuid TEXT NOT NULL,
            shot_index INTEGER NOT NULL,
            time_seconds_start REAL,
            time_seconds_end REAL,
            description TEXT,
            qc_flags_json TEXT,
            frame_indices_json TEXT,
            extra_json TEXT,                     -- forward-compat: any other shot keys
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(clip_uuid, shot_index),
            FOREIGN KEY (clip_uuid) REFERENCES clips(clip_uuid) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS ix_shots_clip ON shots(clip_uuid, shot_index);

        -- Per-field provenance for subjective (vision/human) values.
        -- Current value = the row with superseded_at IS NULL.
        CREATE TABLE IF NOT EXISTS subjective_fields (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL CHECK(entity_type IN ('clip', 'shot')),
            entity_uuid TEXT NOT NULL,
            field_path TEXT NOT NULL,
            value_json TEXT NOT NULL,
            confidence TEXT,
            source TEXT NOT NULL,                -- 'vision_v0.2' | 'human' | ...
            source_model TEXT,
            author TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            superseded_at TEXT
        );

        CREATE INDEX IF NOT EXISTS ix_sf_entity
            ON subjective_fields(entity_type, entity_uuid, field_path);
        CREATE INDEX IF NOT EXISTS ix_sf_current
            ON subjective_fields(entity_type, entity_uuid, field_path)
            WHERE superseded_at IS NULL;

        CREATE TABLE IF NOT EXISTS field_changelog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_uuid TEXT NOT NULL,
            field_path TEXT NOT NULL,
            previous_value_json TEXT,
            new_value_json TEXT NOT NULL,
            previous_source TEXT,
            new_source TEXT NOT NULL,
            previous_author TEXT,
            new_author TEXT NOT NULL,
            change_reason TEXT,
            timestamp TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS ix_changelog_entity
            ON field_changelog(entity_type, entity_uuid, timestamp);

        CREATE TABLE IF NOT EXISTS transcript_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clip_uuid TEXT NOT NULL,
            segment_index INTEGER NOT NULL,
            start_seconds REAL,
            end_seconds REAL,
            text TEXT,
            speaker_id TEXT,
            UNIQUE(clip_uuid, segment_index),
            FOREIGN KEY (clip_uuid) REFERENCES clips(clip_uuid) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS ix_transcript_segments_clip
            ON transcript_segments(clip_uuid, start_seconds);

        CREATE TABLE IF NOT EXISTS frames (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clip_uuid TEXT NOT NULL,
            shot_uuid TEXT,
            frame_index INTEGER NOT NULL,
            time_seconds REAL,
            frame_path TEXT,
            selection_reason TEXT,
            motion_peak INTEGER NOT NULL DEFAULT 0,
            UNIQUE(clip_uuid, frame_index),
            FOREIGN KEY (clip_uuid) REFERENCES clips(clip_uuid) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS ix_frames_clip ON frames(clip_uuid, frame_index);
        CREATE INDEX IF NOT EXISTS ix_frames_shot ON frames(shot_uuid);

        CREATE TABLE IF NOT EXISTS qc_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clip_uuid TEXT NOT NULL,
            shot_uuid TEXT,
            observation_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            message TEXT NOT NULL,
            related_shot_indices_json TEXT,
            confidence TEXT,
            source TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0,
            resolved_by TEXT,
            resolved_at TEXT,
            resolution_note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (clip_uuid) REFERENCES clips(clip_uuid) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS ix_qc_clip ON qc_observations(clip_uuid);
        CREATE INDEX IF NOT EXISTS ix_qc_unresolved
            ON qc_observations(clip_uuid, resolved) WHERE resolved = 0;
        """
    )


@register_migration(10)
def _migrate_v10_embeddings(conn: sqlite3.Connection) -> None:
    """C3 — embeddings for similarity search (Phase C of the analysis program).

    One row per (entity, kind, model). Vectors are float32 BLOBs; similarity
    is brute-force cosine in the app layer (thousands of rows, not millions).
    `content_hash` fingerprints the embedded content so re-runs only re-embed
    entities whose text/frames changed.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL CHECK(entity_type IN ('clip', 'shot', 'frame', 'segment')),
            entity_uuid TEXT NOT NULL,
            embedding_kind TEXT NOT NULL,        -- 'text' | 'visual'
            model_name TEXT NOT NULL,
            dimension INTEGER NOT NULL,
            vector BLOB NOT NULL,
            content_hash TEXT,
            computed_at TEXT NOT NULL,
            UNIQUE(entity_type, entity_uuid, embedding_kind, model_name)
        );

        CREATE INDEX IF NOT EXISTS ix_embeddings_kind
            ON embeddings(embedding_kind, model_name);
        CREATE INDEX IF NOT EXISTS ix_embeddings_entity
            ON embeddings(entity_type, entity_uuid);
        """
    )


@register_migration(11)
def _migrate_v11_entities(conn: sqlite3.Connection) -> None:
    """C5 — cross-clip entities (Phase D of the analysis program).

    `entities` rows start as provisional clusters over the v10 visual
    embeddings (source='clustering', label NULL) and are enriched by one
    host-vision call per cluster representative (source='vision_entity_v1')
    or by humans. `entity_appearances` records every frame an entity was
    seen in, with the clip/shot derivation and the match similarity.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS entities (
            entity_uuid TEXT PRIMARY KEY,
            kind TEXT,                            -- person|place|object|unknown
            label TEXT,
            description TEXT,
            confidence TEXT,
            source TEXT NOT NULL,
            representative_frame_ref TEXT,        -- 'clip_uuid:frame_index'
            representative_frame_path TEXT,
            cluster_size INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS ix_entities_kind ON entities(kind);

        CREATE TABLE IF NOT EXISTS entity_appearances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_uuid TEXT NOT NULL,
            clip_uuid TEXT NOT NULL,
            shot_uuid TEXT,
            frame_ref TEXT NOT NULL,              -- 'clip_uuid:frame_index'
            similarity REAL,
            UNIQUE(entity_uuid, frame_ref),
            FOREIGN KEY (entity_uuid) REFERENCES entities(entity_uuid) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS ix_entity_appearances_entity
            ON entity_appearances(entity_uuid);
        CREATE INDEX IF NOT EXISTS ix_entity_appearances_clip
            ON entity_appearances(clip_uuid);
        """
    )


@register_migration(12)
def _migrate_v12_shot_relationships(conn: sqlite3.Connection) -> None:
    """Cross-shot relationships (spec §4 — pattern recognition only).

    Three types: same_setup_as / alt_take_of (symmetric — stored once with
    the canonically-ordered pair) and continues_from (directional — the
    SOURCE shot continues from the TARGET shot, i.e. target precedes source).
    Rows are append-only with supersede semantics: current rows have
    superseded_at IS NULL.
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS shot_relationships (
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

        CREATE INDEX IF NOT EXISTS idx_relationships_source
            ON shot_relationships(source_shot_uuid) WHERE superseded_at IS NULL;
        CREATE INDEX IF NOT EXISTS idx_relationships_target
            ON shot_relationships(target_shot_uuid) WHERE superseded_at IS NULL;
        CREATE INDEX IF NOT EXISTS idx_relationships_type
            ON shot_relationships(relationship_type) WHERE superseded_at IS NULL;
        """
    )


def latest_version(conn: sqlite3.Connection, timeline_name: str) -> Optional[int]:
    """Return the highest archived version number for `timeline_name`, or None."""
    row = conn.execute(
        "SELECT MAX(version) AS v FROM timeline_versions WHERE timeline_name = ?",
        (timeline_name,),
    ).fetchone()
    if row is None or row["v"] is None:
        return None
    return int(row["v"])


def run_archived_for_run(conn: sqlite3.Connection, timeline_name: str, analysis_run_id: str) -> bool:
    """Has an archive already happened for this (timeline, run) pair?"""
    if not analysis_run_id:
        return False
    row = conn.execute(
        "SELECT 1 FROM timeline_versions WHERE timeline_name = ? AND analysis_run_id = ? LIMIT 1",
        (timeline_name, analysis_run_id),
    ).fetchone()
    return row is not None
