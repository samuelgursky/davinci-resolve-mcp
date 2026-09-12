"""LUT file discovery and safe installation under Resolve's master LUT root.

The server could already put a LUT on a node (`graph set_lut`) and pull one out
of a grade (`export_lut`), but nothing could answer the question `set_lut`
raises: *which LUTs exist?* There was no listing, no install and no removal,
even though the same needs for DCTL shaders are served by the `dctl` tool and
the two live in the same directory tree. Blackmagic's own MCP exposes
`list_luts`, `generate_lut` and `delete_lut`; this closes that gap.

Two rules shape everything here.

**Reads roam, writes do not.** Listing walks the whole master LUT root so
stock, vendor and hand-installed LUTs are all discoverable. Writing and
deleting are confined to one namespaced subfolder, `MCP/`, which is the same
confinement Blackmagic's own MCP applies to `generate_lut`/`delete_lut`. Stock
and vendor LUTs are never modified or removed by this server.

**Master root, not the user LUT dir.** `Graph.SetLUT()` resolves relative names
— and even absolute paths — only against the master root, never the per-user
dir the `dctl` tool installs into. That is measured behaviour recorded in
`lut_paths`, so installs land where `set_lut` can actually reach them, and
every listing reports the master-relative path in the exact form `set_lut`
accepts.

Deliberately **not** ported from the official MCP: its `generate_lut` takes a
Python function body from the caller and executes it per lattice point. This
server does not accept caller-supplied code, so LUT authoring here is limited
to declarative operations already implemented in `cube_lut` — writing a
provided `.cube` and attenuating an existing one toward identity.
"""

import os
from typing import Any, Dict, List, Optional, Tuple

from src.utils.lut_paths import MASTER_LUT_RELOCATE_SUBDIR, master_lut_dir

# The extensions Resolve's LUT browser picks up, matching the official MCP's list.
LUT_EXTENSIONS = (".3dl", ".cube", ".dat", ".lut", ".olut")

# Writes and deletes are confined to this subfolder of the master root.
WRITABLE_SUBDIR = MASTER_LUT_RELOCATE_SUBDIR


class LutPathError(ValueError):
    """A caller-supplied LUT name or subdir could not be used safely."""


def writable_dir() -> str:
    """The one directory this server installs into and deletes from."""
    return os.path.join(master_lut_dir(), WRITABLE_SUBDIR)


def normalize_relative(name: str, *, default_ext: Optional[str] = None) -> str:
    """Validate a caller-supplied LUT name and return it as a POSIX relative path.

    Rejects absolute paths, drive letters, empty segments and any `.`/`..`
    segment, so a name can never escape the directory it is resolved against.
    """
    if not isinstance(name, str) or not name.strip():
        raise LutPathError("name is required")
    candidate = name.strip().replace("\\", "/")
    if candidate.startswith("/") or (len(candidate) > 1 and candidate[1] == ":"):
        raise LutPathError(f"name must be relative, not an absolute path: {name!r}")
    parts = [segment.strip() for segment in candidate.split("/") if segment.strip()]
    if not parts:
        raise LutPathError("name is required")
    for segment in parts:
        if segment in (".", ".."):
            raise LutPathError(f"unsafe path segment in {name!r}: {segment!r}")
    relative = "/".join(parts)
    if default_ext and not os.path.splitext(relative)[1]:
        relative += default_ext
    ext = os.path.splitext(relative)[1].lower()
    if ext not in LUT_EXTENSIONS:
        raise LutPathError(
            f"{relative!r} is not a LUT file. Expected one of: "
            + ", ".join(LUT_EXTENSIONS)
        )
    return relative


def resolve_writable(name: str, *, default_ext: Optional[str] = ".cube") -> Tuple[str, str]:
    """Return ``(absolute_path, master_relative_path)`` inside the writable subdir.

    The second value is what `graph set_lut` wants, so a caller can install and
    then apply without constructing a path by hand.
    """
    relative = normalize_relative(name, default_ext=default_ext)
    absolute = os.path.join(writable_dir(), *relative.split("/"))
    root = os.path.realpath(writable_dir())
    if os.path.commonpath([root, os.path.realpath(os.path.dirname(absolute)) or root]) != root:
        raise LutPathError(f"{name!r} resolves outside {WRITABLE_SUBDIR}/")
    return absolute, f"{WRITABLE_SUBDIR}/{relative}"


def list_luts(subdir: Optional[str] = None) -> Dict[str, Any]:
    """Walk the master LUT root and report every LUT Resolve would see.

    Each entry carries `set_lut_path` — the master-relative form `set_lut`
    resolves — plus `writable`, which says whether this server may remove it.
    """
    root = master_lut_dir()
    base = root
    if subdir:
        relative_parts = [s for s in subdir.replace("\\", "/").split("/") if s.strip()]
        for segment in relative_parts:
            if segment in (".", ".."):
                raise LutPathError(f"unsafe subdir segment: {segment!r}")
        base = os.path.join(root, *relative_parts)
    if not os.path.isdir(base):
        return {"lut_dir": root, "searched": base, "exists": False, "luts": [], "count": 0}

    writable_root = os.path.realpath(writable_dir())
    found: List[Dict[str, Any]] = []
    for current, _dirs, files in os.walk(base):
        for filename in sorted(files):
            if os.path.splitext(filename)[1].lower() not in LUT_EXTENSIONS:
                continue
            absolute = os.path.join(current, filename)
            relative = os.path.relpath(absolute, root).replace(os.sep, "/")
            try:
                size = os.path.getsize(absolute)
            except OSError:
                size = None
            try:
                is_writable = os.path.realpath(current).startswith(writable_root)
            except OSError:
                is_writable = False
            found.append({
                "name": filename,
                "set_lut_path": relative,
                "bytes": size,
                "writable": is_writable,
            })
    found.sort(key=lambda row: row["set_lut_path"])
    return {
        "lut_dir": root,
        "searched": base,
        "exists": True,
        "writable_dir": writable_dir(),
        "luts": found,
        "count": len(found),
    }


def install_lut(name: str, *, source: Optional[str] = None,
                source_path: Optional[str] = None,
                overwrite: bool = False) -> Dict[str, Any]:
    """Write a LUT into the writable subdir from text or by copying a file.

    Refuses an existing destination unless `overwrite` is set, so an install
    never silently replaces something already in use.
    """
    if (source is None) == (source_path is None):
        raise LutPathError("provide exactly one of source (text) or source_path (a file to copy)")
    absolute, set_lut_path = resolve_writable(name)
    existed = os.path.exists(absolute)
    if existed and not overwrite:
        raise LutPathError(
            f"{set_lut_path} already exists. Pass overwrite=true to replace it."
        )
    if source_path is not None:
        if not os.path.isfile(source_path):
            raise LutPathError(f"source_path not found: {source_path}")
        with open(source_path, "r", encoding="utf-8", errors="strict") as handle:
            payload = handle.read()
    else:
        payload = source
    if not payload.strip():
        raise LutPathError("refusing to install an empty LUT")
    os.makedirs(os.path.dirname(absolute), exist_ok=True)
    with open(absolute, "w", encoding="utf-8") as handle:
        handle.write(payload)
    return {
        "success": True,
        "path": absolute,
        "set_lut_path": set_lut_path,
        "bytes": os.path.getsize(absolute),
        # Whether a file was actually replaced, not whether the caller allowed
        # it: `payload is not None` is always true here, so this reported a
        # replacement for every overwrite=true install, including the ones that
        # landed on an empty MCP/. This flag is the record of what an install
        # destroyed -- execution_lifecycle rates `lut install` on the fact that
        # it "can replace with overwrite=true" -- so it has to be the observed
        # pre-state, not the permission.
        "overwritten": existed,
        "note": ("Call project_settings(action='refresh_luts') so Resolve picks up "
                 "the new file before applying it."),
    }


def remove_lut(name: str) -> Dict[str, Any]:
    """Delete a LUT from the writable subdir only.

    Stock and vendor LUTs live outside it and cannot be removed through here.
    """
    absolute, set_lut_path = resolve_writable(name)
    if not os.path.isfile(absolute):
        raise LutPathError(
            f"{set_lut_path} is not present in {WRITABLE_SUBDIR}/. This server only "
            "removes LUTs it can install; stock and vendor LUTs are left alone."
        )
    os.remove(absolute)
    return {"success": True, "removed": set_lut_path, "path": absolute}


def read_lut_summary(name: str) -> Dict[str, Any]:
    """Summarize a `.cube` without returning the whole table.

    A 65-cube is 274,625 rows; handing that back through a tool result is
    useless to a caller and expensive, so this reports shape and header only.
    """
    from src.utils import cube_lut

    root = master_lut_dir()
    relative = normalize_relative(name)
    absolute = os.path.join(root, *relative.split("/"))
    if not os.path.isfile(absolute):
        raise LutPathError(f"LUT not found under the master LUT dir: {relative}")
    if os.path.splitext(absolute)[1].lower() != ".cube":
        return {
            "set_lut_path": relative,
            "path": absolute,
            "bytes": os.path.getsize(absolute),
            "parsed": False,
            "note": "Only 3D .cube files are parsed; other formats report size only.",
        }
    parsed = cube_lut.read_cube(absolute)
    return {
        "set_lut_path": relative,
        "path": absolute,
        "bytes": os.path.getsize(absolute),
        "parsed": True,
        "size": parsed["size"],
        "title": parsed["title"],
        "domain_min": parsed["domain_min"],
        "domain_max": parsed["domain_max"],
        "entries": int(parsed["size"]) ** 3,
    }


def attenuate_lut(source: str, strength: float, name: str) -> Dict[str, Any]:
    """Blend an existing `.cube` toward identity and install the result.

    Reads from anywhere under the master root, writes only into the writable
    subdir. `cube_lut` refuses a non-unit domain, because identity is only
    identity on 0..1.
    """
    from src.utils import cube_lut

    try:
        value = float(strength)
    except (TypeError, ValueError):
        raise LutPathError("strength must be a number between 0 and 1")
    if not 0.0 <= value <= 1.0:
        raise LutPathError(f"strength must be between 0 and 1, got {value}")
    root = master_lut_dir()
    source_relative = normalize_relative(source)
    source_absolute = os.path.join(root, *source_relative.split("/"))
    if not os.path.isfile(source_absolute):
        raise LutPathError(f"source LUT not found under the master LUT dir: {source_relative}")
    absolute, set_lut_path = resolve_writable(name)
    if os.path.exists(absolute):
        raise LutPathError(f"{set_lut_path} already exists. Choose another name.")
    os.makedirs(os.path.dirname(absolute), exist_ok=True)
    summary = cube_lut.attenuate_file(source_absolute, value, absolute,
                                      title_suffix=f"@{value:g}")
    summary.update({
        "success": True,
        "source": source_relative,
        "strength": value,
        "set_lut_path": set_lut_path,
        "note": ("Call project_settings(action='refresh_luts') so Resolve picks up "
                 "the new file before applying it."),
    })
    return summary
