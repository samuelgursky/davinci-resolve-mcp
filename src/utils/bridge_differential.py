"""Differential qualification for the in-app bridge: two transports, one answer.

The bridge is a *transport*. It is correct exactly when a call through it is
indistinguishable from the same call over Blackmagic's own scripting API. That is
a property you can test mechanically rather than argue about, and this module is
the machinery for it:

1. **Enumerate** the Resolve API surface the MCP tools actually call, by
   intersecting the documented API with what the source really invokes. Testing
   the whole documented API would waste effort on methods we never reach; testing
   an ad-hoc list would miss the ones we do.
2. **Plan** a call for each method that can be driven without side effects, by
   walking the live object graph from `resolve` outwards.
3. **Normalise** each result into a comparable form — live objects become their
   shape, not their address, since two transports necessarily mint different
   handles for the same object.
4. **Diff** the two runs and report, including what could *not* be exercised and
   why. Silent coverage gaps read as "everything passed".

## Why the comparison has to run against one Resolve

External scripting is Studio-gated, so a free edition can only be reached through
the bridge — there is no native side to diff against. But Studio speaks *both*,
so the differential runs there: one application, one project, one object graph,
two ways in. Anything that differs is the transport's doing, which is the whole
question. On the free edition the same plan runs bridge-only, which proves
reachability and shape rather than equivalence.

## What "identical" has to tolerate

Nothing structural. Handles differ by construction and are normalised away.
Everything else — types, values, ordering, None-vs-False — is compared exactly,
because every one of those distinctions has been a real bug in this codebase:
False-means-failure, None-means-absent, and ordering that a caller relies on.

A small set of readings are genuinely time-varying (playhead position, render
progress). Those are compared by *type only*, and each one is named here rather
than pattern-matched, so the exemption list stays auditable.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
API_DOCS = REPO_ROOT / "docs" / "reference" / "resolve_scripting_api.txt"
SOURCE_ROOTS = ("src",)

#: Readings that legitimately differ between two calls a moment apart. Compared
#: by type instead of value. Named individually — a regex over "Timecode" or
#: "Progress" would quietly excuse a real difference in something else.
VOLATILE_METHODS = frozenset({
    "GetCurrentTimecode",
    "GetCurrentVideoItem",
    "GetCurrentVideoTimecode",
    "IsRenderingInProgress",
    "GetRenderJobStatus",
    "IsPlayheadOnVideoFrame",
})

#: Never invoked by the harness, whatever the enumeration says. These either
#: change the project, touch the filesystem, or block on UI. The write paths are
#: exercised by named scenarios instead, where the setup and teardown are
#: explicit and a failure can be cleaned up.
_UNSAFE_VERBS = (
    "Delete", "Remove", "Create", "Add", "Set", "Import", "Export", "Save",
    "Load", "Append", "Insert", "Paste", "Copy", "Duplicate", "Move", "Render",
    "Start", "Stop", "Open", "Close", "Quit", "Restore", "Archive", "Refresh",
    "Transcribe", "Apply", "Link", "Unlink", "Relink", "Replace", "Convert",
    "Detect", "Generate", "Auto", "Reset", "Clear", "Enable", "Disable",
)

_CLASS_HEADING_RE = re.compile(r"^([A-Z][A-Za-z]+)\s*$")
_METHOD_RE = re.compile(r"^\s+([A-Z][A-Za-z0-9_]+)\s*\(")


# ── 1. what the tools actually call ──────────────────────────────────────────


def documented_methods(docs_path: Path = API_DOCS) -> Dict[str, Set[str]]:
    """`{class_name: {method, ...}}` from Blackmagic's own API reference.

    Deprecated and unsupported sections are cut: a bridge is not obliged to carry
    calls the vendor has withdrawn, and including them would report failures that
    say nothing about the transport.
    """
    classes: Dict[str, Set[str]] = {}
    text = docs_path.read_text(encoding="utf-8", errors="replace")
    for marker in ("\nDeprecated Resolve API Functions", "\nUnsupported Resolve API Functions"):
        index = text.find(marker)
        if index != -1:
            text = text[:index]
    current: Optional[str] = None
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line.startswith(" "):
            match = _CLASS_HEADING_RE.match(line)
            current = match.group(1) if match and len(match.group(1).split()) == 1 else None
            continue
        if current is None:
            continue
        method = _METHOD_RE.match(line)
        if method:
            classes.setdefault(current, set()).add(method.group(1))
    return classes


def called_methods(roots: Sequence[str] = SOURCE_ROOTS) -> Dict[str, Set[str]]:
    """`{method: {file, ...}}` — Resolve API methods this codebase invokes.

    AST rather than grep: a method name inside a docstring, a log line or a tool
    description is not a call, and counting it would inflate the surface the
    bridge is asked to carry.
    """
    documented = {m for methods in documented_methods().values() for m in methods}
    found: Dict[str, Set[str]] = {}
    for root in roots:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:  # pragma: no cover - a broken file is its own alarm
                continue
            relative = str(path.relative_to(REPO_ROOT))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                target = node.func
                name = None
                if isinstance(target, ast.Attribute):
                    name = target.attr
                elif isinstance(target, ast.Name):
                    name = target.id
                if name in documented:
                    found.setdefault(name, set()).add(relative)
                # getattr(obj, "SetLUT", None) is a capability check, and the
                # bridge has to answer it as truthfully as a call.
                if isinstance(target, ast.Name) and target.id == "getattr" and node.args[1:]:
                    probe = node.args[1]
                    if isinstance(probe, ast.Constant) and probe.value in documented:
                        found.setdefault(probe.value, set()).add(relative)
    return found


def is_safe_to_probe(method: str) -> bool:
    """Can the harness call this blind, on a project it does not own?

    Read-only by name is a weak test in general — but here it is backed by the
    rule that anything failing it is not skipped, it is routed to a named
    scenario with explicit setup and teardown. The conservative answer costs
    coverage in one place and buys it back in the other.
    """
    if method.startswith(_UNSAFE_VERBS):
        return False
    return method.startswith(("Get", "Is", "Has", "List", "Find", "Count"))


def probe_surface(roots: Sequence[str] = SOURCE_ROOTS) -> Dict[str, Any]:
    """The enumeration, split into what can be probed and what cannot."""
    calls = called_methods(roots)
    safe = sorted(m for m in calls if is_safe_to_probe(m))
    unsafe = sorted(m for m in calls if not is_safe_to_probe(m))
    return {
        "called": sorted(calls),
        "safe_to_probe": safe,
        "needs_a_scenario": unsafe,
        "sources": {m: sorted(files) for m, files in calls.items()},
    }


# ── 2. walking the live object graph ─────────────────────────────────────────


#: How the harness reaches each object worth probing, as a chain of zero-argument
#: calls from the Resolve root. Kept declarative so the same walk runs over either
#: transport without the driver knowing which it holds.
#: `("[]", (index,))` takes an element of a returned list. Without it the walk
#: stops at the collection accessors and never reaches TimelineItem,
#: MediaPoolItem or Graph — which between them carry most of the read surface
#: worth qualifying (LUTs, node graphs, source timings, metadata).
_INDEX = "[]"
#: Pick the first element of a returned list for which `method()` is truthy.
#: Indexing blindly is not good enough: a timeline's first video item is often a
#: generator or a title, which has no MediaPoolItem and answers None to every
#: node-graph question. Measured on a real timeline — `GetNumNodes` and
#: `GetNodeGraph` both None on an SMPTE Color Bar, and 1 and a live graph on the
#: clip sitting next to it. Taking index 0 therefore reported the whole grading
#: surface as unreachable, which is the silent coverage gap this module exists to
#: refuse.
_FIRST_WITH = "[first-with]"

_PM = ("GetProjectManager", ())
_PROJECT = (_PM, ("GetCurrentProject", ()))
_POOL = _PROJECT + (("GetMediaPool", ()),)
_TIMELINE = _PROJECT + (("GetCurrentTimeline", ()),)
_TIMELINE_ITEM = _TIMELINE + (("GetItemListInTrack", ("video", 1)),
                              (_FIRST_WITH, ("GetMediaPoolItem",)))
_GALLERY = _PROJECT + (("GetGallery", ()),)

OBJECT_GRAPH: Tuple[Tuple[str, Tuple[Any, ...]], ...] = (
    ("resolve", ()),
    ("project_manager", (_PM,)),
    ("project", _PROJECT),
    ("media_pool", _POOL),
    ("root_folder", _POOL + (("GetRootFolder", ()),)),
    ("media_pool_item", _POOL + (("GetRootFolder", ()), ("GetClipList", ()), (_INDEX, (0,)))),
    ("timeline", _TIMELINE),
    ("timeline_node_graph", _TIMELINE + (("GetNodeGraph", ()),)),
    ("timeline_item", _TIMELINE_ITEM),
    ("timeline_item_node_graph", _TIMELINE_ITEM + (("GetNodeGraph", ()),)),
    # Unreachable until a project actually has a colour group. Listed anyway so
    # its three methods report as "no such object here" rather than vanishing
    # from the coverage count with no explanation.
    ("color_group", _PROJECT + (("GetColorGroupsList", ()), (_INDEX, (0,)))),
    ("gallery", _GALLERY),
    ("gallery_still_album", _GALLERY + (("GetCurrentStillAlbum", ()),)),
    ("media_storage", (("GetMediaStorage", ()),)),
)


def walk(resolve: Any, chain: Iterable[Tuple[str, Tuple[Any, ...]]]) -> Any:
    """Follow a chain from the Resolve root, returning None if it breaks.

    A missing link is a legitimate state — no project open, no current timeline,
    an empty track — and must not read as a transport failure, so it returns None
    rather than raising. The distinction matters: the report separates "this
    object was unreachable" from "this method disagreed".
    """
    current = resolve
    for method, args in chain:
        if current is None:
            return None
        if method == _INDEX:
            index = args[0]
            if not isinstance(current, (list, tuple)) or len(current) <= index:
                return None
            current = current[index]
            continue
        if method == _FIRST_WITH:
            if not isinstance(current, (list, tuple)):
                return None
            probe = args[0]
            chosen = None
            for candidate in current:
                try:
                    if getattr(candidate, probe, lambda: None)():
                        chosen = candidate
                        break
                except Exception:  # noqa: BLE001 - an unusable candidate, not a verdict
                    continue
            if chosen is None:
                return None
            current = chosen
            continue
        function = getattr(current, method, None)
        if function is None:
            return None
        try:
            current = function(*args)
        except Exception:  # noqa: BLE001 - an unreachable branch, not a verdict
            return None
    return current


# ── 3. normalising a result so two transports can be compared ────────────────


def normalise(value: Any, *, depth: int = 0) -> Any:
    """Reduce a result to what two transports must agree on.

    Live objects become a marker rather than a value: the bridge returns a
    handle, native scripting returns a `PyRemoteObject`, and neither address says
    anything about correctness. Everything else is preserved exactly — including
    the difference between None and False, which this codebase has been bitten by
    often enough to make it a compared value rather than a detail.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        # Two transports serialise the same double identically; rounding only
        # guards against a JSON round trip introducing a last-bit difference.
        return round(value, 9)
    if depth > 6:
        return "<deep>"
    if isinstance(value, (list, tuple)):
        return [normalise(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        return {str(k): normalise(v, depth=depth + 1) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    return "<object>"


def describe(value: Any) -> str:
    """A type label that survives the transport difference."""
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (list, tuple)):
        return "list[%d]" % len(value)
    if isinstance(value, dict):
        return "dict[%d]" % len(value)
    if isinstance(value, (int, float, str)):
        return type(value).__name__
    return "object"


# ── 4. running and diffing ───────────────────────────────────────────────────


def probe_one(target: Any, method: str) -> Dict[str, Any]:
    """Call one method, recording the outcome rather than propagating it.

    A raising method is a *result* here, not an abort: whether both transports
    raise the same way is exactly what the diff is for.
    """
    function = getattr(target, method, None)
    if function is None:
        return {"outcome": "absent"}
    try:
        value = function()
    except Exception as exc:  # noqa: BLE001 - the exception IS the observation
        return {"outcome": "raised", "error": type(exc).__name__, "message": str(exc)[:200]}
    return {"outcome": "returned", "value": normalise(value), "type": describe(value)}


def run_probes(resolve: Any, methods: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """Every enumerated safe method, against every object that has it.

    Keyed `object.method` so the diff can say *where* two transports disagreed,
    not merely that they did.
    """
    results: Dict[str, Dict[str, Any]] = {}
    for label, chain in OBJECT_GRAPH:
        target = walk(resolve, chain)
        if target is None:
            results[f"{label}.<unreachable>"] = {"outcome": "unreachable"}
            continue
        for method in methods:
            if getattr(target, method, None) is None:
                continue  # not on this object; absence is reported by the diff
            results[f"{label}.{method}"] = probe_one(target, method)
    return results


def compare(native: Dict[str, Dict[str, Any]], bridged: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Diff two probe runs. Empty `differences` is the pass condition."""
    differences: List[Dict[str, Any]] = []
    for key in sorted(set(native) | set(bridged)):
        left, right = native.get(key), bridged.get(key)
        if left is None or right is None:
            differences.append({
                "key": key, "kind": "only_one_transport_reached_it",
                "native": left, "bridge": right,
            })
            continue
        method = key.rsplit(".", 1)[-1]
        if method in VOLATILE_METHODS:
            # Value moves on its own; the transport is still on the hook for
            # returning the same *kind* of thing.
            if left.get("type") != right.get("type") or left["outcome"] != right["outcome"]:
                differences.append({"key": key, "kind": "volatile_type_mismatch",
                                    "native": left.get("type"), "bridge": right.get("type")})
            continue
        if left != right:
            differences.append({"key": key, "kind": "value_mismatch",
                                "native": left, "bridge": right})
    agreed = len(set(native) & set(bridged)) - len(
        [d for d in differences if d["kind"] != "only_one_transport_reached_it"]
    )
    return {
        "compared": len(set(native) | set(bridged)),
        "agreed": agreed,
        "differences": differences,
        "identical": not differences,
    }


def coverage_report(surface: Dict[str, Any], results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """What the run actually exercised — and what it did not, with the reason.

    A harness that reports only its passes reads as complete when it is not, so
    the untouched methods are named. Most of them are writes routed to scenarios;
    the rest are methods no reachable object carried.
    """
    exercised = {key.rsplit(".", 1)[-1] for key in results if not key.endswith(".<unreachable>")}
    safe = set(surface["safe_to_probe"])
    unreachable = sorted(key.split(".", 1)[0] for key in results if key.endswith(".<unreachable>"))
    return {
        "called_by_tools": len(surface["called"]),
        "safe_to_probe": len(safe),
        "exercised": len(safe & exercised),
        "not_exercised": sorted(safe - exercised),
        # Named, because "this project has no colour group" and "the bridge
        # cannot reach colour groups" are different findings and a bare count
        # of exercised methods conflates them.
        "unreachable_objects": unreachable,
        "needs_a_scenario": surface["needs_a_scenario"],
    }
