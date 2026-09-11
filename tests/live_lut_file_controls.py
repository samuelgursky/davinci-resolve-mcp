"""Live LUT file controls against the real Resolve LUT directory.

Run from the repo root:
    python tests/live_lut_file_controls.py

Needs no running Resolve — these are filesystem operations on the master LUT
root, which is the point: LUT discovery works whether or not Resolve is up.

Everything this writes goes into the namespaced MCP/ subfolder and is removed
again. Stock and vendor LUTs are read but never modified.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

NAME = "mcp_live_probe.cube"
IDENTITY_CUBE = """TITLE "mcp live probe"
LUT_3D_SIZE 2
DOMAIN_MIN 0.0 0.0 0.0
DOMAIN_MAX 1.0 1.0 1.0
0.0 0.0 0.0
1.0 0.0 0.0
0.0 1.0 0.0
1.0 1.0 0.0
0.0 0.0 1.0
1.0 0.0 1.0
0.0 1.0 1.0
1.0 1.0 1.0
"""


def main():
    import src.server as s
    from src.granular import graph as g
    from src.utils import lut_files

    rows = []
    root = lut_files.master_lut_dir()
    rows.append({"case": "master LUT root", "path": root, "exists": os.path.isdir(root)})
    if not os.path.isdir(root):
        raise SystemExit(f"Master LUT directory not found: {root}")

    # Discovery, both interfaces, against the user's real LUT tree.
    compound_list = s.lut("list", {})
    granular_list = g.list_lut_files()
    same = ([r["set_lut_path"] for r in compound_list["luts"]]
            == [r["set_lut_path"] for r in granular_list["luts"]])
    rows.append({
        "case": "list agrees across both interfaces",
        "count": compound_list["count"],
        "identical": same,
        "writable_entries": sum(1 for r in compound_list["luts"] if r["writable"]),
        "sample_paths": [r["set_lut_path"] for r in compound_list["luts"][:3]],
    })

    before = compound_list["count"]
    try:
        installed = s.lut("install", {"name": NAME, "source": IDENTITY_CUBE})
        rows.append({"case": "compound install", "success": installed.get("success"),
                     "set_lut_path": installed.get("set_lut_path"),
                     "bytes": installed.get("bytes")})

        after = s.lut("list", {})
        listed = [r for r in after["luts"] if r["set_lut_path"] == installed.get("set_lut_path")]
        rows.append({"case": "installed LUT appears in the listing and is writable",
                     "found": bool(listed),
                     "writable": listed[0]["writable"] if listed else None,
                     "count_delta": after["count"] - before})

        summary = g.read_lut_file(installed["set_lut_path"])
        rows.append({"case": "granular read reports shape, not the table",
                     "parsed": summary.get("parsed"), "size": summary.get("size"),
                     "entries": summary.get("entries"),
                     "table_returned": "table" in summary})

        clobber = s.lut("install", {"name": NAME, "source": IDENTITY_CUBE})
        rows.append({"case": "re-install without overwrite is refused",
                     "refused": "error" in clobber})

        traversal = g.install_lut_file("../escaped.cube", source=IDENTITY_CUBE)
        rows.append({"case": "path traversal refused", "refused": "error" in traversal,
                     "escaped_file_exists": os.path.exists(
                         os.path.join(os.path.dirname(root.rstrip("/")), "escaped.cube"))})

        stock = [r for r in after["luts"] if not r["writable"]]
        protected = None
        if stock:
            attempt = s.lut("remove", {"name": os.path.basename(stock[0]["set_lut_path"])})
            protected = ("error" in attempt and os.path.isfile(
                os.path.join(root, *stock[0]["set_lut_path"].split("/"))))
        rows.append({"case": "a stock LUT cannot be removed through this server",
                     "stock_luts_present": len(stock), "protected": protected})
    finally:
        removed = s.lut("remove", {"name": NAME})
        rows.append({"case": "cleanup", "removed": removed.get("removed"),
                     "success": removed.get("success"),
                     "file_gone": not os.path.exists(
                         os.path.join(lut_files.writable_dir(), NAME))})

    final = s.lut("list", {})
    rows.append({"case": "final count matches the starting count",
                 "before": before, "after": final["count"]})

    print(json.dumps({"rows": rows}, indent=2))
    ok = (rows[1]["identical"]
          and rows[2]["success"] and rows[3]["found"] and rows[3]["writable"]
          and rows[3]["count_delta"] == 1
          and rows[4]["parsed"] and not rows[4]["table_returned"]
          and rows[5]["refused"]
          and rows[6]["refused"] and not rows[6]["escaped_file_exists"]
          and (rows[7]["protected"] is not False)
          and rows[8]["success"] and rows[8]["file_gone"]
          and rows[9]["before"] == rows[9]["after"])
    print("RESULT:", "pass" if ok else "review the rows above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
