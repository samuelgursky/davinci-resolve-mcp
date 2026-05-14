# Security Policy

## Supported Use

`davinci-resolve-mcp` is a local stdio MCP server for controlling DaVinci
Resolve Studio through the official Resolve Scripting API. It is intended to run
under the same local user account that operates Resolve.

The default server does not expose a network listener, HTTP API, remote shell, or
multi-user authentication surface. Access control is delegated to the MCP client
that launches the stdio process and to the local operating-system user session.

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
