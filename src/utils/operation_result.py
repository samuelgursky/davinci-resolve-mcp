"""A standard operation envelope over every compound tool's return value.

Agents orchestrating multi-turn edits have to answer the same three questions
after every call — did it actually happen, was it verified, and what changed —
and today each tool answers them in its own vocabulary: ``readback.missing``,
``succeeded``/``failed``, ``partial``, ``status: "confirmation_required"``.
This module normalizes those into one shape so the answer is in the same place
every time.

Adapted from the design contributed in PR #181.

**Where the envelope lives.** Its keys are namespaced under a single reserved
key rather than merged into the top level, because half of them are already
domain keys here and merging silently destroys them:

    status       22 sites — a background job's "done", a transcription's
                 "Transcribed", a confirm gate's "confirmation_required"
    operation    20 sites
    warnings     15 sites
    result        8 sites
    changes       2 sites

Flattening the envelope over those rewrites `job_status`'s "done" to "success"
(an agent polling a job then never sees it finish) and a confirm gate's
"confirmation_required" to "blocked" — renaming the very signal the envelope
exists to make unambiguous. So in the default ``dual`` mode the raw payload is
passed through **untouched** and the envelope is added under ``_operation``,
following the existing ``_versioning`` private-key convention. Nothing is
shadowed, nothing is dropped, and there is still exactly one place to look.

Modes:
  ``dual``   (default) raw payload verbatim + ``_operation``.
  ``pure``   only the envelope, domain payload nested under ``result``. Opt in
             per call with ``params={"envelope": "pure"}``, per session with
             ``setup(action="set_defaults", params={"result_envelope": "pure"})``,
             or per process with ``RESOLVE_MCP_RESULT_ENVELOPE=pure``.
  ``legacy`` no envelope at all.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("resolve-mcp.operation-result")

#: The reserved key the envelope hangs off in ``dual`` mode. Verified unused as
#: a domain key across ``src/`` — ``test_envelope_key_stays_reserved`` keeps it
#: that way, since the day a tool returns its own ``_operation`` is the day this
#: mode starts destroying payloads the way the flat one did.
ENVELOPE_KEY = "_operation"

MODES = ("dual", "pure", "legacy")
DEFAULT_MODE = "dual"


def _clean_mode(mode: Any) -> Optional[str]:
    if not isinstance(mode, str):
        return None
    candidate = mode.strip().lower()
    return candidate if candidate in MODES else None


_CURRENT_ENVELOPE_MODE = (
    _clean_mode(os.environ.get("RESOLVE_MCP_RESULT_ENVELOPE")) or DEFAULT_MODE
)


def get_envelope_mode() -> str:
    """The envelope mode applied when a call does not name one."""
    return _CURRENT_ENVELOPE_MODE


def set_envelope_mode(mode: str) -> str:
    """Set the default envelope mode. Unknown values leave it unchanged."""
    global _CURRENT_ENVELOPE_MODE
    cleaned = _clean_mode(mode)
    if cleaned:
        _CURRENT_ENVELOPE_MODE = cleaned
    return _CURRENT_ENVELOPE_MODE


def new_execution_id() -> str:
    """A compact id for correlating one tool call across logs and transcripts."""
    return f"exec_{uuid.uuid4().hex[:12]}"


# ─── Status ──────────────────────────────────────────────────────────────────

def normalize_status(raw: Any) -> str:
    """Reduce a result to 'success' | 'partial' | 'blocked' | 'failed'.

    Deliberately narrow. Every rule below keys on a convention this repo
    actually uses, checked against the call sites — a heuristic that guesses
    from a plausible-looking key name produces exactly the confident-and-wrong
    status the envelope is supposed to eliminate. The clearest example is
    ``blocked``: it reads like a gate flag, but here it is a domain key holding
    the *list of targets that could not be resolved* (`timeline` range delete,
    `timeline_item_color.bulk_match_to_hero`), and a successful dry-run carries
    a non-empty one. Keying on it would report a gate that never happened.
    """
    if not isinstance(raw, dict):
        return "success" if bool(raw) else "failed"

    # The confirm gate. `_issue_confirm_token` is the single producer of these
    # responses and always stamps this exact status, so the check is exact
    # rather than inferred.
    if raw.get("status") == "confirmation_required" or raw.get("confirmation_required") is True:
        return "blocked"

    if raw.get("error"):
        return "failed"
    if raw.get("success") is False:
        return "failed"

    # Bulk operations set this explicitly when some units failed.
    if raw.get("partial") is True:
        return "partial"
    succeeded, failed = raw.get("succeeded"), raw.get("failed")
    if isinstance(succeeded, int) and isinstance(failed, int) and succeeded > 0 and failed > 0:
        return "partial"

    return "success"


# ─── Warnings ────────────────────────────────────────────────────────────────

def extract_warnings(raw: Any) -> List[str]:
    """Every advisory the payload carries, as a flat list of strings."""
    if not isinstance(raw, dict):
        return []

    out: List[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value.strip() and value.strip() not in out:
            out.append(value.strip())

    plural = raw.get("warnings")
    if isinstance(plural, list):
        for item in plural:
            add(item if isinstance(item, str) else str(item) if item else None)
    else:
        add(plural)
    add(raw.get("warning"))

    ignored = raw.get("ignored_options")
    if ignored:
        add(f"Ignored unsupported options: {ignored}")

    return out


# ─── Verification ────────────────────────────────────────────────────────────

def extract_verification(raw: Any) -> Dict[str, Any]:
    """Normalize whatever verification evidence the payload carries.

    'unverified' means *no evidence was reported*, which is not the same as
    'checked and fine' — a caller that needs certainty should treat it as an
    open question rather than a pass.
    """
    unverified = {"status": "unverified", "checks": [], "contradiction": False}
    if not isinstance(raw, dict):
        return unverified

    # An impl that already speaks this shape wins outright.
    existing = raw.get("verification")
    if isinstance(existing, dict) and existing:
        merged = dict(existing)
        merged.setdefault(
            "status", "passed" if existing.get("verified") else "unverified")
        merged.setdefault("checks", [])
        merged.setdefault("contradiction", False)
        return merged

    checks: List[Dict[str, Any]] = []
    status = "unverified"
    contradiction = False

    readback = raw.get("readback")
    if isinstance(readback, dict):
        missing = readback.get("missing")
        if isinstance(missing, list):
            checks.append({
                "check": "readback_verification",
                "passed": not missing,
                "missing_items": len(missing),
            })
            status = "passed" if not missing else "failed"

    # verify_by_readback's own shape: a mutation that reported success while the
    # post-state disagrees is a contradiction, this repo's single most valuable
    # reliability signal — it must not be flattened into a plain failure.
    if "verified" in raw:
        verified = bool(raw["verified"])
        contradiction = bool(raw.get("contradiction"))
        checks.append({
            "check": "readback_post_state",
            "passed": verified,
            "contradiction": contradiction,
            "observed": raw.get("observed"),
        })
        status = "contradiction" if contradiction else ("passed" if verified else "failed")

    if "property_restore_failures" in raw:
        failures = _as_int(raw.get("property_restore_failures"))
        checks.append({
            "check": "property_restore",
            "passed": failures == 0,
            "restored_items": _as_int(raw.get("properties_restored_items")),
            "failures": failures,
        })
        if failures and status in ("passed", "unverified"):
            status = "partial"

    succeeded, failed = raw.get("succeeded"), raw.get("failed")
    if isinstance(succeeded, int) and isinstance(failed, int):
        checks.append({
            "check": "bulk_operations",
            "passed": failed == 0,
            "succeeded": succeeded,
            "failed": failed,
        })
        if status == "unverified":
            if failed == 0 and succeeded > 0:
                status = "passed"
            elif succeeded > 0:
                status = "partial"
            elif failed > 0:
                status = "failed"

    if not checks:
        return unverified
    return {"status": status, "checks": checks, "contradiction": contradiction}


# ─── Changes ─────────────────────────────────────────────────────────────────

def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


#: Domain key → semantic delta. Every entry is a key that exists in `src/` and
#: means what the delta says it means; nothing is mapped on the strength of a
#: suggestive name. `properties_restored_items`, for instance, is deliberately
#: absent: a ripple insert restores clip properties it had to re-apply after
#: moving items, which is bookkeeping, not an edit the user made.
_COUNT_ALIASES = {
    "items_added": ("inserted_clips",),
    "items_moved": ("tail_items_shifted",),
    "items_deleted": (),
}


def extract_changes(raw: Any) -> Optional[Dict[str, Any]]:
    """The operation's semantic delta, or None when it did not report one.

    None, not ``{}``. An empty dict reads as "this operation changed nothing",
    which is a false statement about a ripple insert that simply never declared
    its deltas — the silent-lie failure this codebase treats as a bug class. A
    caller that needs a number and gets None knows to go and count.
    """
    if not isinstance(raw, dict):
        return None

    changes: Dict[str, Any] = {}

    # An impl that declares its own deltas is authoritative.
    declared = raw.get("_changes")
    if isinstance(declared, dict):
        changes.update(declared)

    for canonical, aliases in _COUNT_ALIASES.items():
        if canonical in raw:
            changes[canonical] = _as_int(raw[canonical])
            continue
        for alias in aliases:
            if alias in raw:
                changes[canonical] = _as_int(raw[alias])
                break

    if "shift_frames" in raw:
        changes["shift_frames"] = raw["shift_frames"]

    versioning = raw.get("_versioning")
    if isinstance(versioning, dict):
        metric = versioning.get("metric")
        before, after = versioning.get("before_value"), versioning.get("after_value")
        if metric and before is not None and after is not None:
            changes["metric"] = metric
            changes["before_value"] = before
            changes["after_value"] = after
            try:
                changes["delta"] = round(float(after) - float(before), 4)
            except (TypeError, ValueError):
                pass
        if versioning.get("archived"):
            changes["timeline_archived"] = True
            if versioning.get("archived_version"):
                changes["archived_version"] = versioning["archived_version"]

    return changes or None


# ─── Assembly ────────────────────────────────────────────────────────────────

def is_passthrough(obj: Any) -> bool:
    """MCP content objects (Image, TextContent, EmbeddedResource) go through as-is."""
    return getattr(obj.__class__, "__name__", "") in {
        "Image", "TextContent", "EmbeddedResource"
    }


def _requested_mode(params: Optional[Dict[str, Any]], fallback: Optional[str]) -> str:
    if isinstance(params, dict):
        for key in ("envelope", "_envelope"):
            if key in params:
                named = _clean_mode(params[key])
                if named:
                    return named
                if isinstance(params[key], bool):
                    return "pure" if params[key] else "legacy"
    return _clean_mode(fallback) or get_envelope_mode()


def build_operation_envelope(
    tool_name: str,
    action: str,
    params: Optional[Dict[str, Any]],
    raw_result: Any,
    *,
    execution_id: Optional[str] = None,
    mode: Optional[str] = None,
) -> Any:
    """Attach the operation envelope to one action's return value."""
    if is_passthrough(raw_result):
        return raw_result

    selected = _requested_mode(params, mode)
    if selected == "legacy":
        return raw_result

    envelope: Dict[str, Any] = {
        "status": normalize_status(raw_result),
        "operation": f"{tool_name}.{action}",
        "execution_id": execution_id or new_execution_id(),
        "verification": extract_verification(raw_result),
    }

    changes = extract_changes(raw_result)
    if changes is not None:
        envelope["changes"] = changes

    warnings = extract_warnings(raw_result)
    if warnings:
        envelope["warnings"] = warnings

    versioning = raw_result.get("_versioning") if isinstance(raw_result, dict) else None
    if isinstance(versioning, dict) and versioning.get("analysis_run_id"):
        envelope["run_id"] = versioning["analysis_run_id"]

    if selected == "pure":
        return {**envelope, "result": raw_result}

    # dual: the payload is passed through byte-for-byte and the envelope rides
    # alongside it. A non-dict return has nowhere to carry the key, so it is
    # handed back unchanged rather than being boxed into a shape callers of
    # that action have never seen.
    if not isinstance(raw_result, dict):
        return raw_result
    return {**raw_result, ENVELOPE_KEY: envelope}
