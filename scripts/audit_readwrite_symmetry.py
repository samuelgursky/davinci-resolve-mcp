#!/usr/bin/env python3
"""Audit read/write symmetry across the compound server's action surface.

For every mutating action (set_/add_/clear_/enable_/...) it checks whether a
matching read action (get_/list_/...) exists on the same tool, and reports the
asymmetries. The goal is to find write-without-read gaps before users have to —
the repeatable feature-discovery method behind R5.

Reads the `_unknown(action, [...])` lists in src/server.py, which enumerate every
action a tool accepts. Prints a markdown report.
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "src", "server.py")

READ_PREFIXES = ("get_", "list_", "probe_", "is_", "has_", "find_")
# `set_` is the high-signal class: a set with no get is a genuine readback gap.
# create_/add_/insert_/import_ are inherently writes that usually have no paired
# read of the same noun, so they're reported separately as low-signal.
HIGH_SIGNAL = ("set_",)
LOW_SIGNAL = ("add_", "create_", "insert_", "apply_", "import_")


def _action_lists(src: str):
    """Yield lists of action-name string literals from each _unknown(action, [...])."""
    for m in re.finditer(r"_unknown\(action,\s*\[(.*?)\]\)", src, re.DOTALL):
        names = re.findall(r'"([a-z][a-z0-9_]*)"', m.group(1))
        if names:
            yield names


def _has_read(stem: str, aset: set) -> bool:
    # Match get_<stem>, list_<stem>, and plural get_<stem>s (e.g. add_keyframe -> get_keyframes).
    candidates = {rp + stem for rp in READ_PREFIXES}
    candidates |= {rp + stem + "s" for rp in READ_PREFIXES}
    candidates |= {rp + stem.rstrip("s") for rp in READ_PREFIXES}
    return bool(candidates & aset)


def audit(src: str):
    high, low, covered, total = set(), set(), 0, 0
    for actions in _action_lists(src):
        aset = set(actions)
        for a in actions:
            for wp in HIGH_SIGNAL + LOW_SIGNAL:
                if a.startswith(wp):
                    total += 1
                    stem = a[len(wp):]
                    if _has_read(stem, aset):
                        covered += 1
                    elif wp in HIGH_SIGNAL:
                        high.add(a)
                    else:
                        low.add(a)
                    break
    return total, covered, sorted(high), sorted(low)


def main():
    src = open(SERVER, encoding="utf-8").read()
    total, covered, high, low = audit(src)
    print("# Read/Write Symmetry Audit\n")
    print(f"- write-style actions scanned: **{total}**")
    print(f"- with a matching read: **{covered}**")
    print(f"- `set_` actions with no `get_`/`list_` (real readback gaps): **{len(high)}**\n")
    if high:
        print("## High-signal gaps — `set_` with no read counterpart\n")
        for a in high:
            print(f"- `{a}`")
    print(f"\n## Low-signal (create/add/insert/import — usually expected): {len(low)}\n")
    print(", ".join(f"`{a}`" for a in low))
    return 0


if __name__ == "__main__":
    sys.exit(main())
