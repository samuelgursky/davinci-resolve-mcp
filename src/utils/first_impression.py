"""The first-impression log — the one perception that cannot be recovered.

The editor is the only person who ever gets to be a first-time audience for the
material, and that perception is destroyed by the second viewing. The classical
practice is to record reactions during the first pass through dailies for
exactly this reason: by the tenth screening an editor knows the film too well to
feel what a stranger will feel, and no amount of later analysis restores it.

Everything else in this codebase measures something. This measures nothing. It
is craft infrastructure: capture the reaction while it is still available, then
**make it immutable**, so that an editor eight weeks in — who now finds the slow
opening perfectly paced because they have seen it ninety times — can be
confronted with what they thought the first time.

## The lock is the entire feature

An editable first-impression log is worthless. The failure mode is not malice,
it is the completely natural act of revising a note that "no longer seems
right" — which is precisely the moment the note is most valuable, because what
changed is the reader, not the film. So `record` refuses on a locked log and
says why.

## Deliberately not built

- **No schema.** Reactions are free text. A dailies notation is personal
  shorthand; the notation is the editor's, the capture is the tool.
- **No sentiment analysis.** Scoring "confused here" as 0.3-negative destroys
  the only thing it carried. The words are the artifact.
- **No inference about whether a note was addressed.** The diff reports whether
  a later pass has anything near the same timecode. That is *revisited*, not
  *fixed*, and it says so.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Mapping, Optional

LOG_DIRNAME = "first_impressions"

#: Two reactions within this many seconds are about the same moment.
PROXIMITY_SECONDS = 5.0

_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


class LogLocked(Exception):
    """Raised on any attempt to change a sealed log. The lock is the feature."""


def _log_dir(project_root: str) -> str:
    return os.path.join(project_root, LOG_DIRNAME)


def _log_path(project_root: str, log_id: str) -> str:
    return os.path.join(_log_dir(project_root), f"{_SAFE.sub('_', log_id)}.json")


def start_pass(project_root: str, *, timeline_name: str, log_id: str,
               viewer: Optional[str] = None) -> Dict[str, Any]:
    """Open a log for a first viewing. Fails rather than overwriting an existing one."""
    path = _log_path(project_root, log_id)
    if os.path.exists(path):
        return {
            "success": False,
            "error": f"a log named {log_id!r} already exists",
            "remediation": "Use a new log_id. A first impression happens once.",
        }
    os.makedirs(_log_dir(project_root), exist_ok=True)
    log = {
        "log_id": log_id,
        "timeline_name": timeline_name,
        "viewer": viewer,
        "locked": False,
        "entries": [],
    }
    _write(path, log)
    return {"success": True, "log": log,
            "note": "Log open. Record reactions as you watch, then lock it. "
                    "Once locked it cannot be edited — that is the point."}


def record(project_root: str, *, log_id: str, time_seconds: float,
           text: str) -> Dict[str, Any]:
    """Append a reaction. Refuses on a locked log."""
    path = _log_path(project_root, log_id)
    log = _read(path)
    if log is None:
        return {"success": False, "error": f"no log named {log_id!r}"}
    if log.get("locked"):
        raise LogLocked(
            f"log {log_id!r} is locked and cannot be added to. A first impression "
            "that can be revised after the fact is worthless — what changed by then "
            "is the viewer, not the film. Start a new log for a later pass."
        )
    if not str(text).strip():
        return {"success": False, "error": "an empty reaction is not a reaction"}
    log["entries"].append({
        "time_seconds": round(float(time_seconds), 3),
        "text": str(text).strip(),
    })
    log["entries"].sort(key=lambda e: e["time_seconds"])
    _write(path, log)
    return {"success": True, "entry_count": len(log["entries"])}


def lock(project_root: str, *, log_id: str) -> Dict[str, Any]:
    """Seal a log. Irreversible by design; there is no unlock function."""
    path = _log_path(project_root, log_id)
    log = _read(path)
    if log is None:
        return {"success": False, "error": f"no log named {log_id!r}"}
    if log.get("locked"):
        return {"success": True, "already_locked": True, "log": log}
    log["locked"] = True
    _write(path, log)
    return {
        "success": True,
        "log": log,
        "note": (
            f"Sealed with {len(log['entries'])} reactions. There is deliberately no "
            "unlock — the value of this record is precisely that a later, "
            "better-informed self cannot talk it out of what it noticed."
        ),
    }


def load(project_root: str, *, log_id: str) -> Optional[Dict[str, Any]]:
    return _read(_log_path(project_root, log_id))


def list_logs(project_root: str) -> List[Dict[str, Any]]:
    directory = _log_dir(project_root)
    if not os.path.isdir(directory):
        return []
    out = []
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        log = _read(os.path.join(directory, name))
        if log:
            out.append({
                "log_id": log.get("log_id"),
                "timeline_name": log.get("timeline_name"),
                "locked": bool(log.get("locked")),
                "entry_count": len(log.get("entries") or []),
            })
    return out


def diff(first: Mapping[str, Any], later: Mapping[str, Any], *,
         proximity_seconds: float = PROXIMITY_SECONDS) -> Dict[str, Any]:
    """Compare a first-impression log against a later pass.

    Reports whether each first reaction was **revisited** — whether the later
    pass said anything near the same moment. It does **not** claim anything was
    fixed: a note with no counterpart may have been addressed and forgotten, or
    simply never looked at again. Those are different and this cannot tell them
    apart, so it does not pretend to.
    """
    first_entries = list(first.get("entries") or [])
    later_entries = list(later.get("entries") or [])
    revisited, not_revisited = [], []
    for entry in first_entries:
        near = [
            l for l in later_entries
            if abs(float(l["time_seconds"]) - float(entry["time_seconds"])) <= proximity_seconds
        ]
        (revisited if near else not_revisited).append({
            **entry,
            "later_notes": [n["text"] for n in near],
        })
    new_concerns = [
        entry for entry in later_entries
        if not any(
            abs(float(entry["time_seconds"]) - float(f["time_seconds"])) <= proximity_seconds
            for f in first_entries
        )
    ]
    return {
        "first_log_id": first.get("log_id"),
        "later_log_id": later.get("log_id"),
        "first_reaction_count": len(first_entries),
        "revisited": revisited,
        "not_revisited": not_revisited,
        "new_in_later_pass": new_concerns,
        "note": (
            f"{len(revisited)} of {len(first_entries)} first reactions were revisited in "
            f"the later pass; {len(not_revisited)} were not. **Not revisited does NOT "
            "mean not fixed** — it means nobody wrote anything there the second time, "
            "which could be because it was solved or because it stopped being visible "
            "once the film became familiar. That second possibility is the reason this "
            "log exists."
        ),
    }


def _read(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _write(path: str, log: Mapping[str, Any]) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(log, handle, indent=2)
    os.replace(tmp, path)
