"""Best-effort update checks for the DaVinci Resolve MCP server."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple


DEFAULT_REPO = "samuelgursky/davinci-resolve-mcp"
DEFAULT_INTERVAL_HOURS = 24.0
DEFAULT_TIMEOUT_SECONDS = 3.0
DEFAULT_SNOOZE_HOURS = 24.0
DEFAULT_CHANNEL = "stable"
VALID_CHANNELS = ("stable", "beta", "dev")

ENV_ENABLED = "DAVINCI_RESOLVE_MCP_UPDATE_CHECK"
ENV_INTERVAL_HOURS = "DAVINCI_RESOLVE_MCP_UPDATE_INTERVAL_HOURS"
ENV_MODE = "DAVINCI_RESOLVE_MCP_UPDATE_MODE"
ENV_REPO = "DAVINCI_RESOLVE_MCP_UPDATE_REPO"
ENV_SNOOZE_HOURS = "DAVINCI_RESOLVE_MCP_UPDATE_SNOOZE_HOURS"
ENV_URL = "DAVINCI_RESOLVE_MCP_UPDATE_URL"
ENV_STATE_PATH = "DAVINCI_RESOLVE_MCP_UPDATE_STATE"
ENV_CHANNEL = "DAVINCI_RESOLVE_MCP_UPDATE_CHANNEL"

_FALSE_VALUES = {"0", "false", "no", "off", "disabled"}
_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
_UPDATE_MODES = {"prompt", "auto", "notify", "never"}
_SUCCESS_STATUSES = {"up_to_date", "update_available", "current_ahead"}
_PERSISTENT_STATE_KEYS = (
    "update_mode",
    "ignored_version",
    "ignored_tag",
    "ignored_at",
    "ignored_at_iso",
    "snooze_until",
    "snooze_until_iso",
)
_started_lock = threading.Lock()
_started = False
_cached_lock = threading.Lock()
_cached_status: Dict[str, Any] = {"status": "unknown"}


def update_check_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """Return whether startup update checks are enabled."""
    values = os.environ if env is None else env
    raw = str(values.get(ENV_ENABLED, "1")).strip().lower()
    return raw not in _FALSE_VALUES and _normalize_update_mode(values.get(ENV_MODE)) != "never"


def get_update_mode(
    project_dir: Optional[os.PathLike[str] | str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """Return the configured update policy mode.

    Modes:
    - prompt: check and let human-facing callers prompt.
    - auto: human-facing callers may apply a safe update automatically.
    - notify: check and report only.
    - never: do not check for updates.
    """
    values = os.environ if env is None else env
    if not update_check_enabled(values):
        return "never"

    env_mode = _normalize_update_mode(values.get(ENV_MODE))
    if env_mode:
        return env_mode

    legacy_auto = str(values.get("DAVINCI_RESOLVE_MCP_AUTO_UPDATE", "")).strip().lower()
    if legacy_auto in _TRUE_VALUES:
        return "auto"
    if legacy_auto in _FALSE_VALUES:
        return "prompt"

    if project_dir is not None:
        state = _read_state(update_state_path(project_dir, values))
        state_mode = _normalize_update_mode(state.get("update_mode"))
        if state_mode:
            return state_mode
    return "prompt"


def parse_version(value: Any) -> Tuple[int, ...]:
    """Parse a release tag or version string into comparable integer parts."""
    match = re.search(r"\d+(?:\.\d+)*", str(value or ""))
    if not match:
        return ()
    return tuple(int(part) for part in match.group(0).split("."))


def compare_versions(current: Any, latest: Any) -> Optional[int]:
    """Compare two version strings, returning -1, 0, 1, or None if unknown."""
    left = parse_version(current)
    right = parse_version(latest)
    if not left or not right:
        return None
    width = max(len(left), len(right), 3)
    left = left + (0,) * (width - len(left))
    right = right + (0,) * (width - len(right))
    if left < right:
        return -1
    if left > right:
        return 1
    return 0


def update_state_path(
    project_dir: os.PathLike[str] | str,
    env: Optional[Mapping[str, str]] = None,
) -> Path:
    """Return the JSON state path used to throttle update checks."""
    values = os.environ if env is None else env
    override = values.get(ENV_STATE_PATH)
    if override:
        return Path(override).expanduser()
    return Path(project_dir) / "logs" / "update-check.json"


def get_cached_update_status(
    project_dir: os.PathLike[str] | str,
    current_version: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Return the last known update status without performing network I/O."""
    with _cached_lock:
        cached = dict(_cached_status)
    if cached.get("status") != "unknown":
        if current_version and "current_version" not in cached:
            cached["current_version"] = current_version
        return cached

    state = _read_state(update_state_path(project_dir, env))
    if state:
        if current_version and "current_version" not in state:
            state["current_version"] = current_version
        if "update_mode" not in state:
            state["update_mode"] = get_update_mode(project_dir, env)
        return state
    result = {"status": "unknown"}
    if current_version:
        result["current_version"] = current_version
    result["update_mode"] = get_update_mode(project_dir, env)
    return result


def check_for_updates(
    current_version: str,
    project_dir: os.PathLike[str] | str,
    *,
    env: Optional[Mapping[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    now: Optional[float] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Check GitHub releases for a newer MCP version.

    This function never installs or modifies code. Network failures are returned
    as structured status so startup can continue normally.
    """
    values = os.environ if env is None else env
    checked_at = time.time() if now is None else float(now)
    state_path = update_state_path(project_dir, values)
    previous = _read_state(state_path)
    update_mode = get_update_mode(project_dir, values)

    if update_mode == "never":
        result = {
            "status": "disabled",
            "current_version": current_version,
            "update_mode": "never",
            "checked_at": checked_at,
            "checked_at_iso": _format_timestamp(checked_at),
        }
        result = _merge_persistent_state(previous, result)
        if update_check_enabled(values):
            _write_state(state_path, result)
        _set_cached_status(result)
        return result

    interval_seconds = _interval_seconds(values)
    if (
        not force
        and previous
        and checked_at - float(previous.get("checked_at", 0)) < interval_seconds
    ):
        cached = dict(previous)
        cached["cached"] = True
        cached["update_mode"] = update_mode
        cached["next_check_at"] = float(previous.get("checked_at", 0)) + interval_seconds
        cached["next_check_at_iso"] = _format_timestamp(cached["next_check_at"])
        _set_cached_status(cached)
        return cached

    try:
        release = _fetch_latest_release(values, timeout)
        result = _result_from_release(current_version, release, checked_at, values)
    except Exception as exc:
        result = {
            "status": "error",
            "current_version": current_version,
            "checked_at": checked_at,
            "checked_at_iso": _format_timestamp(checked_at),
            "error": str(exc),
        }
        if previous and previous.get("status") in _SUCCESS_STATUSES:
            result["last_success"] = {
                key: previous.get(key)
                for key in (
                    "status",
                    "latest_version",
                    "latest_tag",
                    "release_url",
                    "checked_at",
                    "checked_at_iso",
                )
                if key in previous
            }

    result["update_mode"] = update_mode
    result = _merge_persistent_state(previous, result)
    _write_state(state_path, result)
    _set_cached_status(result)
    return result


def start_background_update_check(
    current_version: str,
    project_dir: os.PathLike[str] | str,
    logger: Any,
    *,
    env: Optional[Mapping[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Optional[threading.Thread]:
    """Start a daemon thread that checks for updates without blocking stdio."""
    global _started
    values = os.environ if env is None else env
    if get_update_mode(project_dir, values) == "never":
        result = {
            "status": "disabled",
            "current_version": current_version,
            "update_mode": "never",
            "checked_at": time.time(),
        }
        _set_cached_status(result)
        _log_result(logger, result)
        return None

    with _started_lock:
        if _started:
            return None
        _started = True

    def worker() -> None:
        result = check_for_updates(
            current_version,
            project_dir,
            env=values,
            timeout=timeout,
        )
        _log_result(logger, result)

    thread = threading.Thread(
        target=worker,
        name="davinci-resolve-mcp-update-check",
        daemon=True,
    )
    thread.start()
    return thread


def update_prompt_decision(
    result: Mapping[str, Any],
    *,
    env: Optional[Mapping[str, str]] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Return whether a human-facing caller should prompt, auto-update, or skip."""
    values = os.environ if env is None else env
    timestamp = time.time() if now is None else float(now)
    env_mode = _normalize_update_mode(values.get(ENV_MODE))
    mode = env_mode or _normalize_update_mode(result.get("update_mode")) or get_update_mode(env=values)
    if not update_check_enabled(values):
        mode = "never"
    latest_version = str(result.get("latest_version") or "").strip()
    latest_tag = str(result.get("latest_tag") or "").strip()

    if result.get("status") != "update_available":
        return {"action": "none", "reason": "no_update", "update_mode": mode}
    if mode == "never":
        return {"action": "none", "reason": "never", "update_mode": mode}
    if mode == "notify":
        return {"action": "notify", "reason": "notify_only", "update_mode": mode}
    if _matches_ignored_version(result):
        return {"action": "none", "reason": "ignored", "update_mode": mode}

    snooze_until = _float_or_none(result.get("snooze_until"))
    if snooze_until and snooze_until > timestamp:
        return {
            "action": "none",
            "reason": "snoozed",
            "update_mode": mode,
            "snooze_until": snooze_until,
            "snooze_until_iso": _format_timestamp(snooze_until),
        }

    if mode == "auto":
        return {"action": "auto", "reason": "auto", "update_mode": mode}
    return {
        "action": "prompt",
        "reason": "update_available",
        "update_mode": mode,
        "latest_version": latest_version,
        "latest_tag": latest_tag,
    }


def set_update_mode(
    project_dir: os.PathLike[str] | str,
    mode: str,
    *,
    env: Optional[Mapping[str, str]] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Persist the local update mode in the update-check state file."""
    normalized = _normalize_update_mode(mode)
    if not normalized:
        raise ValueError(f"Unsupported update mode: {mode!r}")
    state_path = update_state_path(project_dir, env)
    state = _read_state(state_path)
    state["update_mode"] = normalized
    state["updated_at"] = time.time() if now is None else float(now)
    state["updated_at_iso"] = _format_timestamp(state["updated_at"])
    _write_state(state_path, state)
    _set_cached_status(state or {"status": "unknown", "update_mode": normalized})
    return state


def ignore_update_version(
    project_dir: os.PathLike[str] | str,
    result: Mapping[str, Any],
    *,
    env: Optional[Mapping[str, str]] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Persist an ignored release version/tag for future prompts."""
    timestamp = time.time() if now is None else float(now)
    state_path = update_state_path(project_dir, env)
    state = _read_state(state_path)
    if result.get("latest_version"):
        state["ignored_version"] = result.get("latest_version")
    if result.get("latest_tag"):
        state["ignored_tag"] = result.get("latest_tag")
    state["ignored_at"] = timestamp
    state["ignored_at_iso"] = _format_timestamp(timestamp)
    state.pop("snooze_until", None)
    state.pop("snooze_until_iso", None)
    _write_state(state_path, state)
    _set_cached_status(state or {"status": "unknown"})
    return state


def snooze_update_prompt(
    project_dir: os.PathLike[str] | str,
    *,
    hours: Optional[float] = None,
    env: Optional[Mapping[str, str]] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Persist a temporary update-prompt snooze."""
    values = os.environ if env is None else env
    timestamp = time.time() if now is None else float(now)
    snooze_hours = _snooze_hours(values, hours)
    snooze_until = timestamp + snooze_hours * 60 * 60
    state_path = update_state_path(project_dir, values)
    state = _read_state(state_path)
    state["snooze_until"] = snooze_until
    state["snooze_until_iso"] = _format_timestamp(snooze_until)
    _write_state(state_path, state)
    _set_cached_status(state or {"status": "unknown"})
    return state


def clear_update_prompt_preferences(
    project_dir: os.PathLike[str] | str,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Clear ignored-version and snooze state while preserving check results."""
    state_path = update_state_path(project_dir, env)
    state = _read_state(state_path)
    for key in (
        "ignored_version",
        "ignored_tag",
        "ignored_at",
        "ignored_at_iso",
        "snooze_until",
        "snooze_until_iso",
    ):
        state.pop(key, None)
    _write_state(state_path, state)
    _set_cached_status(state or {"status": "unknown"})
    return state


def _normalize_update_mode(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower().replace("_", "-")
    aliases = {
        "": "",
        "ask": "prompt",
        "manual": "prompt",
        "prompt": "prompt",
        "auto": "auto",
        "automatic": "auto",
        "autoupdate": "auto",
        "auto-update": "auto",
        "check": "notify",
        "check-only": "notify",
        "inform": "notify",
        "informational": "notify",
        "notify": "notify",
        "off": "never",
        "disable": "never",
        "disabled": "never",
        "never": "never",
        "none": "never",
    }
    normalized = aliases.get(text, text)
    return normalized if normalized in _UPDATE_MODES else None


def _merge_persistent_state(
    previous: Mapping[str, Any],
    result: Mapping[str, Any],
) -> Dict[str, Any]:
    merged = dict(result)
    for key in _PERSISTENT_STATE_KEYS:
        if key in previous and key not in merged:
            merged[key] = previous[key]
    return merged


def _matches_ignored_version(result: Mapping[str, Any]) -> bool:
    ignored_version = str(result.get("ignored_version") or "").strip()
    ignored_tag = str(result.get("ignored_tag") or "").strip()
    latest_version = str(result.get("latest_version") or "").strip()
    latest_tag = str(result.get("latest_tag") or "").strip()
    return bool(
        (ignored_version and ignored_version == latest_version)
        or (ignored_tag and ignored_tag == latest_tag)
    )


def _float_or_none(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _snooze_hours(env: Mapping[str, str], override: Optional[float]) -> float:
    if override is not None:
        try:
            return max(float(override), 0.1)
        except (TypeError, ValueError):
            return DEFAULT_SNOOZE_HOURS
    raw = env.get(ENV_SNOOZE_HOURS)
    if raw is None:
        return DEFAULT_SNOOZE_HOURS
    try:
        return max(float(raw), 0.1)
    except (TypeError, ValueError):
        return DEFAULT_SNOOZE_HOURS


def _interval_seconds(env: Mapping[str, str]) -> float:
    raw = env.get(ENV_INTERVAL_HOURS)
    if raw is None:
        return DEFAULT_INTERVAL_HOURS * 60 * 60
    try:
        hours = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_HOURS * 60 * 60
    return max(hours, 0.1) * 60 * 60


def get_update_channel(env: Optional[Mapping[str, str]] = None) -> str:
    """Resolve the active update channel: stable | beta | dev."""
    values = os.environ if env is None else env
    raw = str(values.get(ENV_CHANNEL) or DEFAULT_CHANNEL).strip().lower()
    return raw if raw in VALID_CHANNELS else DEFAULT_CHANNEL


def _release_api_url(env: Mapping[str, str], *, channel: Optional[str] = None) -> str:
    if env.get(ENV_URL):
        return str(env[ENV_URL])
    repo = str(env.get(ENV_REPO) or DEFAULT_REPO).strip().strip("/")
    ch = (channel or get_update_channel(env)).lower()
    # `stable` → latest non-prerelease only (GitHub's /releases/latest).
    # `beta`, `dev` → list endpoint so we can pick prereleases too.
    if ch == "stable":
        return f"https://api.github.com/repos/{repo}/releases/latest"
    return f"https://api.github.com/repos/{repo}/releases?per_page=10"


def _fetch_latest_release(env: Mapping[str, str], timeout: float) -> Dict[str, Any]:
    channel = get_update_channel(env)
    url = _release_api_url(env, channel=channel)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "davinci-resolve-mcp-update-check",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub update check failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub update check failed: {exc.reason}") from exc
    payload = json.loads(data)

    if channel == "stable":
        if not isinstance(payload, dict):
            raise RuntimeError("GitHub update check returned an unexpected response")
        payload["_channel"] = channel
        return payload

    # beta/dev: payload is a LIST of releases ordered newest-first by created_at.
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("GitHub update check returned no releases")
    selected: Optional[Dict[str, Any]] = None
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        tag = str(entry.get("tag_name") or "").lower()
        if channel == "beta":
            # Allow non-prerelease stable releases AND prereleases tagged -beta.
            if (not entry.get("prerelease")) or "beta" in tag:
                selected = entry
                break
        else:  # dev — accept anything including all prereleases.
            selected = entry
            break
    if selected is None:
        selected = payload[0]
    selected["_channel"] = channel
    return selected


def _result_from_release(
    current_version: str,
    release: Mapping[str, Any],
    checked_at: float,
    env: Mapping[str, str],
) -> Dict[str, Any]:
    latest_tag = str(release.get("tag_name") or release.get("name") or "").strip()
    latest_version = _version_text(latest_tag)
    comparison = compare_versions(current_version, latest_version)
    if comparison is None:
        status = "unknown"
    elif comparison < 0:
        status = "update_available"
    elif comparison > 0:
        status = "current_ahead"
    else:
        status = "up_to_date"

    repo = str(env.get(ENV_REPO) or DEFAULT_REPO).strip().strip("/")
    body = str(release.get("body") or "").strip()
    return {
        "status": status,
        "current_version": current_version,
        "latest_version": latest_version,
        "latest_tag": latest_tag,
        "release_url": release.get("html_url")
        or f"https://github.com/{repo}/releases/latest",
        "release_notes": body,
        "release_notes_breaking": _scan_for_breaking_changes(body),
        "release_target_sha": release.get("target_commitish") or release.get("tag_sha"),
        "prerelease": bool(release.get("prerelease")),
        "channel": release.get("_channel") or get_update_channel(env),
        "checked_at": checked_at,
        "checked_at_iso": _format_timestamp(checked_at),
    }


_BREAKING_RE = re.compile(
    r"(?:^|\n)\s*(?:[-*]\s*)?"
    r"(?:\*\*)?(?:BREAKING(?:\s+CHANGE)?[: ]|⚠️|:warning:|MIGRATION\s+REQUIRED[: ])(?:\*\*)?"
    r"(?P<rest>[^\n]+)",
    re.IGNORECASE,
)


def _scan_for_breaking_changes(body: str) -> list:
    """Pluck BREAKING/⚠️/MIGRATION-REQUIRED markers out of a release-notes blob."""
    if not body:
        return []
    found: list = []
    for match in _BREAKING_RE.finditer(body):
        snippet = (match.group("rest") or "").strip(" -*\t")
        if snippet:
            found.append(snippet)
    return found


def _version_text(value: Any) -> str:
    match = re.search(r"\d+(?:\.\d+)*", str(value or ""))
    return match.group(0) if match else str(value or "").strip()


def _read_state(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(path: Path, result: Mapping[str, Any]) -> None:
    # Atomic replace: _read_state resets to {} on a corrupt file, so a crash
    # mid-write would silently drop snooze/ignore preferences.
    tmp_path = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    except OSError:
        return
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _set_cached_status(result: Mapping[str, Any]) -> None:
    with _cached_lock:
        _cached_status.clear()
        _cached_status.update(dict(result))


def _format_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )


def _log_result(logger: Any, result: Mapping[str, Any]) -> None:
    status = result.get("status")
    if status == "update_available":
        logger.warning(
            "DaVinci Resolve MCP update available: current v%s, latest v%s. "
            "Update from %s",
            result.get("current_version"),
            result.get("latest_version"),
            result.get("release_url"),
        )
    elif status == "up_to_date":
        logger.info("DaVinci Resolve MCP is up to date at v%s", result.get("current_version"))
    elif status == "current_ahead":
        logger.info(
            "DaVinci Resolve MCP local version v%s is newer than latest release v%s",
            result.get("current_version"),
            result.get("latest_version"),
        )
    elif status == "disabled":
        logger.info("DaVinci Resolve MCP update checks are disabled")
    elif status == "error":
        logger.warning("DaVinci Resolve MCP update check failed: %s", result.get("error"))
