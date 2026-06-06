"""Networked transport for the MCP server (opt-in via --transport).

stdio remains the default. The `sse` and `streamable-http` modes bind to
loopback (127.0.0.1) by default and REQUIRE a bearer token on every request, so
turning networking on never silently exposes Resolve. The token comes from
``$DAVINCI_MCP_TOKEN`` or is generated and logged at startup. A small state file
lets the control panel show the live connection URL + token.

Security posture:
- Default host is loopback; a non-loopback bind logs a loud warning.
- Every HTTP request must carry ``Authorization: Bearer <token>`` (constant-time
  compared); otherwise 401.
- stdio (the default transport) is unaffected by anything here.
"""
import json
import logging
import os
import secrets
import tempfile
import time

logger = logging.getLogger("davinci-resolve-mcp")

TRANSPORT_STATE_PATH = os.path.join(
    tempfile.gettempdir(), "davinci_resolve_mcp_transport.json"
)
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def resolve_token():
    """Return (token, was_generated). Honors $DAVINCI_MCP_TOKEN."""
    tok = os.environ.get("DAVINCI_MCP_TOKEN")
    if tok:
        return tok, False
    return secrets.token_urlsafe(24), True


def _auth_middleware_cls(token):
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    expected = f"Bearer {token}"

    class BearerAuth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            provided = request.headers.get("authorization", "")
            if not secrets.compare_digest(provided, expected):
                return JSONResponse(
                    {"error": "unauthorized: Authorization: Bearer <token> required"},
                    status_code=401,
                )
            return await call_next(request)

    return BearerAuth


def write_transport_state(transport, host, port, token):
    try:
        with open(TRANSPORT_STATE_PATH, "w", encoding="utf-8") as fh:
            json.dump({
                "transport": transport,
                "host": host,
                "port": port,
                "url": f"http://{host}:{port}",
                "token": token,
                "loopback": host in LOOPBACK_HOSTS,
                "pid": os.getpid(),
                "started_at": time.time(),
            }, fh)
    except OSError as exc:
        logger.warning("could not write transport state: %s", exc)


def clear_transport_state():
    try:
        os.remove(TRANSPORT_STATE_PATH)
    except OSError:
        pass


def read_transport_state():
    """Return the live transport state dict, or None if no networked instance.

    Treats a state file whose pid is no longer alive as stale (returns None).
    """
    try:
        with open(TRANSPORT_STATE_PATH, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return None
    pid = state.get("pid")
    if isinstance(pid, int):
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return None
    return state


def run_networked(mcp, transport):
    """Serve `mcp` over an authenticated HTTP transport ('sse'|'streamable-http')."""
    import uvicorn

    host = os.environ.get("DAVINCI_MCP_HOST") or mcp.settings.host or "127.0.0.1"
    port = int(os.environ.get("DAVINCI_MCP_PORT") or mcp.settings.port or 8000)
    mcp.settings.host = host
    mcp.settings.port = port
    token, generated = resolve_token()

    app = mcp.sse_app() if transport == "sse" else mcp.streamable_http_app()
    app.add_middleware(_auth_middleware_cls(token))

    if host not in LOOPBACK_HOSTS:
        logger.warning(
            "SECURITY: MCP %s transport bound to NON-loopback host %r — Resolve "
            "control is exposed on the network. Ensure this is intended.",
            transport, host,
        )
    logger.info("MCP %s transport: http://%s:%s (bearer token required)",
                transport, host, port)
    if generated:
        logger.info("Generated bearer token (set $DAVINCI_MCP_TOKEN to pin it): %s", token)

    write_transport_state(transport, host, port, token)
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        clear_transport_state()
