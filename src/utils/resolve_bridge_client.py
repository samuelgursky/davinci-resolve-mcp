"""Client side of the in-app bridge: a proxy that looks exactly like Resolve.

The point is that **existing call sites do not change**. Code written against the
native API —

    resolve.GetProjectManager().GetCurrentProject().GetMediaPool()

— works verbatim against a `BridgeProxy`. Each attribute access returns a
callable that signs a request, sends it over loopback to the script running
inside Resolve, and rehydrates the answer. Live Resolve objects come back as
opaque handles wrapped in further proxies, so chains of arbitrary depth work.

## Why a proxy rather than a mapping layer

The MCP server already holds the thorough layer: confirm tokens, path
allowlists, timeline versioning, dry-run/confirm gates, the destructive-action
registry. All of it sits *above* this and keeps working unchanged. A mapping
layer would mean a second validation surface at the bridge boundary, and two
safety layers that must agree are a drift risk rather than extra safety.

## Transparency includes the ugly parts

`False` is returned as `False`, not raised. Resolve signals failure that way far
more often than it raises, and every existing call site was written knowing it.
Converting it here would silently change the meaning of code that already handles
it correctly. The bridge's *named* operations do apply `false_is_error`; the
proxy deliberately does not.

## What it does not hide

- **Latency.** Every call is a loopback round trip, measured at ~0.35 ms. Fine
  for hundreds of calls, noticeable for tens of thousands — enumerating a large
  timeline item-by-item is the shape that bites.
- **Bridge absence.** If the in-Resolve script is not running, construction fails
  with a clear message rather than pretending; there is nothing to fall back to.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils import resolve_bridge as _bridge

logger = logging.getLogger("resolve-mcp.bridge-client")

DEFAULT_CONFIG_PATH = Path.home() / ".config/davinci-resolve-mcp/bridge.json"
#: Env override, so a caller can point at a non-default bridge without editing code.
ENV_CONFIG_PATH = "DAVINCI_RESOLVE_BRIDGE_CONFIG"
#: Opt-in. Absent means "do not try the bridge", so nothing changes for existing
#: installs until someone asks for it.
ENV_ENABLE = "DAVINCI_RESOLVE_BRIDGE"

#: Operations this client cannot work without. The in-Resolve script is a *copy*
#: taken at install time, so it can be older than the client — and a stale bridge
#: must fail at connect with an actionable message, not mid-session on every
#: attribute access. `list_methods` is required because without it the proxy
#: cannot answer `hasattr` truthfully, which silently breaks capability detection.
REQUIRED_BRIDGE_OPERATIONS = ("call", "list_methods", "release_handles", "health")

DEFAULT_TIMEOUT_SECONDS = 30.0


class BridgeUnavailable(RuntimeError):
    """The in-Resolve bridge could not be reached. Not a fallback condition."""


class BridgeCallError(RuntimeError):
    """The bridge refused or failed a call, carrying its stable code."""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = details or {}


def config_path() -> Path:
    override = os.environ.get(ENV_CONFIG_PATH)
    return Path(override).expanduser() if override else DEFAULT_CONFIG_PATH


def bridge_enabled() -> bool:
    """Opt-in only — an unset env var must not change existing behaviour."""
    return str(os.environ.get(ENV_ENABLE, "")).strip().lower() in {"1", "true", "yes", "on"}


class BridgeTransport:
    """One authenticated loopback connection per request, serialised."""

    def __init__(self, config: Dict[str, Any], *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.host = config["host"]
        self.port = int(config["port"])
        self._token = config["token"]
        self.timeout = float(timeout)
        #: Propagated to proxies decoded from this transport's replies.
        self.strict_attributes = True
        #: type name -> frozenset of method names, scoped to **this** transport.
        #: Per-transport rather than per-class because the method set is the
        #: answer to "what does this Resolve build have", and two builds can be
        #: bridged from one process — the differential harness does exactly that.
        #: A shared cache would let free 21's surface answer for Studio 19, which
        #: is the precise question `list_methods` exists to get right.
        self.method_cache: Dict[str, frozenset] = {}
        self.cache_lock = threading.Lock()
        # The in-Resolve side serialises native calls anyway; serialising here too
        # keeps request/response pairing simple and matches the _bridge_lock
        # discipline the rest of the server already follows.
        self._lock = threading.RLock()

    def request(self, operation: str, arguments: Dict[str, Any]) -> Any:
        payload = {
            "protocol": _bridge.PROTOCOL_VERSION,
            "id": str(uuid.uuid4()),
            "timestamp": int(time.time()),
            "nonce": secrets.token_urlsafe(24),
            "operation": operation,
            "arguments": arguments,
        }
        payload["signature"] = _bridge.sign_request(self._token, payload)
        line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        if len(line) > _bridge.MAX_REQUEST_BYTES:
            raise BridgeCallError("request_too_large", "request exceeds the bridge limit")

        with self._lock:
            try:
                with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                    sock.settimeout(self.timeout)
                    sock.sendall(line)
                    raw = sock.makefile("rb").readline(_bridge.MAX_REQUEST_BYTES + 1)
            except (TimeoutError, socket.timeout) as exc:
                raise BridgeCallError(
                    "bridge_timeout",
                    "Resolve did not answer in time — check for an open modal dialog, "
                    "which blocks its scripting API entirely",
                ) from exc
            except OSError as exc:
                raise BridgeUnavailable(
                    "Cannot reach the in-Resolve bridge on "
                    f"{self.host}:{self.port} ({exc}). Start it from "
                    "Workspace > Scripts > resolve_bridge."
                ) from exc

        if not raw:
            raise BridgeCallError("bridge_protocol_error", "bridge closed without replying")
        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise BridgeCallError("bridge_protocol_error", "bridge returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise BridgeCallError("bridge_protocol_error", "bridge returned a non-object")
        if response.get("id") != payload["id"]:
            # Mismatched ids mean interleaved responses; failing loudly beats
            # handing a caller another request's answer.
            raise BridgeCallError("bridge_protocol_error", "bridge response id does not match")
        if response.get("ok") is not True:
            error = response.get("error") or {}
            raise BridgeCallError(
                str(error.get("code", "bridge_error")),
                str(error.get("message", "the bridge refused the call")),
                error.get("details") if isinstance(error.get("details"), dict) else {},
            )
        return response.get("result")


def _encode_argument(value: Any) -> Any:
    """Send a proxy back as the handle it stands for."""
    if isinstance(value, BridgeProxy):
        return {"__handle__": value._handle}
    if isinstance(value, dict):
        return {k: _encode_argument(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode_argument(v) for v in value]
    return value


def _decode_value(transport: BridgeTransport, value: Any) -> Any:
    """Rehydrate a reply: handles become proxies, recursively."""
    if isinstance(value, dict):
        handle = value.get("__handle__")
        if handle is not None:
            return BridgeProxy(transport, handle, type_name=value.get("__type__"),
                               strict_attributes=getattr(transport, "strict_attributes", True))
        return {k: _decode_value(transport, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode_value(transport, v) for v in value]
    return value


class _BoundMethod:
    """One callable method on a proxied object."""

    __slots__ = ("_transport", "_handle", "_name")

    def __init__(self, transport: BridgeTransport, handle: str, name: str) -> None:
        self._transport = transport
        self._handle = handle
        self._name = name

    def __call__(self, *args: Any) -> Any:
        result = self._transport.request(
            "call",
            {"target": self._handle, "method": self._name,
             "args": [_encode_argument(a) for a in args]},
        )
        return _decode_value(self._transport, (result or {}).get("value"))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<bridge method {self._handle}.{self._name}>"


class BridgeProxy:
    """Stands in for a live Resolve object reached over the bridge.

    Attribute access yields a callable, so any chain the existing code uses
    behaves as it would against the native object. Return values are never
    cached: Resolve's own proxies are views onto mutable state, and caching
    would hand callers a stale answer.

    **Attribute existence IS checked**, and that is not optional. A naive
    `__getattr__` proxy answers `hasattr(obj, anything)` with True, so
    capability detection — `getattr(timeline, "CreateMagicMask", None)`, of which
    this codebase has ~50 instances — silently passes for methods the running
    Resolve build does not have. The call then fails somewhere else with an
    unrelated error instead of refusing cleanly at the check.

    So an unknown name raises `AttributeError`, exactly as the native object
    would. The method set is fetched once per object *type* and shared across
    every proxy of that type, so this costs one extra round trip per distinct
    type per session, not per object.
    """

    __slots__ = ("_transport", "_handle", "_type_name", "_strict")

    def __init__(self, transport: BridgeTransport, handle: str, *, type_name: Optional[str] = None,
                 strict_attributes: bool = True) -> None:
        object.__setattr__(self, "_transport", transport)
        object.__setattr__(self, "_handle", handle)
        object.__setattr__(self, "_type_name", type_name)
        # `strict_attributes=False` permits any name, i.e. the naive-proxy
        # behaviour where hasattr is always True. Only for talking to a bridge
        # too old to support `list_methods`; `connect()` refuses those outright,
        # so this is an explicit opt-in for diagnostics, never the default.
        object.__setattr__(self, "_strict", strict_attributes)

    def _methods(self) -> frozenset:
        # Cached on the transport, so all Timeline proxies from one bridge share
        # a single fetch while a second bridge keeps its own answer.
        cache = self._transport.method_cache
        key = self._type_name or self._handle
        cached = cache.get(key)
        if cached is not None:
            return cached
        result = self._transport.request("list_methods", {"target": self._handle}) or {}
        names = frozenset(result.get("methods") or ())
        # Key on the type the bridge reports, so sibling objects reuse this.
        actual = result.get("type") or key
        with self._transport.cache_lock:
            cache[actual] = names
            cache[key] = names
        return names

    def __getattr__(self, name: str) -> _BoundMethod:
        if name.startswith("__") and name.endswith("__"):
            # Let normal dunder lookup fail rather than sending it over the wire.
            raise AttributeError(name)
        if self._strict and name not in self._methods():
            # Matches native semantics: hasattr() is False, getattr(..., None)
            # is None, and a capability check refuses instead of guessing.
            raise AttributeError(
                f"{self._type_name or 'Resolve object'} has no attribute {name!r} "
                "in this Resolve build"
            )
        return _BoundMethod(self._transport, self._handle, name)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<BridgeProxy {self._handle}>"

    # -- lifecycle helpers, not part of the Resolve API -------------------

    def bridge_health(self) -> Dict[str, Any]:
        """The bridge's own health payload — not a Resolve method."""
        return self._transport.request("health", {})

    def bridge_release_handles(self, handles: Optional[List[str]] = None) -> Dict[str, Any]:
        """Drop handles the bridge is holding. Long sessions should call this."""
        return self._transport.request(
            "release_handles", {} if handles is None else {"handles": handles}
        )

    def bridge_shutdown(self) -> Dict[str, Any]:
        """Stop the in-Resolve listener so Workspace ▸ Scripts can start it again.

        Does not wait: the reply is written before the listener goes away, and
        there is nothing to come back to.
        """
        return self._transport.request("shutdown", {})

    def bridge_reload(self, *, wait: bool = True, timeout: float = 30.0,
                      poll_seconds: float = 0.1) -> Dict[str, Any]:
        """Re-import the in-Resolve runtime from disk, in place.

        This is what makes the bridge iterable: re-run the installer, call this,
        and the new code is live without touching Resolve's UI.

        Waiting is keyed on the surface's `session` id rather than on health
        merely answering, because for a short window after the reply the *old*
        listener is still accepting connections — a naive "wait until health
        works" returns immediately, against the code being replaced.

        **Every handle from before is dead.** The new session mints new ids, so
        existing proxies raise `stale_handle` and must be re-fetched from a root.
        """
        before = (self.bridge_health() or {}).get("session")
        result = dict(self._transport.request("reload", {}) or {})
        if not wait:
            return result
        deadline = time.monotonic() + timeout
        last_error: Optional[Exception] = None
        while time.monotonic() < deadline:
            time.sleep(poll_seconds)
            try:
                health = self.bridge_health() or {}
            except (BridgeUnavailable, BridgeCallError) as exc:
                last_error = exc  # expected while the listener is down
                continue
            session = health.get("session")
            if session and session != before:
                self._transport.method_cache.clear()
                return {**result, "session": session, "reloaded": True,
                        "operations": health.get("operations")}
        raise BridgeCallError(
            "reload_timeout",
            f"the bridge did not come back within {timeout:g}s"
            + (f" (last error: {last_error})" if last_error else "")
            + ". Check the script's output inside Resolve — a reload that fails to "
              "import keeps serving the previous runtime.",
        )


def connect(*, timeout: float = DEFAULT_TIMEOUT_SECONDS, require_enabled: bool = True) -> BridgeProxy:
    """Return a Resolve-shaped proxy backed by the in-app bridge.

    Raises `BridgeUnavailable` rather than returning None so a caller cannot
    accidentally treat "no bridge" as "no Resolve" and carry on.
    """
    if require_enabled and not bridge_enabled():
        raise BridgeUnavailable(
            f"The in-app bridge is opt-in: set {ENV_ENABLE}=1 to use it."
        )
    path = config_path()
    try:
        config = _bridge.load_config(str(path))
    except _bridge.BridgeConfigError as exc:
        raise BridgeUnavailable(
            f"Bridge configuration unusable ({exc}). Run "
            "`python scripts/install_resolve_bridge.py` first."
        ) from exc

    transport = BridgeTransport(config, timeout=timeout)
    proxy = BridgeProxy(transport, "resolve", type_name="Resolve")
    # Prove the far end is alive now, rather than failing on the first real call
    # somewhere deep in a tool.
    health = transport.request("health", {})
    available = set((health or {}).get("operations") or ())
    missing = [op for op in REQUIRED_BRIDGE_OPERATIONS if op not in available]
    if missing:
        raise BridgeUnavailable(
            "The running in-Resolve bridge is older than this client and is "
            f"missing {missing}. The script inside Resolve is a copy taken at "
            "install time, so it does not update when the repository does. Fix: "
            "re-run `python scripts/install_resolve_bridge.py`, then stop and "
            "restart Workspace > Scripts > resolve_bridge."
        )
    logger.info(
        "connected to the in-Resolve bridge: %s %s (%s)",
        (health or {}).get("product"), (health or {}).get("version"), (health or {}).get("edition"),
    )
    return proxy
