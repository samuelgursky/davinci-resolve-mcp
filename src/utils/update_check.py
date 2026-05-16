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

ENV_ENABLED = "DAVINCI_RESOLVE_MCP_UPDATE_CHECK"
ENV_INTERVAL_HOURS = "DAVINCI_RESOLVE_MCP_UPDATE_INTERVAL_HOURS"
ENV_REPO = "DAVINCI_RESOLVE_MCP_UPDATE_REPO"
ENV_URL = "DAVINCI_RESOLVE_MCP_UPDATE_URL"
ENV_STATE_PATH = "DAVINCI_RESOLVE_MCP_UPDATE_STATE"

_FALSE_VALUES = {"0", "false", "no", "off", "disabled"}
_SUCCESS_STATUSES = {"up_to_date", "update_available", "current_ahead"}
_started_lock = threading.Lock()
_started = False
_cached_lock = threading.Lock()
_cached_status: Dict[str, Any] = {"status": "unknown"}


def update_check_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """Return whether startup update checks are enabled."""
    values = os.environ if env is None else env
    raw = str(values.get(ENV_ENABLED, "1")).strip().lower()
    return raw not in _FALSE_VALUES


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
        return state
    result = {"status": "unknown"}
    if current_version:
        result["current_version"] = current_version
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

    if not update_check_enabled(values):
        result = {
            "status": "disabled",
            "current_version": current_version,
            "checked_at": checked_at,
            "checked_at_iso": _format_timestamp(checked_at),
        }
        _set_cached_status(result)
        return result

    previous = _read_state(state_path)
    interval_seconds = _interval_seconds(values)
    if (
        not force
        and previous
        and checked_at - float(previous.get("checked_at", 0)) < interval_seconds
    ):
        cached = dict(previous)
        cached["cached"] = True
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
    if not update_check_enabled(values):
        result = {
            "status": "disabled",
            "current_version": current_version,
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


def _interval_seconds(env: Mapping[str, str]) -> float:
    raw = env.get(ENV_INTERVAL_HOURS)
    if raw is None:
        return DEFAULT_INTERVAL_HOURS * 60 * 60
    try:
        hours = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_HOURS * 60 * 60
    return max(hours, 0.1) * 60 * 60


def _release_api_url(env: Mapping[str, str]) -> str:
    if env.get(ENV_URL):
        return str(env[ENV_URL])
    repo = str(env.get(ENV_REPO) or DEFAULT_REPO).strip().strip("/")
    return f"https://api.github.com/repos/{repo}/releases/latest"


def _fetch_latest_release(env: Mapping[str, str], timeout: float) -> Dict[str, Any]:
    url = _release_api_url(env)
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
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub update check returned an unexpected response")
    return payload


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
    return {
        "status": status,
        "current_version": current_version,
        "latest_version": latest_version,
        "latest_tag": latest_tag,
        "release_url": release.get("html_url")
        or f"https://github.com/{repo}/releases/latest",
        "checked_at": checked_at,
        "checked_at_iso": _format_timestamp(checked_at),
    }


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
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except OSError:
        return


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
