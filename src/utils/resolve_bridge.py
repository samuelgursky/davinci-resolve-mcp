"""Authenticated loopback bridge that runs *inside* DaVinci Resolve.

External scripting is a Studio feature: `fusionscript` refuses a connection from
a foreign process on the free edition. The in-app path is not gated — Blackmagic's
own README documents the Workspace ▸ Scripts menu with no edition qualifier, and a
script launched from it is handed the same `resolve` object Studio exposes. This
module is that script: it re-exports a *named, allowlisted* operation surface over
127.0.0.1 so the MCP server can drive Resolve on any edition.

This is the documented in-app path, not a circumvention of the licence check —
but Blackmagic could close it, so treat this tier as supported-until-it-isn't.

## Runs on Resolve's embedded interpreter

Standard library only. No numpy, no MCP, no project imports — this file is copied
next to a `bridge.json` into Resolve's Scripts folder and must import cleanly
there.

## Lifecycle: both host models are handled

Whether a Scripts-menu script runs in Resolve's own interpreter or as a child
`fuscript` process is version- and platform-dependent, and getting it wrong is
fatal in opposite directions:

- as a **child process**, a daemon thread dies the instant the script returns,
  so the listener must block;
- **in-process**, blocking would wedge Resolve's script execution forever.

Rather than guess, `serve()` detects which it is (see `_host_model`) and does the
right thing for each. `probe_host_model()` reports the same detection without
starting a listener, which is how the question gets answered empirically.

## Security

- Binds 127.0.0.1 only, never a routable interface.
- Every request is HMAC-SHA256 signed over its canonical form; the shared secret
  never travels on the wire.
- Timestamp freshness **plus** one-use nonces, with the nonce cache retained for
  twice the skew — see `_NONCE_RETENTION_FACTOR` for why one skew is not enough.
- Bounded before authentication: a read deadline, a byte cap enforced before any
  allocation, and a concurrent-connection cap. An unauthenticated local process
  must not be able to pin threads or memory inside Resolve.
- Operations are **named and allowlisted**. A method-name prefix match is a
  spelling convention, not a security boundary: `startswith("Delete")` admits
  `DeleteProject`, and arbitrary `Import`/`Export` admit arbitrary paths.

## Stopping without restarting Resolve

Because the listener blocks, the script that started it cannot be re-run while it
is alive, and the copy of the runtime inside Resolve's Scripts folder is taken at
install time — so a repository change leaves a *stale* bridge with no way back
short of quitting Resolve. `request_stop()` gives a client the two ways out:

- ``exit``   — stop, so Workspace ▸ Scripts can start it again;
- ``reload`` — stop, re-import the runtime from disk, and start again in the same
  process, needing no UI interaction at all.

`validate_runtime_sources()` is what makes the second one safe: the new sources
must compile *before* the running listener is asked to stop, so a syntax error
is refused by a bridge that is still serving rather than discovered by one that
has already gone.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import socket
import socketserver
import stat
import sys
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional, Tuple

PROTOCOL_VERSION = "1.0"

#: Nonces must outlive the window in which their request is still timestamp-fresh.
#: Accepting |now - ts| <= skew while pruning at now - skew leaves a replay hole
#: the width of the skew for a future-dated request: the nonce is forgotten while
#: the timestamp is still valid. Retaining for 2x the skew closes it.
_NONCE_RETENTION_FACTOR = 2

#: Pre-auth bounds. A local process that has not authenticated must not be able
#: to hold a thread or force an allocation inside Resolve's interpreter.
MAX_REQUEST_BYTES = 1_048_576
PREAUTH_READ_TIMEOUT_S = 5.0
MAX_CONCURRENT_CONNECTIONS = 16
#: Post-auth: a real Resolve call can be slow, but not unbounded.
OPERATION_TIMEOUT_S = 300.0

#: How a running bridge may be asked to stop. `exit` leaves nothing listening;
#: `reload` asks the launcher to re-import the runtime and start again.
STOP_MODES = ("exit", "reload")
#: The runtime files the launcher imports, and therefore what `reload` must be
#: able to compile before anyone is asked to stop.
RUNTIME_MODULES = ("resolve_bridge.py", "resolve_bridge_ops.py")
#: How long `serve()` waits for in-flight requests to finish before closing the
#: listener, so the reply to `shutdown` reaches the client that asked for it.
STOP_DRAIN_TIMEOUT_S = 5.0

#: Parent-process names that mean "this script is a child of Resolve".
#: `scripts/resolve_bridge_probe.py` duplicates this list because it must be
#: self-contained inside Resolve's Scripts folder; a test asserts they agree.
PARENT_MARKERS = ("resolve", "fuscript", "fusion")

_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_SIGNATURE_RE = re.compile(r"^[0-9a-f]{64}$")


class BridgeConfigError(RuntimeError):
    pass


# ── protocol ─────────────────────────────────────────────────────────────────


def canonical_request(request: Dict[str, Any]) -> bytes:
    """The exact signed representation — everything except the signature."""
    unsigned = {k: v for k, v in request.items() if k != "signature"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sign_request(token: str, request: Dict[str, Any]) -> str:
    return hmac.new(token.encode("utf-8"), canonical_request(request), hashlib.sha256).hexdigest()


def signature_is_valid(token: str, request: Dict[str, Any], signature: str) -> bool:
    return hmac.compare_digest(sign_request(token, request), signature)


# ── host model detection ─────────────────────────────────────────────────────


def _host_model(
    *,
    getppid: Callable[[], int] = os.getppid,
    process_name_of: Optional[Callable[[int], str]] = None,
    self_executable: Optional[str] = None,
) -> Dict[str, Any]:
    """Is this script running inside Resolve's own interpreter, or as a child?

    **Asks about this process, not the parent.** The parent-name approach fails
    on the sandboxed App Store build: `ps` on another process is blocked, the
    name comes back empty, and the script looks like it has no Resolve ancestor
    when in fact it is a child of one (measured: script pid 97667, parent pid
    97258, name unreadable). Defaulting that to "in-process" starts a listener
    that dies the moment the script returns — on the exact edition the bridge
    exists for.

    Reading `sys.executable` needs no permission at all. If *this* interpreter is
    Resolve's own binary we are in-process; anything else (fuscript, a python
    binary) is a child. The parent name is kept as corroboration when readable,
    never as the decision.

    Returns a dict rather than a bool so the reasoning is inspectable: this
    decision changes whether `serve()` blocks, and a silent wrong answer either
    wedges Resolve or kills the bridge instantly.
    """
    executable = self_executable if self_executable is not None else (sys.executable or "")
    parent_pid = getppid()
    reader = process_name_of or _process_name
    parent_name = reader(parent_pid) or ""

    # In-process means THIS interpreter is Resolve itself. A Resolve-launched
    # child runs fuscript or a python binary, neither of which is the app.
    self_is_host = bool(executable) and executable.rstrip("/").endswith("/Resolve")
    parent_looks_like_resolve = any(m in parent_name.lower() for m in PARENT_MARKERS)
    is_child = not self_is_host

    if self_is_host:
        reason = (
            f"this interpreter is Resolve itself ({executable!r}) — the module stays alive after "
            "the script returns, so blocking would wedge Resolve's script execution"
        )
    elif parent_looks_like_resolve:
        reason = (
            f"this interpreter is {executable!r} with parent {parent_name!r} — a Resolve-launched "
            "child, so a daemon thread would die when the script returns and the listener must block"
        )
    else:
        reason = (
            f"this interpreter is {executable!r}, which is not Resolve"
            + (f" (parent {parent_name!r})" if parent_name else " (parent name unreadable — normal "
               "under the App Store sandbox, where ps on another process is blocked)")
            + " — treated as a child process, so the listener blocks. A bridge that exits early is "
              "recoverable by re-running the script; a listener that never starts is not."
        )
    return {
        "model": "child_process" if is_child else "in_process",
        "parent_pid": parent_pid,
        "parent_name": parent_name,
        "self_executable": executable,
        "self_is_resolve": self_is_host,
        "parent_corroborates": parent_looks_like_resolve,
        "blocking_required": is_child,
        "reason": reason,
    }


def _process_name(pid: int) -> str:
    """Best-effort process name; empty string when it cannot be read."""
    try:  # Linux
        with open(f"/proc/{pid}/comm", "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        pass
    try:  # macOS
        import subprocess

        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return (out.stdout or "").strip()
    except Exception:  # pragma: no cover - defensive
        return ""


def probe_host_model() -> Dict[str, Any]:
    """Report the host model without starting a listener.

    This is the empirical answer to "does a Scripts-menu script run in-process
    or as a child?" — run it from Workspace ▸ Scripts and read the output.
    """
    model = _host_model()
    model["pid"] = os.getpid()
    model["protocol_version"] = PROTOCOL_VERSION
    return model


# ── configuration ────────────────────────────────────────────────────────────


def load_config(path: str) -> Dict[str, Any]:
    """Read bridge.json, refusing a world/group-readable secret."""
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if os.name != "nt" and mode & 0o077:
            raise BridgeConfigError(f"{path} is group/world accessible; chmod 600 it")
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except BridgeConfigError:
        raise
    except (OSError, ValueError) as exc:
        raise BridgeConfigError(f"cannot read bridge config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise BridgeConfigError("bridge config must be an object")
    if raw.get("host", "127.0.0.1") != "127.0.0.1":
        raise BridgeConfigError("bridge host must be 127.0.0.1 — never a routable interface")
    token = raw.get("token")
    if not isinstance(token, str) or len(token) < 43:
        raise BridgeConfigError("bridge token is missing or too short (need >= 43 chars)")
    port = raw.get("port", 49632)
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        raise BridgeConfigError("bridge port must be 1024..65535")
    skew = raw.get("auth_clock_skew_seconds", 60)
    if not isinstance(skew, int) or isinstance(skew, bool) or not 10 <= skew <= 300:
        raise BridgeConfigError("auth_clock_skew_seconds must be 10..300")
    return {"host": "127.0.0.1", "port": port, "token": token, "auth_clock_skew_seconds": skew}


def validate_runtime_sources(runtime_root: str) -> list:
    """Problems that would make re-importing the runtime fail. Empty means safe.

    Checked *before* the running listener is asked to stop. A reload that stops
    first and discovers the breakage afterwards leaves no bridge at all — and no
    way to start one without the Scripts menu, which is the situation reload
    exists to avoid. Compiling is not proof the module imports cleanly, so the
    launcher still loads into a throwaway module object and keeps the old one on
    failure; this catches the overwhelmingly common case (a typo) at the point
    where refusing is free.
    """
    problems = []
    for name in RUNTIME_MODULES:
        path = os.path.join(runtime_root, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
        except OSError as exc:
            problems.append(f"{name}: cannot be read ({exc})")
            continue
        try:
            compile(source, path, "exec")
        except SyntaxError as exc:
            problems.append(f"{name}: does not compile (line {exc.lineno}: {exc.msg})")
    return problems


# ── authentication ───────────────────────────────────────────────────────────


class NonceCache:
    """One-use nonces, retained past the timestamp window they protect."""

    def __init__(self, skew_seconds: int, *, capacity: int = 8192) -> None:
        self._retention = skew_seconds * _NONCE_RETENTION_FACTOR
        self._capacity = capacity
        self._seen: "OrderedDict[str, float]" = OrderedDict()
        self._lock = threading.Lock()

    def check_and_add(self, nonce: str, now: float) -> bool:
        """True when the nonce is fresh; False when it has been used."""
        with self._lock:
            cutoff = now - self._retention
            while self._seen:
                oldest, seen_at = next(iter(self._seen.items()))
                if seen_at >= cutoff:
                    break
                self._seen.pop(oldest)
            if nonce in self._seen:
                return False
            self._seen[nonce] = now
            # Capacity eviction is a memory backstop. It can in principle drop a
            # nonce that is still within retention under a flood, so it is set
            # far above any legitimate rate.
            while len(self._seen) > self._capacity:
                self._seen.popitem(last=False)
            return True


def authenticate(
    request: Any, *, token: str, skew_seconds: int, nonces: NonceCache, now: Optional[float] = None
) -> Optional[str]:
    """None when the request is authentic; otherwise a stable error code."""
    now = time.time() if now is None else now
    if not isinstance(request, dict):
        return "invalid_request"
    if request.get("protocol") != PROTOCOL_VERSION:
        return "protocol_mismatch"
    if "token" in request:
        return "unauthorized"  # the secret must never be on the wire
    timestamp = request.get("timestamp")
    nonce = request.get("nonce")
    signature = request.get("signature")
    if (
        not isinstance(timestamp, int)
        or isinstance(timestamp, bool)
        or not isinstance(nonce, str)
        or not _NONCE_RE.match(nonce)
        or not isinstance(signature, str)
        or not _SIGNATURE_RE.match(signature)
    ):
        return "unauthorized"
    if not signature_is_valid(token, request, signature):
        return "unauthorized"
    if abs(now - timestamp) > skew_seconds:
        return "stale_request"
    if not nonces.check_and_add(nonce, now):
        return "replayed_request"
    return None


# ── server ───────────────────────────────────────────────────────────────────


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:  # pragma: no cover - exercised via integration
        bridge: "Bridge" = self.server.bridge  # type: ignore[attr-defined]
        if not bridge.acquire_slot():
            self._write({"ok": False, "error": {"code": "too_many_connections"}})
            return
        try:
            self.request.settimeout(PREAUTH_READ_TIMEOUT_S)
            line = self.rfile.readline(MAX_REQUEST_BYTES + 1)
            if len(line) > MAX_REQUEST_BYTES:
                self._write({"ok": False, "error": {"code": "request_too_large"}})
                return
            if not line:
                return
            try:
                request = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                self._write({"ok": False, "error": {"code": "invalid_json"}})
                return
            self.request.settimeout(OPERATION_TIMEOUT_S)
            self._write(bridge.process(request))
        finally:
            bridge.release_slot()

    def _write(self, payload: Dict[str, Any]) -> None:
        self.wfile.write((json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    address_family = socket.AF_INET

    def __init__(self, address: Tuple[str, int], bridge: "Bridge") -> None:
        self.bridge = bridge
        super().__init__(address, _Handler)


class Bridge:
    """Owns the listener, the nonce cache, and the serialised operation lock."""

    def __init__(self, resolve: Any, config: Dict[str, Any], dispatch: Callable[[str, Dict[str, Any]], Any]) -> None:
        self.resolve = resolve
        self.config = config
        self._dispatch = dispatch
        self._nonces = NonceCache(config["auth_clock_skew_seconds"])
        # Resolve's API is not thread-safe; the listener is threaded. Every
        # native call is serialised behind this, matching the server-side
        # bridge-lock discipline.
        self._operation_lock = threading.RLock()
        self._slots = threading.Semaphore(MAX_CONCURRENT_CONNECTIONS)
        self._server: Optional[_Server] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._stop_mode: Optional[str] = None

    def acquire_slot(self) -> bool:
        return self._slots.acquire(blocking=False)

    def release_slot(self) -> None:
        try:
            self._slots.release()
        except ValueError:  # pragma: no cover - defensive
            pass

    def process(self, request: Any) -> Dict[str, Any]:
        request_id = request.get("id") if isinstance(request, dict) else None
        error = authenticate(
            request,
            token=self.config["token"],
            skew_seconds=self.config["auth_clock_skew_seconds"],
            nonces=self._nonces,
        )
        if error:
            return {"id": request_id, "ok": False, "error": {"code": error}}
        operation = request.get("operation")
        arguments = request.get("arguments") or {}
        if not isinstance(operation, str) or not isinstance(arguments, dict):
            return {"id": request_id, "ok": False, "error": {"code": "invalid_request"}}
        try:
            with self._operation_lock:
                result = self._dispatch(operation, arguments)
        except Exception as exc:
            # The surface chooses stable codes — `stale_handle` tells a client to
            # re-fetch, `ambiguous_locator` tells it to disambiguate, and so on.
            # Collapsing them all to `operation_failed` here would strip exactly
            # the information they exist to carry, leaving the client one
            # undifferentiated failure and a string to pattern-match. Read by
            # attribute rather than by import: the transport must not depend on
            # the surface module, and anything raising a str `code` qualifies.
            code = getattr(exc, "code", None)
            details = getattr(exc, "details", None)
            error = {
                "code": code if isinstance(code, str) and code else "operation_failed",
                "message": str(exc)[:300],
            }
            if isinstance(details, dict) and details:
                try:
                    json.dumps(details)
                except (TypeError, ValueError):
                    pass  # a detail we cannot send must not cost the whole reply
                else:
                    error["details"] = details
            return {"id": request_id, "ok": False, "error": error}
        return {"id": request_id, "ok": True, "result": result}

    def request_stop(self, mode: str = "exit") -> str:
        """Ask `serve()` to come back. Returns without waiting, on purpose.

        The caller is inside a request handler: stopping the listener here would
        tear down the socket the reply still has to travel over. Setting a flag
        lets `process()` finish normally and `serve()` do the teardown after it
        has drained.
        """
        if mode not in STOP_MODES:
            raise ValueError(f"stop mode must be one of {list(STOP_MODES)}")
        self._stop_mode = mode
        self._stop_event.set()
        return mode

    @property
    def stop_mode(self) -> Optional[str]:
        return self._stop_mode

    def _drain(self, timeout: float) -> bool:
        """Wait until no handler is in flight, so replies are already on the wire.

        Every handler holds a slot for the whole of `handle()`, and the reply is
        written inside it (`wbufsize = 0`, so the write is a `sendall`, not a
        buffer). Reclaiming every slot therefore means every reply has been sent
        — deterministic, where a fixed grace period would only be probable.
        """
        deadline = time.monotonic() + timeout
        held = 0
        while held < MAX_CONCURRENT_CONNECTIONS and time.monotonic() < deadline:
            if self._slots.acquire(blocking=False):
                held += 1
            else:
                time.sleep(0.01)
        for _ in range(held):
            self._slots.release()
        return held == MAX_CONCURRENT_CONNECTIONS

    def start(self) -> "Bridge":
        self._server = _Server((self.config["host"], self.config["port"]), self)
        self._thread = threading.Thread(target=self._server.serve_forever, name="ResolveBridge", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        self._thread = None

    @property
    def port(self) -> int:
        return self._server.server_address[1] if self._server else self.config["port"]

    def serve(self, *, poll_seconds: float = 1.0, host_model: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Start, then block or return according to the detected host model.

        Returns immediately in-process (the caller keeps a reference alive);
        blocks until Resolve exits, or until a client asks it to stop, as a child
        process. Either choice made wrongly is fatal, which is why the detection
        is explicit and reported.

        The returned dict carries `stop_reason`, which is how the launcher knows
        whether to exit or to re-import the runtime and serve again.
        """
        model = dict(host_model or _host_model())
        self.start()
        if not model["blocking_required"]:
            model["stop_reason"] = None
            return model
        expected_parent = model["parent_pid"]
        reason = "resolve_exited"
        try:
            while True:
                if self._stop_event.is_set():
                    reason = self._stop_mode or "exit"
                    break
                if self._thread is None or not self._thread.is_alive():
                    reason = "listener_died"
                    break
                if os.getppid() != expected_parent:
                    break
                # Waiting on the event rather than joining the thread makes a
                # requested stop immediate instead of up to `poll_seconds` late.
                self._stop_event.wait(poll_seconds)
            if self._stop_event.is_set():
                self._drain(STOP_DRAIN_TIMEOUT_S)
        finally:
            self.stop()
        model["stop_reason"] = reason
        return model
