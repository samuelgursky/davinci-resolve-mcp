"""Live probe for PR #113: list-key get_metadata subset + delete_timelines param error.

Read-only: get_metadata calls only; the delete_timelines calls use bad params
that must error before any lookup or deletion. No media or project mutation.
"""
import os
import sys

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

from src.utils.platform import get_resolve_paths  # noqa: E402

paths = get_resolve_paths()
os.environ["RESOLVE_SCRIPT_API"] = paths["api_path"]
os.environ["RESOLVE_SCRIPT_LIB"] = paths["lib_path"]
sys.path.insert(0, paths["modules_path"])

import src.server as s  # noqa: E402

failures = []


def check(label, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + label + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(label)


def main():
    _, proj, mp, err = s._get_mp()
    if err:
        print("Cannot reach Resolve media pool:", err)
        return 2
    print("Project:", proj.GetName())

    # Find any clip in the media pool (recursive).
    def first_clip(folder):
        for c in folder.GetClipList() or []:
            return c
        for f in folder.GetSubFolderList() or []:
            c = first_clip(f)
            if c:
                return c
        return None

    clip = first_clip(mp.GetRootFolder())
    if clip is None:
        print("SKIP get_metadata checks — no clips in media pool")
    else:
        cid = clip.GetUniqueId()
        print("Clip:", clip.GetName(), cid)

        full = s.media_pool_item("get_metadata", {"clip_id": cid})
        check("full dict when key omitted", isinstance(full.get("metadata"), dict),
              f"{len(full.get('metadata') or {})} keys")

        keys = list((full.get("metadata") or {}).keys())[:2] or ["Description", "Keywords"]
        sub_out = s.media_pool_item("get_metadata", {"clip_id": cid, "key": keys})
        md = sub_out.get("metadata")
        check("list key returns only requested subset",
              isinstance(md, dict) and sorted(md.keys()) == sorted(keys), str(md)[:120])

        one = s.media_pool_item("get_metadata", {"clip_id": cid, "key": keys[0]})
        check("string key still returns scalar",
              "metadata" in one and not isinstance(one["metadata"], dict), str(one)[:120])

        bad = s.media_pool_item("get_metadata", {"clip_id": cid, "key": []})
        check("empty list rejected", "error" in bad, str(bad.get("error", ""))[:120])

    # delete_timelines param errors — must fail before touching anything.
    r1 = s.media_pool("delete_timelines", {"timeline_names": ["NoSuchTimeline"]})
    m1 = (r1.get("error") or {}).get("message", "")
    check("timeline_names -> clear error naming timeline_ids",
          "timeline_ids" in m1 and "timeline_names" in m1, m1[:160])

    r2 = s.media_pool("delete_timelines", {})
    m2 = (r2.get("error") or {}).get("message", "")
    check("missing param -> clear error naming timeline_ids", "timeline_ids" in m2, m2[:160])

    print("RESULT:", "PASS" if not failures else f"FAIL ({failures})")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
