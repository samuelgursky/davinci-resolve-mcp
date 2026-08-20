# Security Policy

## Supported Use

`davinci-resolve-mcp` is a local stdio MCP server for controlling DaVinci
Resolve Studio through the official Resolve Scripting API. It is intended to run
under the same local user account that operates Resolve.

The default stdio server does not expose a network listener, remote shell, or
multi-user authentication surface. Access control is delegated to the MCP client
that launches the stdio process and to the local operating-system user session.

Two opt-in surfaces DO open local HTTP listeners, and both are hardened the same
way:

- **The control panel** (`resolve_control action=open_control_panel`,
  `python -m src.control_panel`) — a single-user browser UI on
  `127.0.0.1:8765` by default.
- **The networked MCP transport** (`--transport sse|streamable-http`) — a
  second MCP instance for remote clients, on `127.0.0.1:8000` by default.

Their posture:

- **Loopback only.** The panel refuses any bind host other than
  `127.0.0.1` / `localhost` / `::1` — the bind address is not a tool parameter
  an AI can widen. The transport defaults to loopback and logs a loud warning
  if `DAVINCI_MCP_HOST` points elsewhere.
- **Bearer token on every request.** Each panel launch generates a fresh
  `secrets.token_urlsafe(32)` token, passed to the child via environment (not
  argv) and delivered to the browser in the URL fragment (`#token=…`), which
  never reaches the server or its logs. Every route except the static shell at
  `/` returns 401 without it (`Authorization: Bearer …`, or the HttpOnly,
  `SameSite=Strict` session cookie the panel exchanges it for so image loads
  work). The transport requires `Authorization: Bearer <token>` on every request.
- **DNS-rebinding and CSRF guards.** The panel rejects any request whose
  `Host` header is not a loopback host, any request carrying a non-loopback
  `Origin`, and any `POST` that is not `Content-Type: application/json`. It
  never answers a CORS preflight, so no third-party page can call it.
- **Secrets on disk are private.** The panel's pidfile (token + pid + URL) and
  the transport's state file (token + URL) live under
  `~/.davinci-resolve-mcp/` (0700) and are written 0600 — never in a shared
  temp directory or `~/Documents`.

If you find a route that can be reached without the token, or a way to satisfy
the Host/Origin checks from a non-loopback page, that is a security bug — please
report it (see below).

## Operational Boundaries

- Keep Resolve external scripting set to **Local** unless you have a separate,
  intentional remote-control deployment plan.
- Treat the MCP client as the user-confirmation boundary. Clients should ask for
  confirmation before destructive or high-impact actions such as quitting
  Resolve, deleting projects, replacing clips, relinking media, deleting markers,
  changing render/project settings, or installing/removing scripts, Fuses, DCTLs,
  and presets.
- Source media is immutable by default. This server must not modify, transcode,
  proxy, relink, replace, or create derivatives of source media unless the user
  explicitly asks for that exact operation.
- Analysis outputs belong in sidecar files, session scratch space, or the
  configured `davinci-resolve-mcp-analysis` project root.

## Tool Metadata

Tools use MCP `ToolAnnotations` where supported:

- `readOnlyHint` for probe/list/get operations.
- `destructiveHint` for operations that overwrite, delete, relink, replace,
  change project state, or can otherwise cause meaningful workflow impact.
- `idempotentHint` for repeatable state changes such as page switching.
- `openWorldHint` for operations that touch filesystem paths, media, render
  output, scripts, Fuses, DCTLs, presets, or other external resources.

Compound tools group multiple actions behind an `action` parameter, so their
annotation is conservative when any action in the group can mutate state.

## Reporting Vulnerabilities

Please report security issues privately by opening a GitHub security advisory or
emailing the maintainer listed in the README. Include:

- Affected version or commit.
- MCP client and operating system.
- Minimal reproduction steps.
- Expected and actual impact.

Please do not publish exploit details until there is a coordinated fix or a
reasonable disclosure window has passed.
