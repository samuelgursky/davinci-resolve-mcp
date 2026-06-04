"""Structural diff over plain JSON-able state (snapshots, specs).

A general recursive diff that classifies every leaf change as added / removed /
changed, and — crucially — aligns *lists* by a stable identity key before
comparing, so a reordered or trimmed element reads as a move/change instead of a
wholesale delete+add. This is the substrate the timeline-version diff and the
declarative-spec `plan` both build on.

Pure and Resolve-free: every function takes plain dicts/lists and returns plain
data, so it unit-tests without a live Resolve instance.

Design ported (with adaptation) from the MIT-licensed `mhadifilms/dvr` `diff.py`
`_walk` smart-alignment idea; the identity-key precedence here is tuned for our
snapshots (stable media id / shot id first, then frame/index, then name).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Identity keys tried in order when aligning two lists of dicts. The first key
# present in an element wins; alignment then matches elements sharing that key's
# value. Falls back to positional (index) alignment when no key is shared.
DEFAULT_LIST_KEYS: Tuple[str, ...] = (
    "clip_hash",            # our rename-stable canonical hash (issue #51)
    "media_pool_item_id",   # Resolve GetUniqueId — stable across renames
    "shot_id",
    "id",
    "uid",
    "frame",                # markers
    "name",
)


@dataclass
class Change:
    """One leaf-level difference. `op` ∈ {added, removed, changed}.

    `path` is a dotted/bracketed location, e.g. ``tracks.video[1].name`` or
    ``markers[frame=0].color``. `before`/`after` are the scalar values (None on
    the side where the element/leaf is absent).
    """

    op: str
    path: str
    before: Any = None
    after: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {"op": self.op, "path": self.path, "before": self.before, "after": self.after}


@dataclass
class Diff:
    changes: List[Change] = field(default_factory=list)
    left_label: str = "before"
    right_label: str = "after"

    def added(self) -> List[Change]:
        return [c for c in self.changes if c.op == "added"]

    def removed(self) -> List[Change]:
        return [c for c in self.changes if c.op == "removed"]

    def changed(self) -> List[Change]:
        return [c for c in self.changes if c.op == "changed"]

    def is_empty(self) -> bool:
        return not self.changes

    def summary(self) -> Dict[str, int]:
        return {
            "added": len(self.added()),
            "removed": len(self.removed()),
            "changed": len(self.changed()),
            "total": len(self.changes),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "left_label": self.left_label,
            "right_label": self.right_label,
            "summary": self.summary(),
            "changes": [c.to_dict() for c in self.changes],
        }


def _identity_key(item: Any, list_keys: Tuple[str, ...]) -> Optional[Tuple[str, Any]]:
    """Return (key_name, value) for the first identity key present on a dict item."""
    if not isinstance(item, dict):
        return None
    for key in list_keys:
        if key in item and item[key] is not None:
            return (key, item[key])
    return None


def _align_lists(
    left: List[Any], right: List[Any], list_keys: Tuple[str, ...]
) -> List[Tuple[Optional[Any], Optional[Any], str]]:
    """Pair up elements of two lists.

    Returns a list of (left_item, right_item, label) triples. When a shared
    identity key exists, elements are matched by it (so reorders don't read as
    delete+add); otherwise alignment is positional. `label` is the path segment
    used for the pair (``[key=value]`` for keyed, ``[i]`` for positional).
    """
    # Try keyed alignment first: only viable if *both* sides expose the same key.
    left_keyed = [(_identity_key(x, list_keys), x) for x in left]
    right_keyed = [(_identity_key(x, list_keys), x) for x in right]
    if all(k is not None for k, _ in left_keyed) and all(k is not None for k, _ in right_keyed):
        pairs: List[Tuple[Optional[Any], Optional[Any], str]] = []
        right_by_key: Dict[Tuple[str, Any], Any] = {k: v for k, v in right_keyed}  # type: ignore[misc]
        consumed: set = set()
        for k, lv in left_keyed:
            label = f"[{k[0]}={k[1]}]"  # type: ignore[index]
            if k in right_by_key:
                pairs.append((lv, right_by_key[k], label))
                consumed.add(k)
            else:
                pairs.append((lv, None, label))
        for k, rv in right_keyed:
            if k not in consumed:
                pairs.append((None, rv, f"[{k[0]}={k[1]}]"))  # type: ignore[index]
        return pairs

    # Positional fallback.
    pairs = []
    for i in range(max(len(left), len(right))):
        lv = left[i] if i < len(left) else None
        rv = right[i] if i < len(right) else None
        pairs.append((lv, rv, f"[{i}]"))
    return pairs


def _walk(left: Any, right: Any, path: str, out: List[Change], list_keys: Tuple[str, ...]) -> None:
    # Type mismatch or one side missing → record as a changed/added/removed leaf.
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            child_path = f"{path}.{key}" if path else key
            if key not in left:
                out.append(Change("added", child_path, None, right[key]))
            elif key not in right:
                out.append(Change("removed", child_path, left[key], None))
            else:
                _walk(left[key], right[key], child_path, out, list_keys)
        return

    if isinstance(left, list) and isinstance(right, list):
        for lv, rv, seg in _align_lists(left, right, list_keys):
            child_path = f"{path}{seg}"
            if lv is None:
                out.append(Change("added", child_path, None, rv))
            elif rv is None:
                out.append(Change("removed", child_path, lv, None))
            else:
                _walk(lv, rv, child_path, out, list_keys)
        return

    if left != right:
        out.append(Change("changed", path or "", left, right))


def compare(
    left: Any,
    right: Any,
    *,
    left_label: str = "before",
    right_label: str = "after",
    list_keys: Tuple[str, ...] = DEFAULT_LIST_KEYS,
) -> Diff:
    """Diff two JSON-able structures into a `Diff` of leaf-level changes."""
    out: List[Change] = []
    _walk(left, right, "", out, list_keys)
    return Diff(changes=out, left_label=left_label, right_label=right_label)
