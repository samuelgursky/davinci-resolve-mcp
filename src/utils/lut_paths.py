"""Master LUT directory resolution for Graph.SetLUT().

Resolve's Graph.SetLUT() resolves relative LUT names -- and even absolute
paths -- ONLY against the master (system) LUT root, NOT the per-user LUT dir
that the dctl tool installs into. Verified live on Resolve Studio 19.1.3.7:
SetLUT succeeds for a LUT in the master dir (by relative or subfolder path) and
returns False for the same file in the user dir, even after RefreshLUTList and
even via an absolute user-dir path. (The originating report, PR #90, observed
the same behavior on Studio 21.0.2.) These helpers relocate a user-dir LUT into
a namespaced subfolder of the master dir so SetLUT can resolve it.
"""

import os
import platform
import shutil
from typing import List, Optional

from src.utils.platform import get_resolve_plugin_paths

# Subfolder under the master LUT root where relocated LUTs are staged. SetLUT
# resolves relative paths against the master root, so a subfolder path like
# "MCP/Foo.cube" works AND avoids clobbering stock/vendor LUTs that share a
# basename (e.g. InstantC.cube). Verified live on Resolve Studio 19.1.3.7.
MASTER_LUT_RELOCATE_SUBDIR = "MCP"


def master_lut_dir() -> str:
    """Return Resolve's master (system) LUT directory for this platform."""
    plat = platform.system().lower()
    if plat == "windows":
        programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return os.path.join(programdata, "Blackmagic Design",
                            "DaVinci Resolve", "Support", "LUT")
    if plat == "linux":
        for cand in ("/opt/resolve/LUT", "/home/resolve/LUT"):
            if os.path.isdir(cand):
                return cand
        return "/opt/resolve/LUT"
    # darwin / default
    return "/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT"


def _user_lut_dir() -> Optional[str]:
    """Return the per-user LUT dir (where dctl install writes), or None."""
    try:
        return get_resolve_plugin_paths()["dctl_dir"]
    except Exception:
        return None


def ensure_lut_in_master(lut_path: str) -> Optional[str]:
    """Make a LUT resolvable by Graph.SetLUT().

    Locates the file named by lut_path (absolute, user LUT dir, or already in
    the master dir), copies it into a namespaced subfolder of the master LUT
    dir when needed, and returns the master-relative path (forward slashes, as
    GetLUT reports) to hand back to SetLUT. Returns None if the source cannot
    be found or the master dir is not writable.
    """
    master = master_lut_dir()
    base = os.path.basename(lut_path)
    candidates: List[str] = []
    if os.path.isabs(lut_path):
        candidates.append(lut_path)
    else:
        user_dir = _user_lut_dir()
        if user_dir:
            candidates.append(os.path.join(user_dir, lut_path))
        candidates.append(os.path.join(master, lut_path))
    src = next((c for c in candidates if os.path.isfile(c)), None)
    if not src:
        return None
    dst_dir = os.path.join(master, MASTER_LUT_RELOCATE_SUBDIR)
    dst = os.path.join(dst_dir, base)
    if os.path.abspath(src) != os.path.abspath(dst):
        try:
            os.makedirs(dst_dir, exist_ok=True)
            shutil.copy2(src, dst)
        except Exception:
            return None
    return f"{MASTER_LUT_RELOCATE_SUBDIR}/{base}"
