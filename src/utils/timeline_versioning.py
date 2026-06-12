"""Timeline versioning + version-on-mutate hook (C6).

Mechanics:

1. **archive_current_timeline** — duplicate the current working timeline, move the
   duplicate into the `Archive` bin (created on first use), record the row in
   `timeline_versions`. The *original* keeps its name; the *duplicate* gets a
   `_archived_v0N` suffix. (We don't rename the working timeline because Resolve
   loses playhead + UI state on rename, which is hostile to interactive work.)
2. **ensure_versioned_before_mutation** — called by the destructive-op hook in
   `src/server.py`. Idempotent within an `analysis_run_id`: if this run already
   archived the current timeline, no-op. Otherwise, archive it.
3. **list_timeline_versions** — version chain for a timeline name.
4. **rollback_to_version** — restore an archived version back to the working pool
   under the original name. Archives the current working state first (rollback
   itself is a versioned op).

The Resolve API surface used here is intentionally narrow:
`Project.GetCurrentTimeline`, `Project.SetCurrentTimeline`, `MediaPool.GetRootFolder`,
`MediaPool.AddSubFolder`, `MediaPool.SetCurrentFolder`, `MediaPool.MoveClips`,
`Timeline.DuplicateTimeline`, `Timeline.GetName`, `Timeline.GetUniqueId`,
`MediaPool.ExportTimeline` (for `.drt` retention export). All of these are
documented stable scripting calls.
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from src.utils import actor_identity, timeline_brain_db

logger = logging.getLogger("resolve-mcp.timeline-versioning")

ARCHIVE_BIN_NAME = "Archive"
ARCHIVED_SUFFIX_PATTERN = re.compile(r"^(?P<base>.+?)(?:_archived_v(?P<v>\d{2,}))?$")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_analysis_run_id() -> str:
    """Generate a fresh analysis_run_id. Callers should pass one if they have it."""
    return f"run_{uuid.uuid4().hex[:12]}"


# ── Bin helpers ──────────────────────────────────────────────────────────────


def _find_subfolder_by_name(folder: Any, name: str) -> Optional[Any]:
    for sub in (folder.GetSubFolderList() or []):
        try:
            if sub.GetName() == name:
                return sub
        except Exception:
            continue
    return None


def _ensure_archive_bin(media_pool: Any) -> Any:
    """Return the Archive folder under the media pool root, creating if missing."""
    root = media_pool.GetRootFolder()
    if root is None:
        raise RuntimeError("Cannot resolve media pool root folder")
    existing = _find_subfolder_by_name(root, ARCHIVE_BIN_NAME)
    if existing is not None:
        return existing
    created = media_pool.AddSubFolder(root, ARCHIVE_BIN_NAME)
    if created is None:
        raise RuntimeError(f"Failed to create '{ARCHIVE_BIN_NAME}' bin")
    return created


def _archive_bin_path(media_pool: Any) -> str:
    """Human-readable path to the Archive bin (for the DB record)."""
    return f"Master/{ARCHIVE_BIN_NAME}"


# ── Timeline lookup ──────────────────────────────────────────────────────────


def _list_all_timelines(project: Any) -> List[Any]:
    count = project.GetTimelineCount()
    if count is None:
        return []
    out = []
    for i in range(1, int(count) + 1):
        tl = project.GetTimelineByIndex(i)
        if tl is not None:
            out.append(tl)
    return out


def _find_timeline_by_name(project: Any, name: str) -> Optional[Any]:
    for tl in _list_all_timelines(project):
        try:
            if tl.GetName() == name:
                return tl
        except Exception:
            continue
    return None


# ── Public API ───────────────────────────────────────────────────────────────


def archive_current_timeline(
    *,
    resolve: Any,
    project: Any,
    project_root: str,
    reason: Optional[str] = None,
    analysis_run_id: Optional[str] = None,
    timeline: Any = None,
    initiator: Optional[str] = None,
    auto_save: bool = False,
) -> Dict[str, Any]:
    """Duplicate the current timeline and move the duplicate to the Archive bin.

    `timeline` defaults to the current timeline. Returns a dict with the new
    version number and the archived timeline's name + DB row id.
    """
    tl = timeline if timeline is not None else project.GetCurrentTimeline()
    if tl is None:
        return {"success": False, "error": "No current timeline"}

    media_pool = project.GetMediaPool()
    if media_pool is None:
        return {"success": False, "error": "Cannot access media pool"}

    working_name = tl.GetName()
    conn = timeline_brain_db.connect(project_root)

    next_version = (timeline_brain_db.latest_version(conn, working_name) or 0) + 1
    archived_name = f"{working_name}_archived_v{next_version:02d}"

    # Resolve duplication must happen on the live timeline; pin current folder
    # to Archive bin first so the duplicate lands there directly.
    archive_bin = _ensure_archive_bin(media_pool)
    if not media_pool.SetCurrentFolder(archive_bin):
        return {"success": False, "error": "Failed to set Archive as current bin"}

    dup = tl.DuplicateTimeline(archived_name)
    if dup is None:
        return {"success": False, "error": f"DuplicateTimeline('{archived_name}') failed"}

    # DuplicateTimeline drops the duplicate in the *current* folder (Archive),
    # but it also switches Resolve's current timeline to the duplicate. Restore
    # the working timeline as the active one so downstream mutation hits it.
    project.SetCurrentTimeline(tl)

    with timeline_brain_db.transaction(project_root) as txn:
        cursor = txn.execute(
            """
            INSERT INTO timeline_versions(
                timeline_name, version, created_at, analysis_run_id,
                archived_timeline_name, archived_bin_path, reason, initiator, actor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                working_name,
                next_version,
                _now_iso(),
                analysis_run_id,
                archived_name,
                _archive_bin_path(media_pool),
                reason,
                initiator,
                actor_identity.actor_string(),
            ),
        )
        row_id = cursor.lastrowid

    # Structural snapshot — record every clip on the working timeline so a diff
    # between v04 and v05 answers "which clips changed?" not just "how did the
    # metric move?". This is the substrate the brain reads to learn what its
    # edits actually did.
    snapshot_count = 0
    try:
        snapshot_count = _snapshot_timeline_clip_usage(
            project_root=project_root,
            timeline=tl,
            timeline_name=working_name,
            timeline_version=next_version,
            analysis_run_id=analysis_run_id,
        )
    except Exception as exc:
        logger.warning(
            "structural snapshot failed for '%s' v%d (non-fatal): %s",
            working_name, next_version, exc,
        )

    # Thumbnail capture — visually identifies a version in the History view
    # without having to switch into Resolve. Cheap (Resolve's already
    # generating thumbnails), and the visual diff is the most-loved UX.
    thumbnail_path: Optional[str] = None
    try:
        thumbnail_path = _capture_version_thumbnail(
            project_root=project_root,
            timeline=tl,
            timeline_name=working_name,
            timeline_version=next_version,
        )
        if thumbnail_path:
            with timeline_brain_db.transaction(project_root) as txn:
                txn.execute(
                    "UPDATE timeline_versions SET thumbnail_path = ? WHERE id = ?",
                    (thumbnail_path, row_id),
                )
    except Exception as exc:
        logger.warning("thumbnail capture failed for v%d (non-fatal): %s", next_version, exc)

    saved = False
    if auto_save:
        try:
            saved = bool(project.SaveProject())
        except Exception as exc:
            logger.warning("auto-save after archive failed (non-fatal): %s", exc)

    logger.info(
        "Archived timeline '%s' as '%s' (v%d, run=%s, snapshot=%d clips, saved=%s, reason=%s)",
        working_name, archived_name, next_version, analysis_run_id, snapshot_count, saved, reason,
    )

    return {
        "success": True,
        "timeline_name": working_name,
        "archived_timeline_name": archived_name,
        "version": next_version,
        "archive_bin": ARCHIVE_BIN_NAME,
        "row_id": row_id,
        "analysis_run_id": analysis_run_id,
        "snapshot_clip_count": snapshot_count,
        "project_saved": saved,
    }


# ── Structural snapshot ──────────────────────────────────────────────────────


def _resolve_media_pool_item_id(item: Any) -> Optional[str]:
    """Best-effort extraction of the media-pool source ID from a timeline item.

    Resolve exposes `GetMediaPoolItem()` on most timeline-item handles; fall
    back to GetUniqueId() if the source isn't reachable (e.g. compound clip).
    """
    try:
        mpi = item.GetMediaPoolItem()
        if mpi is not None and hasattr(mpi, "GetUniqueId"):
            return str(mpi.GetUniqueId())
    except Exception:
        pass
    try:
        return str(item.GetUniqueId()) if hasattr(item, "GetUniqueId") else None
    except Exception:
        return None


def capture_timeline_clip_usage(timeline: Any) -> List[Dict[str, Any]]:
    """Walk every track/item on a LIVE timeline into structural-usage rows
    (no DB writes). Shared by the version snapshot writer and the cross-name
    live diff."""
    rows: List[Dict[str, Any]] = []
    for tt in ("video", "audio", "subtitle"):
        try:
            count = timeline.GetTrackCount(tt)
        except Exception:
            continue
        if not count:
            continue
        for ti in range(1, int(count) + 1):
            try:
                items = timeline.GetItemListInTrack(tt, ti) or []
            except Exception:
                continue
            for item in items:
                mpi_id = _resolve_media_pool_item_id(item)
                if not mpi_id:
                    continue
                try:
                    in_frame = int(item.GetStart())
                    out_frame = int(item.GetEnd())
                except Exception:
                    continue
                rows.append({
                    "media_pool_item_id": mpi_id,
                    "track_type": tt,
                    "track_index": ti,
                    "in_frame": in_frame,
                    "out_frame": out_frame,
                })
    return rows


def _snapshot_timeline_clip_usage(
    *,
    project_root: str,
    timeline: Any,
    timeline_name: str,
    timeline_version: int,
    analysis_run_id: Optional[str],
) -> int:
    """Walk every track/item on the timeline and INSERT a row per clip.

    Returns the number of rows written. Safe to call repeatedly for the same
    (timeline, version) — version is part of the row, not unique, so diffs
    between two versions are a SQL JOIN on media_pool_item_id.
    """
    observed_at = _now_iso()
    rows: List[Tuple[str, str, int, str, int, int, int, Optional[str], str]] = [
        (
            usage["media_pool_item_id"], timeline_name, timeline_version,
            usage["track_type"], usage["track_index"],
            usage["in_frame"], usage["out_frame"], analysis_run_id, observed_at,
        )
        for usage in capture_timeline_clip_usage(timeline)
    ]

    if not rows:
        return 0

    with timeline_brain_db.transaction(project_root) as txn:
        txn.executemany(
            """
            INSERT INTO timeline_clip_usage(
                media_pool_item_id, timeline_name, timeline_version,
                track_type, track_index, in_frame, out_frame,
                analysis_run_id_at_placement, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
    return len(rows)


def diff_versions(
    *,
    project_root: str,
    timeline_name: str,
    from_version: int,
    to_version: int,
) -> Dict[str, Any]:
    """Compare two structural snapshots — which clips were added, removed, moved?

    Returns {added: [...], removed: [...], moved: [...]} where each entry is
    (media_pool_item_id, track_type, track_index, in_frame, out_frame).
    """
    conn = timeline_brain_db.connect(project_root)

    def _snapshot(version: int) -> List[Dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT media_pool_item_id, track_type, track_index, in_frame, out_frame
            FROM timeline_clip_usage
            WHERE timeline_name = ? AND timeline_version = ?
            ORDER BY track_type, track_index, in_frame
            """,
            (timeline_name, version),
        ).fetchall()
        return [dict(r) for r in rows]

    before = _snapshot(from_version)
    after = _snapshot(to_version)
    return {
        "from_version": from_version,
        "to_version": to_version,
        **compare_usage_snapshots(before, after),
    }


def compare_usage_snapshots(
    before: List[Dict[str, Any]], after: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """added/removed/moved/trimmed between two structural-usage snapshots.

    Position key: (media id, track type, track index, in_frame). Same key in
    both snapshots = same placement; a differing out_frame on that same key is
    a *trim*. A differing track/in_frame for the same media id is a *move*.
    """
    def _key(row: Dict[str, Any]) -> Tuple[str, str, int, int]:
        return (row["media_pool_item_id"], row["track_type"], row["track_index"], row["in_frame"])

    before_by_key = {_key(r): r for r in before}
    after_by_key = {_key(r): r for r in after}
    before_keys = set(before_by_key)
    after_keys = set(after_by_key)

    added = [r for r in after if _key(r) not in before_keys]
    removed = [r for r in before if _key(r) not in after_keys]

    # Trimmed: same placement key in both, but the out_frame differs.
    trimmed: List[Dict[str, Any]] = []
    for key in before_keys & after_keys:
        if before_by_key[key]["out_frame"] != after_by_key[key]["out_frame"]:
            row = dict(after_by_key[key])
            row["out_frame_before"] = before_by_key[key]["out_frame"]
            trimmed.append(row)

    # Moved: same media id present on both sides but at a different placement
    # (so it shows up in both `added` and `removed` above). Report it once.
    before_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for r in before:
        before_by_id.setdefault(r["media_pool_item_id"], []).append(r)
    moved: List[Dict[str, Any]] = []
    for r in added:
        prevs = before_by_id.get(r["media_pool_item_id"])
        if prevs and any(_key(p) != _key(r) for p in prevs):
            moved.append(r)

    return {
        "added": added,
        "removed": removed,
        "moved": moved,
        "trimmed": trimmed,
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "moved": len(moved),
            "trimmed": len(trimmed),
            "before_clip_count": len(before),
            "after_clip_count": len(after),
        },
    }


def diff_timelines(
    *,
    project: Any,
    from_timeline: str,
    to_timeline: str,
) -> Dict[str, Any]:
    """Structural diff between two LIVE timelines by name (read-only).

    Unlike diff_versions this needs no archived snapshots and works across
    timeline NAMES — built for edit-engine variants (tighten/selects produce
    new-name timelines that have no shared version chain with their source).
    For moved/trimmed to mean anything the timelines should share source
    clips; for unrelated timelines everything reports as added/removed.
    """
    from_tl = _find_timeline_by_name(project, from_timeline)
    if from_tl is None:
        return {"success": False, "error": f"Timeline '{from_timeline}' not found"}
    to_tl = _find_timeline_by_name(project, to_timeline)
    if to_tl is None:
        return {"success": False, "error": f"Timeline '{to_timeline}' not found"}
    before = capture_timeline_clip_usage(from_tl)
    after = capture_timeline_clip_usage(to_tl)
    return {
        "success": True,
        "from_timeline": from_timeline,
        "to_timeline": to_timeline,
        **compare_usage_snapshots(before, after),
    }


def ensure_versioned_before_mutation(
    *,
    resolve: Any,
    project: Any,
    project_root: str,
    analysis_run_id: str,
    reason: Optional[str] = None,
    initiator: Optional[str] = None,
    auto_save: bool = False,
) -> Dict[str, Any]:
    """Idempotent guard called before any destructive timeline op.

    If this `analysis_run_id` has not yet archived the current timeline, archive
    it. If it has, no-op. Returns a dict with `archived: bool` and the version
    info if an archive happened.
    """
    tl = project.GetCurrentTimeline()
    if tl is None:
        return {"archived": False, "skipped_reason": "no_current_timeline"}

    working_name = tl.GetName()
    conn = timeline_brain_db.connect(project_root)
    if timeline_brain_db.run_archived_for_run(conn, working_name, analysis_run_id):
        return {"archived": False, "skipped_reason": "already_archived_for_run"}

    return {
        "archived": True,
        **archive_current_timeline(
            resolve=resolve,
            project=project,
            project_root=project_root,
            reason=reason or f"version-on-mutate ({analysis_run_id})",
            analysis_run_id=analysis_run_id,
            timeline=tl,
            initiator=initiator,
            auto_save=auto_save,
        ),
    }


def list_timeline_versions(
    *,
    project_root: str,
    timeline_name: str,
) -> List[Dict[str, Any]]:
    """Version chain for `timeline_name`, oldest first."""
    conn = timeline_brain_db.connect(project_root)
    rows = conn.execute(
        """
        SELECT id, timeline_name, version, created_at, analysis_run_id,
               archived_timeline_name, archived_bin_path, drt_export_path, reason
        FROM timeline_versions
        WHERE timeline_name = ?
        ORDER BY version ASC
        """,
        (timeline_name,),
    ).fetchall()
    return [dict(r) for r in rows]


def rollback_to_version(
    *,
    resolve: Any,
    project: Any,
    project_root: str,
    timeline_name: str,
    version: int,
    analysis_run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Restore `timeline_name` to an archived `version`.

    Steps:
    1. Archive the current working state (rollback is itself a versioned op).
    2. Locate the archived timeline (by name in the Archive bin OR re-import from
       `.drt` if it was retention-collapsed).
    3. Duplicate the archived timeline back to the project root, name it
       `<timeline_name>_rolled_back_<HHMMSS>` to avoid collision. The caller can
       rename via `timeline.set_name` if desired.
    """
    run = analysis_run_id or new_analysis_run_id()
    archive_result = ensure_versioned_before_mutation(
        resolve=resolve,
        project=project,
        project_root=project_root,
        analysis_run_id=run,
        reason=f"pre-rollback to v{version:02d}",
    )

    conn = timeline_brain_db.connect(project_root)
    row = conn.execute(
        """
        SELECT archived_timeline_name, drt_export_path
        FROM timeline_versions
        WHERE timeline_name = ? AND version = ?
        """,
        (timeline_name, version),
    ).fetchone()
    if row is None:
        return {"success": False, "error": f"No version v{version} for '{timeline_name}'"}

    archived_name = row["archived_timeline_name"]
    drt_path = row["drt_export_path"]

    media_pool = project.GetMediaPool()
    if media_pool is None:
        return {"success": False, "error": "Cannot access media pool"}

    archived_tl = _find_timeline_by_name(project, archived_name)
    if archived_tl is None and drt_path and os.path.isfile(drt_path):
        # Retention-collapsed: re-import the .drt back into the project.
        imported = media_pool.ImportTimelineFromFile(drt_path)
        if imported is None:
            return {"success": False, "error": f"Failed to re-import {drt_path}"}
        archived_tl = imported
    if archived_tl is None:
        return {"success": False, "error": f"Archived timeline '{archived_name}' not found"}

    timestamp = time.strftime("%H%M%S", time.gmtime())
    restored_name = f"{timeline_name}_rolled_back_{timestamp}"
    restored = archived_tl.DuplicateTimeline(restored_name)
    if restored is None:
        return {"success": False, "error": f"DuplicateTimeline('{restored_name}') failed"}

    project.SetCurrentTimeline(restored)

    return {
        "success": True,
        "rolled_back_from_version": version,
        "restored_timeline_name": restored_name,
        "archive_of_previous": archive_result,
        "analysis_run_id": run,
    }


# ── Retention ─────────────────────────────────────────────────────────────────


def prune_archived_versions(
    *,
    resolve: Any,
    project: Any,
    project_root: str,
    timeline_name: str,
    keep_n: int = 10,
) -> Dict[str, Any]:
    """Keep the most recent `keep_n` archived versions live in the Archive bin.

    Older versions are exported to `<project>/_soul/timeline_versions/<timeline>/`
    as `.drt` files and then removed from the bin. The DB row is preserved and
    its `drt_export_path` is populated, so rollback can re-import.
    """
    if keep_n < 1:
        keep_n = 1

    conn = timeline_brain_db.connect(project_root)
    rows = conn.execute(
        """
        SELECT id, version, archived_timeline_name, drt_export_path
        FROM timeline_versions
        WHERE timeline_name = ?
        ORDER BY version DESC
        """,
        (timeline_name,),
    ).fetchall()

    if len(rows) <= keep_n:
        return {"success": True, "pruned": 0, "kept": len(rows)}

    media_pool = project.GetMediaPool()
    if media_pool is None:
        return {"success": False, "error": "Cannot access media pool"}

    export_dir = os.path.join(
        project_root, "_soul", "timeline_versions", _slugify(timeline_name)
    )
    os.makedirs(export_dir, exist_ok=True)

    to_collapse = list(rows[keep_n:])
    pruned: List[Dict[str, Any]] = []
    for row in to_collapse:
        if row["drt_export_path"]:
            # Already collapsed previously — nothing to do.
            continue
        archived_name = row["archived_timeline_name"]
        tl = _find_timeline_by_name(project, archived_name)
        if tl is None:
            logger.warning("Cannot find archived timeline '%s' to collapse", archived_name)
            continue

        export_path = os.path.join(export_dir, f"{archived_name}.drt")
        # ExportType.DRT is integer 1 in the Resolve API; passing the int avoids
        # a runtime dependency on the constant lookup.
        EXPORT_DRT = 1
        exported = tl.Export(export_path, EXPORT_DRT)
        if not exported:
            logger.warning("Export(%s) returned False", export_path)
            continue

        # Now remove the timeline from the bin. Resolve has no DeleteTimeline on
        # a single timeline handle; project.DeleteTimelines() expects a list.
        try:
            removed = project.DeleteTimelines([tl])
        except Exception as exc:
            logger.warning("DeleteTimelines failed for '%s': %s", archived_name, exc)
            removed = False

        with timeline_brain_db.transaction(project_root) as txn:
            txn.execute(
                "UPDATE timeline_versions SET drt_export_path = ? WHERE id = ?",
                (export_path, row["id"]),
            )

        pruned.append({
            "version": row["version"],
            "archived_name": archived_name,
            "exported_to": export_path,
            "deleted_from_bin": bool(removed),
        })

    return {"success": True, "pruned": len(pruned), "kept": keep_n, "details": pruned}


def _slugify(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "timeline"


# ── Thumbnail capture ───────────────────────────────────────────────────────


def _capture_version_thumbnail(
    *,
    project_root: str,
    timeline: Any,
    timeline_name: str,
    timeline_version: int,
) -> Optional[str]:
    """Snapshot the current Color-page thumbnail to disk.

    Returns the file path, or None if Resolve can't produce a thumbnail (e.g.
    the playhead isn't on a clip, the Color page isn't active, or the
    underlying API call failed). Best-effort — never raises.
    """
    try:
        thumbnail_data = timeline.GetCurrentClipThumbnailImage()
    except Exception as exc:
        logger.debug("GetCurrentClipThumbnailImage raised: %s", exc)
        return None
    if not thumbnail_data:
        return None

    try:
        # Lazy import to avoid a circular module-load with server.py.
        from src.server import _thumbnail_data_to_png_bytes
        png_bytes = _thumbnail_data_to_png_bytes(thumbnail_data)
    except Exception as exc:
        logger.debug("thumbnail PNG conversion failed: %s", exc)
        return None

    out_dir = os.path.join(
        project_root, "_soul", "timeline_versions", _slugify(timeline_name),
    )
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"v{timeline_version:02d}.png")
    try:
        with open(out_path, "wb") as fh:
            fh.write(png_bytes)
    except OSError as exc:
        logger.debug("thumbnail write failed: %s", exc)
        return None
    return out_path
