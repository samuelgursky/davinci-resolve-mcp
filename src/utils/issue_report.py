"""Draft a GitHub issue from inside a chat — bug reports and feature requests.

The user says "send this as a bug" (or "…as a feature request") and the agent
calls `resolve_control(action="report_issue")`. The server never files
anything. It writes the issue and returns a prefilled `issues/new` link; the
user reads the draft, opens the link, and presses Submit on GitHub under their
own account. That keeps three things true:

  - no GitHub credential ever lives in the MCP server;
  - nothing is published that the user has not seen;
  - the report still carries the facts a maintainer would otherwise have to
    ask for in the thread — server version, Resolve build and edition,
    connection mode, OS — which is most of the value.

Redaction runs over every field before it reaches the draft: absolute paths,
the local username, full name and hostname, e-mail addresses, and anything
shaped like a secret. It is best-effort by construction — it cannot recognise
a client or project name typed as plain prose — so the result always tells
the agent to show the draft to the user before handing over the link.

Nothing here connects to Resolve. A report about a connection that will not
come up must not launch Resolve or wait on one, so the environment is read
from a handle the server already holds, or reported as "not connected".
"""

from __future__ import annotations

import getpass
import os
import platform
import re
import socket
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode

from .update_check import DEFAULT_REPO

#: GitHub answers `414 URI Too Long` somewhere past 8 KB and does not document
#: the exact limit. Stay under it; the full body is returned separately.
MAX_URL_CHARS = 8000

MAX_FIELD_CHARS = 4000

KINDS: Dict[str, Dict[str, str]] = {
    "bug": {"template": "bug_report.md", "label": "bug"},
    "feature": {"template": "feature_request.md", "label": "enhancement"},
}

_KIND_ALIASES = {
    "bug": "bug",
    "bug_report": "bug",
    "defect": "bug",
    "issue": "bug",
    "feature": "feature",
    "feature_request": "feature",
    "enhancement": "feature",
    "request": "feature",
    "idea": "feature",
}

#: Install and support locations that say which build is installed and where.
#: They are the same on every machine, so keeping them costs no privacy and
#: saves a round-trip on installer and connection bugs.
_KEEP_PATH_PREFIXES = (
    "/Library/Application Support/Blackmagic Design",
    "/Applications/DaVinci Resolve",
    "/opt/resolve",
    "~/.davinci-resolve-mcp",
    "c:\\program files\\blackmagic design",
    "c:\\programdata\\blackmagic design",
)

#: Usernames that are also ordinary words. Redacting "user" or "editor" out of
#: prose mangles the report and protects nobody.
_COMMON_ACCOUNT_NAMES = {
    "root", "user", "admin", "administrator", "guest", "test", "dev",
    "editor", "video", "mac", "pc", "home", "owner", "localhost",
}

_TRUNCATION_NOTE = "\n\n_…truncated to fit the link — the full report is in the chat._"

_FOOTER = (
    "\n\n---\n"
    "<sub>Drafted in chat with the davinci-resolve-mcp `report_issue` action. "
    "Local paths, the username and anything secret-shaped were redacted "
    "automatically.</sub>\n"
    "<!-- filed-via: davinci-resolve-mcp report_issue -->"
)

# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------

_SEGMENT = r"[^\s/\\\"'`<>|*?:]+"
# A directory segment may contain spaces ("/Volumes/My Drive/") because it is
# closed by the next slash. A final segment may only when it ends in a file
# extension ("A001 take 2.mov"); otherwise it stops at the first space, so
# "/tmp/a to /tmp/b" stays two paths. A space after a comma or before a `~`
# ends the path too — "x.log, see ~/y" is prose between two paths, not one.
_SPACED = r"(?<![,;]) (?!~)"
_DIR_SEGMENT = rf"{_SEGMENT}(?:{_SPACED}{_SEGMENT})*"
_LAST_SEGMENT = (
    rf"(?:{_SEGMENT}(?:{_SPACED}{_SEGMENT})*\.[A-Za-z0-9]{{1,5}}(?![\w.])|{_SEGMENT})"
)

_POSIX_PATH = re.compile(rf"(?<![\w:/.~\\-])(?:~/|/)(?:{_DIR_SEGMENT}/)+{_LAST_SEGMENT}")
_WINDOWS_PATH = re.compile(
    rf"(?<![\w])(?:[A-Za-z]:[\\/]|\\\\{_SEGMENT}\\)(?:{_DIR_SEGMENT}[\\/])*{_LAST_SEGMENT}"
)

_SECRET_PATTERNS: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"#token=[^\s&\"'`]+"), "#token=<redacted>"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*"), "Bearer <redacted>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "<redacted-key>"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "<redacted-key>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "<redacted-key>"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<redacted-key>"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), "<redacted-key>"),
    (
        re.compile(
            r"(?i)\b(token|api[_-]?key|secret|password|passwd|authorization)"
            r"(\s*[=:]\s*)(?!<redacted)[^\s,;&\"'`]+"
        ),
        r"\1\2<redacted>",
    ),
)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _trailing_punctuation(match: str) -> Tuple[str, str]:
    stripped = match.rstrip(".,;:)]}")
    return stripped, match[len(stripped):]


def _path_replacement(path: str, home: str = "") -> Tuple[str, bool]:
    """Return (replacement, redacted?) for one matched absolute path."""
    if len(home) > 1 and path.lower().startswith(home.lower()):
        path = "~" + path[len(home):].replace("\\", "/")
    windows = re.match(r"^[A-Za-z]:|^\\\\", path)
    comparable = path.lower().replace("/", "\\") if windows else path
    for prefix in _KEEP_PATH_PREFIXES:
        if comparable.startswith(prefix):
            return path, False
    last = re.split(r"[\\/]", path)[-1]
    ext = re.search(r"\.([A-Za-z0-9]{1,5})$", last)
    if ext and not ext.group(1).isdigit():
        return f"<path>.{ext.group(1)}", True
    return "<path>", True


def local_identity() -> Dict[str, Any]:
    """The strings that identify this machine and its user."""
    identity: Dict[str, Any] = {"home": os.path.expanduser("~"), "names": []}
    names: List[str] = []
    try:
        names.append(getpass.getuser())
    except Exception:
        pass
    try:
        import pwd  # POSIX only

        gecos = pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0].strip()
        if gecos:
            names.append(gecos)
    except Exception:
        pass
    try:
        host = socket.gethostname().split(".")[0]
        if host:
            names.append(host)
    except Exception:
        pass
    identity["names"] = names
    return identity


def redact(text: Any, identity: Optional[Dict[str, Any]] = None) -> Tuple[str, Dict[str, int]]:
    """Scrub one field. Returns (text, counts by kind)."""
    counts = {"secrets": 0, "emails": 0, "paths": 0, "identity": 0}
    if text is None:
        return "", counts
    out = str(text)
    identity = identity if identity is not None else local_identity()

    for pattern, replacement in _SECRET_PATTERNS:
        out, n = pattern.subn(replacement, out)
        counts["secrets"] += n

    out, n = _EMAIL.subn("<email>", out)
    counts["emails"] += n

    # The home directory is folded to `~` per path, not across the text first:
    # on Windows that would turn C:\Users\name\… into ~\…, which no longer
    # looks like an absolute path and would slip through unredacted.
    home = identity.get("home") or ""

    def _sub_path(match: re.Match) -> str:
        path, tail = _trailing_punctuation(match.group(0))
        replacement, redacted = _path_replacement(path, home)
        if redacted:
            counts["paths"] += 1
        return replacement + tail

    out = _WINDOWS_PATH.sub(_sub_path, out)
    out = _POSIX_PATH.sub(_sub_path, out)
    if len(home) > 1:
        out = out.replace(home, "~")

    # Letters-only boundaries, not \b: `\bname\b` misses "name_project" and
    # "name2", because `_` and digits are word characters.
    for name in sorted(set(identity.get("names") or []), key=len, reverse=True):
        if len(name) < 3 or name.lower() in _COMMON_ACCOUNT_NAMES:
            continue
        pattern = re.compile(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", re.IGNORECASE)
        out, n = pattern.subn("<user>", out)
        counts["identity"] += n
    return out, counts


# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------


def _connection_kind(handle: Any) -> str:
    try:
        from . import resolve_bridge_client

        if isinstance(handle, resolve_bridge_client.BridgeProxy):
            return "in-app bridge"
    except Exception:
        pass
    if os.environ.get("RESOLVE_SCRIPT_HOST"):
        return "network scripting"
    return "local scripting"


def _os_description() -> str:
    system = platform.system()
    if system == "Darwin":
        release = platform.mac_ver()[0] or platform.release()
        return f"macOS {release} ({platform.machine()})"
    if system == "Windows":
        return f"Windows {platform.release()} ({platform.version()}, {platform.machine()})"
    return f"{system} {platform.release()} ({platform.machine()})"


def collect_environment(resolve_handle: Any, mcp_version: str) -> Dict[str, str]:
    """What a maintainer needs to reproduce, read without connecting."""
    env: Dict[str, str] = {"MCP server": mcp_version}
    if resolve_handle is not None:
        try:
            env["DaVinci Resolve"] = (
                f"{resolve_handle.GetProductName()} {resolve_handle.GetVersionString()}"
            )
        except Exception:
            env["DaVinci Resolve"] = "connected, version unreadable"
        env["Connection"] = _connection_kind(resolve_handle)
    else:
        env["DaVinci Resolve"] = "not connected"
        env["Connection"] = "not connected"
    try:
        from . import resolve_runtime

        mode = resolve_runtime.runtime_mode()
        if not mode.get("running"):
            env["Resolve process"] = "not running"
        elif mode.get("headless") is True:
            env["Resolve process"] = "running, headless (-nogui)"
        elif mode.get("headless") is False:
            env["Resolve process"] = "running, with UI"
        else:
            env["Resolve process"] = "running, mode unknown"
    except Exception:
        pass
    env["OS"] = _os_description()
    env["Python"] = platform.python_version()
    return env


# --------------------------------------------------------------------------
# Draft
# --------------------------------------------------------------------------


def normalize_kind(kind: Any) -> Optional[str]:
    return _KIND_ALIASES.get(str(kind or "").strip().lower().replace("-", "_").replace(" ", "_"))


def _clip(text: str, limit: int = MAX_FIELD_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n…(truncated)"


def _steps_markdown(steps: Any) -> str:
    if isinstance(steps, (list, tuple)):
        return "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1) if str(s).strip())
    return str(steps)


def _fence(text: str) -> str:
    fence = "```"
    while fence in text:
        fence += "`"
    return f"{fence}\n{text}\n{fence}"


def _environment_markdown(environment: Dict[str, str]) -> str:
    rows = "\n".join(
        f"| {key} | {str(value).replace('|', '/')} |" for key, value in environment.items()
    )
    return f"### Environment\n\n| | |\n|---|---|\n{rows}"


def issue_url(repo: str, kind: str, title: str, body: str) -> str:
    query = urlencode(
        {
            "template": KINDS[kind]["template"],
            "labels": KINDS[kind]["label"],
            "title": title,
            "body": body,
        },
        quote_via=quote,
    )
    return f"https://github.com/{repo}/issues/new?{query}"


def _fit_url(repo: str, kind: str, title: str, narrative: str, tail: str) -> Tuple[str, bool]:
    """Build the link, shortening only the narrative if the whole body won't fit.

    The environment table and footer are the part a maintainer cannot ask the
    reporter to reconstruct later, so they are never the part cut.
    """
    url = issue_url(repo, kind, title, narrative + tail)
    if len(url) <= MAX_URL_CHARS:
        return url, False
    lo, hi = 0, len(narrative)
    best = issue_url(repo, kind, title, _TRUNCATION_NOTE.lstrip() + tail)
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = issue_url(repo, kind, title, narrative[:mid].rstrip() + _TRUNCATION_NOTE + tail)
        if len(candidate) <= MAX_URL_CHARS:
            best, lo = candidate, mid + 1
        else:
            hi = mid - 1
    return best, True


def build_issue(
    kind: str,
    title: str,
    summary: str,
    *,
    steps: Any = None,
    expected: Any = None,
    actual: Any = None,
    error: Any = None,
    tool: Any = None,
    tool_action: Any = None,
    use_case: Any = None,
    proposal: Any = None,
    environment: Optional[Dict[str, str]] = None,
    identity: Optional[Dict[str, Any]] = None,
    repo: str = DEFAULT_REPO,
) -> Dict[str, Any]:
    """Redact every field, lay out the issue, and build the prefilled link."""
    identity = identity if identity is not None else local_identity()
    totals = {"secrets": 0, "emails": 0, "paths": 0, "identity": 0}

    def scrub(value: Any) -> str:
        text, counts = redact(value, identity)
        for key, n in counts.items():
            totals[key] += n
        return _clip(text.strip())

    clean_title = scrub(title).replace("\n", " ")[:200]
    sections: List[str] = []

    def add(heading: str, value: Any, render=lambda s: s) -> None:
        if value is None or (isinstance(value, (list, tuple)) and not value) or not str(value).strip():
            return
        if isinstance(value, (list, tuple)):
            value = [scrub(v) for v in value]
            sections.append(f"### {heading}\n\n{render(value)}")
        else:
            sections.append(f"### {heading}\n\n{render(scrub(value))}")

    if kind == "bug":
        add("What happened", summary)
        add("Steps to reproduce", steps, _steps_markdown)
        add("Expected", expected)
        add("Actual", actual)
    else:
        add("What I'd like", summary)
        add("What I was trying to do", use_case)
        add("How it could work", proposal)

    if tool or tool_action:
        call = " → ".join(f"`{scrub(v)}`" for v in (tool, tool_action) if v)
        sections.append(f"### {'Failing call' if kind == 'bug' else 'Related call'}\n\n{call}")
    if error is not None and str(error).strip():
        sections.append(_fence(scrub(error)))

    narrative = "\n\n".join(sections)
    tail = ""
    if environment:
        tail = "\n\n" + _environment_markdown(
            {key: scrub(value) for key, value in environment.items()}
        )
    tail += _FOOTER

    url, truncated = _fit_url(repo, kind, clean_title, narrative, tail)
    return {
        "kind": kind,
        "repo": repo,
        "title": clean_title,
        "body": narrative + tail,
        "labels": [KINDS[kind]["label"]],
        "url": url,
        "url_truncated": truncated,
        "redactions": totals,
    }


def next_step_guidance(truncated: bool) -> str:
    text = (
        "Nothing has been filed. Show the user the title and body above, then give "
        "them the url: the issue is created only when they open it and press Submit "
        "on GitHub under their own account (a GitHub account is required). "
        "Redaction is best-effort — it removes paths, the local username, e-mail "
        "addresses and secret-shaped strings, but cannot recognise a client, "
        "project or person named in plain prose, so ask the user to check for "
        "those before submitting."
    )
    if truncated:
        text += (
            " The body was too long for a link and the url carries a shortened "
            "copy; tell the user to paste the full body from the chat into the "
            "issue before submitting."
        )
    return text


__all__ = [
    "KINDS",
    "MAX_URL_CHARS",
    "build_issue",
    "collect_environment",
    "issue_url",
    "local_identity",
    "next_step_guidance",
    "normalize_kind",
    "redact",
]
