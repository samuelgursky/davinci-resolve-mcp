# Threat model

## What this project does and where untrusted input enters
davinci-resolve-mcp is a Model Context Protocol server that lets an AI client drive DaVinci Resolve. Two servers ship from one repo:

- **Python server** (`src/server.py`, `src/granular/`, `src/utils/`) — wraps the Resolve Scripting API, plus offline media analysis (ffmpeg/ffprobe), a local web control panel (`src/control_panel.py`), and an optional networked MCP transport.
- **Node "advanced" server** (`resolve-advanced/server/`, vendored codecs in `resolve-advanced/vendor/`) — reads and writes Resolve's own file formats offline: `.drp` (zip of XML), `.drt`, `.drx`, Resolve's `Project.db` SQLite, AAF, FCPXML/FCP7 XML, EDL, OTIO, LUTs.

It runs on an editor's workstation under their user account. **The key trust boundary is the MCP tool call:** the arguments come from an LLM, and the LLM's context may contain attacker-influenced text (a project file, a clip name, a marker note, a web page the user pasted). Treat every tool argument as untrusted. The rule is that a tool call may do what its documented action does, to the paths it names, and nothing more.

Untrusted:
- All MCP tool arguments: paths, names, regexes, filter expressions, JSON blobs, numeric ranges.
- Content of files the tools read: `.drp/.drt/.drx` archives and XML, AAF, FCPXML, EDL, OTIO, `.cube` LUTs, SQLite databases, media files handed to ffmpeg/ffprobe, sidecar JSON.
- Strings that come back from Resolve (clip, bin, timeline, marker names and metadata). They originate in user/editor media and imported projects.
- HTTP requests to the control panel (`127.0.0.1:8765`) and to the networked transport (`--transport sse|streamable-http`, `127.0.0.1:8000`), including from a browser page the user happens to have open (DNS rebinding, CSRF).

Trusted: the local OS user, the MCP client's launch config and environment variables, files under `~/.davinci-resolve-mcp/`, and the Resolve application itself.

## Security properties we rely on (see SECURITY.md)
- **No caller-supplied code execution.** No tool may evaluate, exec, import or shell out to code or commands supplied in arguments. This is a hard policy (enforced since v3.0.0). Any path from a tool argument to `eval`/`exec`, Python `subprocess` with `shell=True`, Node `exec`, a Lua/Fusion script string, or an argv position where the program parses it as an option, is a real bug. A past example: GHSA-x29h-6rgf-w233, argument injection into `find`.
- **Destructive operations are gated.** Every mutating action is wrapped in `_destructive_op` and listed in the risk registry, so safe mode, dry-run refusal, confirm tokens and the audit log apply. An action that mutates state but skips the gate is a real bug (past examples: GHSA-gmp7-qjp9-m7gm, GHSA-vh75-g46q-hgcw).
- **Source media is immutable.** Tools must not overwrite, move, delete or write next to source media unless that exact action was requested. Analysis output goes to sidecar/scratch roots. Path traversal, symlink following, or zip-slip that makes a write land outside the intended output root is in scope.
- **Local listeners.** The control panel binds loopback only. It requires a per-launch bearer token (`#token=` fragment, then an HttpOnly SameSite=Strict cookie), rejects non-loopback `Host`/`Origin` headers and non-JSON POSTs, and answers no CORS. The networked transport requires a bearer token on every request and has a Host allowlist. Tokens must never reach `logs/server.log` (GHSA-8f4v-j8rq-hj47), argv, or world-readable files.

## Components that matter most / least
Most important:
- Subprocess call sites: `src/utils/proc.py`, `src/utils/media_analysis.py`, `src/utils/offline_fallback.py`, `src/utils/app_control.py`, `src/utils/resolve_bridge.py`, and the `spawn`/`execFile` sites in `resolve-advanced/server/*.mjs` (`aaf.mjs`, `extract-frames.mjs`, `lut-apply.mjs`, `deliverable-qc.mjs`, `media-inventory.mjs`, `editorial.mjs`, `project-db.mjs`).
- The destructive-op gate and registry: `src/utils/destructive_hook.py` and the `_destructive_op` / risk tables in `src/server.py`.
- Control panel and networked transport HTTP handling: `src/control_panel.py`, and the transport setup in `src/server.py`.
- Archive and file-format parsers that write to disk: the `.drp`/`.drt` zip readers and writers, `Project.db` patching (`resolve-advanced/server/project-db.mjs`), extracted frames and LUT output. Check for zip-slip, XXE / entity expansion in XML parsing, and SQL built from strings.
- Path handling for every argument that names a file or directory: output roots, `footageDir`-style search roots, glob patterns.
- Script/plugin install tools (Fuses, DCTLs, scripts, presets) that copy files into Resolve's support directories.

Less important but in scope: resource exhaustion from crafted project files (decompression bombs, huge XML), injection into generated reports (HTML dashboard `src/analysis_dashboard.py`, Markdown), GitHub issue drafts (`resolve_control action=report_issue` builds a URL; it must not leak local paths or tokens beyond what's shown to the user).

Out of scope: `tests/`, `examples/`, `docs/`, `scripts/` (maintainer tooling, not shipped behavior), `local/`, `*_live_probe.py` (maintainer harnesses that need a live Resolve), vulnerabilities in DaVinci Resolve itself, and the Resolve Scripting API granting full control of Resolve to any local process (that's Resolve's design).

## How to exercise it
- Python offline suite: `python -m pytest tests -q` (Resolve is stubbed; no network needed). Advanced server: `cd resolve-advanced && npm test`.
- Start the Python MCP server over stdio: `python -m src.server` (no Resolve present, so Resolve-backed tools return a connection error, but the offline tools work: media_analysis, offline fallbacks, setup, knowledge). Start the advanced server: `node bin/davinci-resolve-advanced-mcp.mjs`. Both speak JSON-RPC on stdin/stdout: send `initialize`, `notifications/initialized`, then `tools/list` / `tools/call`.
- Control panel: `python -m src.control_panel`, then probe `127.0.0.1:8765` with and without the token. Networked transport: `python -m src.server --transport streamable-http`.
- Fixtures: `resolve-advanced/vendor/*/__tests__/`, `resolve-advanced/vendor/conform-qc/__fixtures__/`, and `tests/` contain sample `.drp/.drt/.drx`, XML and media to mutate into malicious inputs. ffmpeg/ffprobe are installed.

## How you rate severity
- **Critical:** code or command execution on the user's machine from a tool argument, from a crafted project/interchange/media file, or from an unauthenticated request to a local listener (including from a web page via DNS rebinding/CSRF).
- **High:** arbitrary file write/overwrite/delete outside the intended output root (zip-slip, traversal, symlinks), and any modification of source media the user didn't request. Also: authentication bypass on the control panel or transport, token disclosure to another host or to world-readable files/logs, and a mutating action that bypasses the destructive-op gate while safe mode is on.
- **Medium:** arbitrary file read returned to the caller beyond the named path, a destructive-op gate bypass with safe mode off (an audit log gap or missing confirmation), XXE without exfiltration, injection into generated HTML reports.
- **Low:** crash, hang or memory blowup from a crafted file. Local path disclosure in error messages or issue drafts.

## Anything to leave alone
- Tools doing exactly what they document to a path the caller named, e.g. a delete action deleting the named project after its confirmation gate. The MCP client is the user-confirmation boundary by design.
- Listeners deliberately bound to a non-loopback address by the operator via `DAVINCI_MCP_HOST` (the server warns loudly; the token remains the gate).
- The `resolve_bridge` in-app script and anything reachable only by a process already running as the same user with access to Resolve's scripting socket.
- Vulnerabilities in npm/PyPI dependencies with no reachable path from a tool call or parsed file.
