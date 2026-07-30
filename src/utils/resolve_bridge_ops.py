"""The named operation surface the in-app bridge exposes. Stdlib-only.

`resolve_bridge` is transport: authentication, framing, lifecycle. This is what
it is allowed to *do*. The split matters because the transport is generic and the
surface is the actual security boundary.

## Named operations, not a method-name proxy

The tempting design is one generic `call(object, method, args)` with a
method-name prefix allowlist. It costs nothing to write and covers the whole API.
It is also not a security boundary: `startswith("Delete")` admits
`DeleteProject`, and prefix-matched `Import`/`Export` admit arbitrary filesystem
paths. Anything that reaches the socket then has the run of the project.

So operations are named, arguments are validated, and paths are checked against
configured roots. Adding an operation is a deliberate act.

## The generic `call` operation, and its actual security model

`call` proxies one method invocation onto a live Resolve object, which is what
lets the MCP server's existing call sites work over the bridge unchanged. It is
deliberately NOT gated by a method-name allowlist — that was never a security
boundary anyway (`startswith("Delete")` admits `DeleteProject`).

The honest model: **`call` is gated by the token, and that is stronger than the
baseline it replaces.** Resolve's own external scripting API has no
authentication at all — any local process that can load `fusionscript` gets
unrestricted control of the running application. This bridge adds HMAC-signed
requests, one-use nonces, a freshness window, loopback-only binding and
pre-auth bounds on top of the same capability. Refusing `call` on security
grounds while native scripting sits wide open would be theatre.

What `call` genuinely constrains:

- **Only objects the API itself returned.** Targets are either one of the named
  roots or a handle this bridge minted from a Resolve return value. A caller can
  never name an arbitrary Python object, reach a module, or touch `__globals__`.
- **Dunder and private names are refused**, so `__class__`/`__globals__`
  traversal is closed.
- **The handle table is bounded and session-scoped.** An unbounded table is a
  slow memory leak inside Resolve — every enumerated timeline item pinning a
  live proxy object forever.

The named operations below still exist and remain the stricter surface. Use them
when a caller only needs the common path; use `call` when the existing code has
to work unmodified.

## Reads may be broad; writes are narrow

Reading cannot damage a project, so the read surface covers what an agent needs
to orient. Writes are deliberately few here: this bridge exists to reach the free
edition, and the destructive surface belongs behind the main server's existing
confirm-token and versioning discipline, not duplicated inside Resolve where
neither is available.

**This is a subset, and says so.** `health` reports exactly which operations
exist, so a caller discovers the surface rather than assuming parity with the
direct transport.

## Lifecycle operations act on the bridge, not the project

`shutdown` and `reload` stop the listener. They exist because the launcher blocks
— the script that started the bridge cannot be re-run while it is alive, and the
runtime inside Resolve's Scripts folder is a copy taken at install time, so a
repository change strands a stale bridge with no way back short of quitting
Resolve. `reload` re-imports from disk in place and needs no UI interaction.

They carry no gate beyond the token, deliberately: a caller holding it can
already drive Resolve through `call`, so refusing them would guard nothing while
removing the only remote recovery path.

## False is an error

Resolve's API returns False or None for failure far more often than it raises.
`_call(..., false_is_error=True)` turns that into a real failure instead of a
silent success — the single most common way these connectors lie.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Tuple

PROTOCOL_SURFACE_VERSION = "1.0"


class OperationError(RuntimeError):
    """A refused or failed operation, carrying a stable code."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


# ── path policy ──────────────────────────────────────────────────────────────


class PathPolicy:
    """Confine filesystem arguments to configured roots, after symlink resolution.

    Resolution happens before the check, so a symlink pointing out of an allowed
    root is rejected rather than followed.
    """

    def __init__(self, media_roots: List[str], output_roots: List[str]) -> None:
        self.media_roots = self._normalize(media_roots, "media")
        self.output_roots = self._normalize(output_roots, "output")

    @staticmethod
    def _normalize(roots: Any, kind: str) -> Tuple[str, ...]:
        if not isinstance(roots, list) or not roots:
            raise OperationError("policy_invalid", f"no {kind} roots configured")
        resolved = []
        for raw in roots:
            if not isinstance(raw, str) or not raw:
                raise OperationError("policy_invalid", f"invalid {kind} root")
            resolved.append(os.path.realpath(os.path.expanduser(raw)))
        return tuple(dict.fromkeys(resolved))

    @staticmethod
    def _under(path: str, roots: Tuple[str, ...]) -> bool:
        return any(path == root or path.startswith(root + os.sep) for root in roots)

    def input_file(self, raw: Any) -> str:
        if not isinstance(raw, str) or not raw:
            raise OperationError("invalid_path", "input path must be a non-empty string")
        expanded = os.path.expanduser(raw)
        if not os.path.isabs(expanded):
            raise OperationError("invalid_path", "input path must be absolute")
        path = os.path.realpath(expanded)
        if not os.path.isfile(path):
            raise OperationError("input_not_found", "input file does not exist", path=raw)
        if not self._under(path, self.media_roots):
            raise OperationError("path_not_allowed", "input path is outside the configured media roots")
        return path


# ── the surface ──────────────────────────────────────────────────────────────


class ResolveOperations:
    """Explicit router over Resolve's native proxy objects."""

    #: Read-only: cannot damage a project, so the surface is generous.
    READ_OPERATIONS = (
        "health",
        "list_projects",
        "get_project",
        "list_timelines",
        "get_timeline",
        "list_media",
        "get_render_formats",
    )
    #: Writes: deliberately narrow. Destructive work stays behind the main
    #: server's confirm-token + versioning discipline, which does not exist here.
    WRITE_OPERATIONS = (
        "save_project",
        "set_current_timeline",
    )
    #: The transparent proxy. See the module docstring for its security model.
    PROXY_OPERATIONS = ("call", "release_handles", "list_methods")
    #: Lifecycle: they act on the bridge, never on the project. Separated from the
    #: write surface so "writes stay narrower than reads" keeps measuring what it
    #: was written to measure.
    LIFECYCLE_OPERATIONS = ("shutdown", "reload")
    OPERATIONS = READ_OPERATIONS + WRITE_OPERATIONS + PROXY_OPERATIONS + LIFECYCLE_OPERATIONS

    #: Handle-table ceiling. Every entry pins a live Resolve proxy object, so an
    #: unbounded table is a memory leak inside Resolve that grows with every
    #: timeline item anyone enumerates. Oldest entries are evicted; a caller that
    #: loses a handle gets a clear `stale_handle` error and can re-fetch.
    MAX_HANDLES = 4096

    def __init__(
        self,
        resolve: Any,
        *,
        media_roots: List[str],
        output_roots: List[str],
        max_items: int = 500,
        lifecycle: Optional[Callable[[str], Dict[str, Any]]] = None,
    ) -> None:
        if resolve is None:
            raise OperationError("resolve_unavailable", "Resolve object is not available")
        self.resolve = resolve
        # Supplied by whatever owns the listener (the launcher). Absent means the
        # lifecycle operations report `capability_unavailable` rather than
        # pretending to stop something they have no handle on.
        self._lifecycle = lifecycle
        self.policy = PathPolicy(media_roots, output_roots)
        self.max_items = max(1, min(int(max_items), 5000))
        self._routes: Dict[str, Callable[[Dict[str, Any]], Any]] = {
            name: getattr(self, f"op_{name}") for name in self.OPERATIONS
        }
        # Handles are session-scoped: a new ResolveOperations means new ids, so a
        # stale handle from a previous bridge run can never silently resolve to a
        # different object.
        self._handles: "OrderedDict[str, Any]" = OrderedDict()
        self._handle_counter = 0
        self._session = os.urandom(4).hex()

    # -- plumbing ---------------------------------------------------------

    def dispatch(self, operation: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        route = self._routes.get(operation)
        if route is None:
            raise OperationError(
                "operation_not_allowed",
                f"operation {operation!r} is not exposed by this bridge",
                available=sorted(self.OPERATIONS),
            )
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise OperationError("invalid_arguments", "arguments must be an object")
        return route(arguments)

    @staticmethod
    def _call(obj: Any, method: str, *args: Any, false_is_error: bool = False) -> Any:
        fn = getattr(obj, method, None)
        if not callable(fn):
            raise OperationError("capability_unavailable", f"Resolve does not expose {method} in this build")
        value = fn(*args)
        if false_is_error and (value is False or value is None):
            raise OperationError("operation_failed", f"Resolve returned failure from {method}")
        return value

    def _project_manager(self) -> Any:
        manager = self._call(self.resolve, "GetProjectManager")
        if manager is None:
            raise OperationError("resolve_not_ready", "Resolve has no project manager yet")
        return manager

    def _project(self) -> Any:
        project = self._call(self._project_manager(), "GetCurrentProject")
        if project is None:
            raise OperationError("no_project", "no Resolve project is currently open")
        return project

    def _timeline(self, arguments: Dict[str, Any]) -> Any:
        project = self._project()
        name = arguments.get("timeline_name")
        if not name:
            timeline = self._call(project, "GetCurrentTimeline")
            if timeline is None:
                raise OperationError("no_timeline", "no current timeline is selected")
            return timeline
        matches = []
        for index in range(1, int(self._call(project, "GetTimelineCount") or 0) + 1):
            candidate = self._call(project, "GetTimelineByIndex", index)
            if candidate is not None and self._call(candidate, "GetName") == name:
                matches.append(candidate)
        if not matches:
            raise OperationError("not_found", f"timeline {name!r} was not found")
        if len(matches) > 1:
            # Resolve permits duplicate timeline names; acting on an arbitrary
            # one of them is exactly the kind of silent wrong-target this refuses.
            raise OperationError("ambiguous_locator", f"more than one timeline is named {name!r}")
        return matches[0]

    # -- reads ------------------------------------------------------------

    def op_health(self, _arguments: Dict[str, Any]) -> Dict[str, Any]:
        manager = self._project_manager()
        project = self._call(manager, "GetCurrentProject")
        product = str(self._call(self.resolve, "GetProductName") or "")
        return {
            "connected": True,
            "product": product,
            "version": self._call(self.resolve, "GetVersionString"),
            "edition": "studio" if "studio" in product.lower() else "free",
            "current_page": self._call(self.resolve, "GetCurrentPage"),
            "current_project": self._call(project, "GetName") if project is not None else None,
            "surface_version": PROTOCOL_SURFACE_VERSION,
            # Handles are scoped to this id. A client that sees it change knows
            # its handles are gone — which is how `reload` is waited on, since
            # the bridge comes back on the same port with a new object graph.
            "session": self._session,
            # The caller discovers the surface rather than assuming parity with
            # the direct transport — this bridge is deliberately a subset.
            "operations": sorted(self.OPERATIONS),
            "read_operations": sorted(self.READ_OPERATIONS),
            "write_operations": sorted(self.WRITE_OPERATIONS),
            # False when nothing owns the listener, so a client can tell
            # "this bridge cannot be stopped remotely" from "I forgot to ask".
            "lifecycle_available": self._lifecycle is not None,
            "policy": {
                "media_roots": list(self.policy.media_roots),
                "output_roots": list(self.policy.output_roots),
                "max_items": self.max_items,
            },
        }

    def op_list_projects(self, _arguments: Dict[str, Any]) -> Dict[str, Any]:
        manager = self._project_manager()
        current = self._call(manager, "GetCurrentProject")
        database = self._call(manager, "GetCurrentDatabase") or {}
        if isinstance(database, dict):
            database = {k: v for k, v in database.items() if k != "IpAddress"}
        return {
            "folder": self._call(manager, "GetCurrentFolder"),
            "projects": list(self._call(manager, "GetProjectListInCurrentFolder") or [])[: self.max_items],
            "current_project": self._call(current, "GetName") if current else None,
            "database": database,
        }

    def op_get_project(self, _arguments: Dict[str, Any]) -> Dict[str, Any]:
        project = self._project()
        return {
            "name": self._call(project, "GetName"),
            "timeline_count": int(self._call(project, "GetTimelineCount") or 0),
            "current_timeline": (
                self._call(self._call(project, "GetCurrentTimeline"), "GetName")
                if self._call(project, "GetCurrentTimeline") is not None
                else None
            ),
        }

    def op_list_timelines(self, _arguments: Dict[str, Any]) -> Dict[str, Any]:
        project = self._project()
        count = int(self._call(project, "GetTimelineCount") or 0)
        timelines = []
        for index in range(1, min(count, self.max_items) + 1):
            timeline = self._call(project, "GetTimelineByIndex", index)
            if timeline is None:
                continue
            timelines.append({
                "index": index,
                "name": self._call(timeline, "GetName"),
                "start_frame": self._call(timeline, "GetStartFrame"),
                "end_frame": self._call(timeline, "GetEndFrame"),
            })
        return {"timelines": timelines, "total": count, "truncated": count > self.max_items}

    def op_get_timeline(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        timeline = self._timeline(arguments)
        tracks = []
        for track_type in ("video", "audio", "subtitle"):
            count = int(self._call(timeline, "GetTrackCount", track_type) or 0)
            for index in range(1, count + 1):
                tracks.append({
                    "type": track_type,
                    "index": index,
                    "name": self._call(timeline, "GetTrackName", track_type, index),
                    "enabled": self._call(timeline, "GetIsTrackEnabled", track_type, index),
                    "locked": self._call(timeline, "GetIsTrackLocked", track_type, index),
                })
        return {
            "name": self._call(timeline, "GetName"),
            "start_frame": self._call(timeline, "GetStartFrame"),
            "end_frame": self._call(timeline, "GetEndFrame"),
            "start_timecode": self._call(timeline, "GetStartTimecode"),
            "tracks": tracks,
        }

    def op_list_media(self, _arguments: Dict[str, Any]) -> Dict[str, Any]:
        pool = self._call(self._project(), "GetMediaPool")
        root = self._call(pool, "GetRootFolder", false_is_error=True)
        clips: List[Dict[str, Any]] = []
        pending = [root]
        seen = set()
        while pending and len(clips) < self.max_items:
            folder = pending.pop()
            unique = str(self._call(folder, "GetUniqueId"))
            if unique in seen:
                continue
            seen.add(unique)
            for clip in list(self._call(folder, "GetClipList") or []):
                if len(clips) >= self.max_items:
                    break
                props = self._call(clip, "GetClipProperty") or {}
                raw_path = str(props.get("File Path", "") or "")
                clips.append({
                    "name": self._call(clip, "GetName"),
                    # A path outside the configured roots is reported as such
                    # rather than leaked: the bridge should not become a way to
                    # enumerate the filesystem.
                    "file_path": raw_path if self._path_visible(raw_path) else "<outside-allowed-roots>",
                    "duration": props.get("Duration"),
                    "fps": props.get("FPS"),
                    "resolution": props.get("Resolution"),
                })
            pending.extend(list(self._call(folder, "GetSubFolderList") or []))
        return {"clips": clips, "truncated": len(clips) >= self.max_items}

    def _path_visible(self, raw: str) -> bool:
        if not raw:
            return False
        try:
            resolved = os.path.realpath(os.path.expanduser(raw))
        except OSError:
            return False
        return self.policy._under(resolved, self.policy.media_roots)

    def op_get_render_formats(self, _arguments: Dict[str, Any]) -> Dict[str, Any]:
        project = self._project()
        formats = self._call(project, "GetRenderFormats") or {}
        return {
            "formats": formats,
            "current": self._call(project, "GetCurrentRenderFormatAndCodec") or {},
        }

    # -- writes -----------------------------------------------------------

    def op_save_project(self, _arguments: Dict[str, Any]) -> Dict[str, Any]:
        self._project()
        return {"saved": bool(self._call(self._project_manager(), "SaveProject", false_is_error=True))}

    def op_set_current_timeline(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        name = arguments.get("timeline_name")
        if not isinstance(name, str) or not name.strip():
            raise OperationError("invalid_arguments", "timeline_name is required")
        timeline = self._timeline({"timeline_name": name})
        self._call(self._project(), "SetCurrentTimeline", timeline, false_is_error=True)
        return {"current_timeline": self._call(timeline, "GetName")}


# ── the transparent proxy ────────────────────────────────────────────────────

    #: Roots a caller may start a chain from by name. Everything else must be a
    #: handle this bridge minted, and therefore already a descendant of the live
    #: `resolve` object.
    ROOT_NAMES = ("resolve", "project_manager", "project", "media_pool", "current_timeline")

    def _mint(self, obj: Any) -> str:
        self._handle_counter += 1
        handle = "h:%s:%d" % (self._session, self._handle_counter)
        self._handles[handle] = obj
        # Bounded, oldest-first. A caller that loses a handle re-fetches; an
        # unbounded table would pin every enumerated item for the session.
        while len(self._handles) > self.MAX_HANDLES:
            self._handles.popitem(last=False)
        return handle

    def _named_root(self, name: str) -> Any:
        if name == "resolve":
            return self.resolve
        manager = self._project_manager()
        if name == "project_manager":
            return manager
        project = self._call(manager, "GetCurrentProject")
        if name == "project":
            if project is None:
                raise OperationError("no_project", "no Resolve project is currently open")
            return project
        if project is None:
            raise OperationError("no_project", "no Resolve project is currently open")
        if name == "media_pool":
            return self._call(project, "GetMediaPool")
        if name == "current_timeline":
            timeline = self._call(project, "GetCurrentTimeline")
            if timeline is None:
                raise OperationError("no_timeline", "no current timeline is selected")
            return timeline
        raise OperationError("invalid_arguments", f"unknown root object {name!r}")

    def _resolve_target(self, target: Any) -> Any:
        if not isinstance(target, str) or not target:
            raise OperationError("invalid_arguments", "target must be a root name or a bridge handle")
        if target in self.ROOT_NAMES:
            return self._named_root(target)
        if target.startswith("h:"):
            if target in self._handles:
                self._handles.move_to_end(target)
                return self._handles[target]
            raise OperationError(
                "stale_handle",
                "that handle is no longer held by the bridge — re-fetch the object and retry",
                hint="handles are session-scoped and bounded; a restart or heavy enumeration evicts them",
            )
        raise OperationError(
            "invalid_arguments",
            f"target must be one of {list(self.ROOT_NAMES)} or a bridge-issued handle",
        )

    def _encode(self, value: Any, depth: int = 0) -> Any:
        """Resolve return value -> JSON-safe, minting handles for live objects."""
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if depth > 6:
            return str(value)
        if isinstance(value, (list, tuple)):
            return [self._encode(v, depth + 1) for v in list(value)[: self.max_items]]
        if isinstance(value, dict):
            return {str(k): self._encode(v, depth + 1) for k, v in list(value.items())[: self.max_items]}
        return {"__handle__": self._mint(value), "__type__": type(value).__name__}

    def _decode(self, value: Any) -> Any:
        """Argument -> live object, rehydrating handles the bridge itself issued."""
        if isinstance(value, dict):
            handle = value.get("__handle__")
            if handle is not None:
                return self._resolve_target(handle)
            return {k: self._decode(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._decode(v) for v in value]
        return value

    def op_call(self, arguments: Dict[str, Any]) -> Any:
        """Invoke one method on a live Resolve object. See the module docstring.

        Returns whatever Resolve returned, verbatim — including False. The proxy
        is transparent on purpose: the MCP server's existing call sites already
        interpret False correctly, and re-interpreting it here would change the
        meaning of code that was written against the native API.
        """
        method = arguments.get("method")
        if not isinstance(method, str) or not method:
            raise OperationError("invalid_arguments", "method must be a non-empty string")
        if method.startswith("_"):
            # Closes __class__/__globals__/__reduce__ traversal off the live object.
            raise OperationError("method_not_allowed", "private and dunder attributes are not reachable")
        target = self._resolve_target(arguments.get("target", "resolve"))
        if target is None:
            raise OperationError("not_found", "the requested object is not available right now")
        fn = getattr(target, method, None)
        if not callable(fn):
            raise OperationError(
                "capability_unavailable",
                f"{type(target).__name__} has no callable {method!r} in this Resolve build",
            )
        raw_args = arguments.get("args") or []
        if not isinstance(raw_args, list):
            raise OperationError("invalid_arguments", "args must be a list")
        if len(raw_args) > 64:
            raise OperationError("invalid_arguments", "too many arguments")
        try:
            result = fn(*[self._decode(a) for a in raw_args])
        except OperationError:
            raise
        except Exception as exc:
            raise OperationError(
                "resolve_raised",
                f"Resolve raised while running {method}: {str(exc)[:200]}",
            )
        return {"value": self._encode(result)}

    def op_list_methods(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """The real callable method names on a target.

        The proxy needs this to answer `hasattr` truthfully. Without it a
        `__getattr__`-based proxy claims every name exists, so capability
        detection — `getattr(obj, "CreateMagicMask", None)` — silently passes for
        methods this Resolve build does not have, and the failure resurfaces
        later as an unrelated error.
        """
        target = self._resolve_target(arguments.get("target", "resolve"))
        names = sorted(
            name for name in dir(target)
            if not name.startswith("_") and callable(getattr(target, name, None))
        )
        return {"type": type(target).__name__, "methods": names}

    # -- lifecycle ---------------------------------------------------------
    #
    # These stop or restart the bridge, never the project. No extra gate beyond
    # the token: a caller holding it can already drive Resolve through `call`, so
    # refusing them here would guard nothing while removing the only way to
    # recover a stale bridge without quitting Resolve.

    def _lifecycle_stop(self, mode: str) -> Dict[str, Any]:
        if self._lifecycle is None:
            raise OperationError(
                "capability_unavailable",
                "this bridge was started without a lifecycle owner, so it cannot stop itself; "
                "quit the script inside Resolve instead",
            )
        outcome = self._lifecycle(mode) or {}
        # The reply has to be written before the listener goes away, so the
        # handler returns now and the teardown happens in the serve loop.
        return {"stopping": True, "mode": mode, **outcome}

    def op_shutdown(self, _arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Stop the listener so Workspace ▸ Scripts can start it again."""
        return self._lifecycle_stop("exit")

    def op_reload(self, _arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Re-import the runtime from disk and serve again, in the same process.

        The in-Resolve runtime is a copy taken at install time, so a repository
        change leaves the bridge stale with no way back except quitting Resolve.
        This closes that loop: re-run the installer, call `reload`, and the new
        code is live without touching the UI.

        Handles do not survive: the new `ResolveOperations` has a new session, so
        a client's existing proxies get `stale_handle` and re-fetch. That is the
        designed behaviour — silently resolving an old handle against a new object
        graph is the wrong-target failure the session scoping exists to prevent.
        """
        return self._lifecycle_stop("reload")

    def op_release_handles(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Drop handles a client no longer needs, or all of them."""
        handles = arguments.get("handles")
        if handles is None:
            count = len(self._handles)
            self._handles.clear()
            return {"released": count, "all": True}
        if not isinstance(handles, list):
            raise OperationError("invalid_arguments", "handles must be a list")
        released = sum(1 for h in handles if self._handles.pop(h, None) is not None)
        return {"released": released, "all": False, "held": len(self._handles)}


def make_dispatch(operations: ResolveOperations) -> Callable[[str, Dict[str, Any]], Any]:
    """Adapt a `ResolveOperations` into the callable `Bridge` expects."""

    def dispatch(operation: str, arguments: Dict[str, Any]) -> Any:
        return operations.dispatch(operation, arguments)

    return dispatch
