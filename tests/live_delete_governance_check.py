"""Live validation for catastrophic media-pool delete governance (EX2/EX3).

STRICTLY NON-DESTRUCTIVE: it calls media_pool('delete_clips', …) WITHOUT a
confirm_token, which by design returns a confirmation_required envelope and
deletes nothing. It then re-lists the media pool to PROVE the clip still exists.
It never passes a token, so no deletion is ever performed.

Run:
  PYTHONPATH=. venv/bin/python tests/live_delete_governance_check.py
"""
import sys

import src.server as s
from src.utils.destructive_hook import is_destructive


def main() -> int:
    r = s.get_resolve()
    if r is None:
        print("FAIL: no Resolve")
        return 1
    pm = r.GetProjectManager()
    proj = pm.GetCurrentProject()
    mp = proj.GetMediaPool()
    root = mp.GetRootFolder()
    clips = root.GetClipList() or []
    print(f"Connected: {proj.GetName()} — {len(clips)} root clips")
    if not clips:
        print("SKIP: no clips to exercise the gating issue-path")
        return 0

    failures = []

    # EX2: registry recognizes the real compound deletes as destructive (archived).
    for action in ("delete_clips", "delete_folders", "delete_timelines"):
        if not is_destructive("media_pool", action):
            failures.append(f"is_destructive media_pool.{action} should be True (EX2)")

    target_id = clips[0].GetUniqueId()
    target_name = clips[0].GetName()
    print(f"Issue-token target clip: {target_name} ({target_id})")

    # EX3: no token -> confirmation_required, NOTHING deleted.
    out = s.media_pool("delete_clips", {"clip_ids": [target_id]})
    print(f"delete_clips (no token) -> status={out.get('status')!r} "
          f"token={'yes' if out.get('confirm_token') else 'no'} "
          f"preview_clips_lost={(out.get('preview') or {}).get('clips_lost')}")
    if out.get("status") != "confirmation_required":
        failures.append(f"expected confirmation_required, got {out.get('status')!r} / {out}")
    if not out.get("confirm_token"):
        failures.append("no confirm_token issued")

    # Prove nothing was deleted.
    after = root.GetClipList() or []
    after_ids = {c.GetUniqueId() for c in after}
    if target_id not in after_ids:
        failures.append("CLIP WAS DELETED — issue-path must never delete!")
    if len(after) != len(clips):
        failures.append(f"clip count changed {len(clips)} -> {len(after)} (must not)")

    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"\nPASS: gating active, clip preserved ({len(after)} clips intact). No deletion performed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
