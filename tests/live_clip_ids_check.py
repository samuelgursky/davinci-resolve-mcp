"""Live check: media_pool clip actions refuse a batch with an unresolved clip id.

Covers delete_clips, move_clips, relink and unlink (v4.8.2) and
create_timeline_from_clips, append_to_timeline, export_metadata and
auto_sync_audio (v4.8.6) against the Media Pool of the project that is open in a
running Resolve.

STRICTLY NON-DESTRUCTIVE, and it never launches Resolve:

- Connects only to a Resolve that is already running (`_try_connect`), never
  `get_resolve()`, which starts the application when nothing answers.
  `_launch_resolve` is replaced with a function that raises.
- **Tripwire.** The MediaPool handed to the actions forwards only
  GetRootFolder / GetCurrentFolder. Every other MediaPool method — DeleteClips,
  MoveClips, RelinkClips, UnlinkClips, CreateTimelineFromClips, AppendToTimeline,
  ExportMetadata, AutoSyncAudio and anything else — is recorded and answered
  False without reaching Resolve. So nothing is deleted, moved, relinked,
  unlinked, created, appended, exported or synced whatever the code under test
  does, including a regressed build. The clip and folder objects the actions
  resolve are the real ones; only their read methods are called. The project is
  read too: create_timeline_from_clips looks its (unique, generated) name up in
  the timeline list, and append_to_timeline reads the current timeline's items
  before and after for its readback.
- Confirm-token gating is forced on and no token is ever passed, so delete_clips
  can at most *issue* a token (kept in memory, never used).
- The destructive hook's project-root provider is disabled for the run, so no
  auto-run or media_pool_changes row is written into the project's analysis
  root, and the execution-trace, operation and security-audit logs go to a temp
  directory instead of the operator's trail under logs/.
- Creates nothing. SKIPs when the open project's Media Pool has no clip.

It records every clip's folder and every folder's parent before and after, plus
the probe clip's File Path, the project's timeline count and the current
timeline's item count, proves all of it is unchanged, and that no metadata file
was written.

Run (Resolve open, Preferences > General > External scripting = Local):
  venv/bin/python tests/live_clip_ids_check.py
"""
import os
import sys
import tempfile
import uuid

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

LOG_DIR = tempfile.mkdtemp(prefix="live-clip-ids-check-")
os.environ["RESOLVE_MCP_TRACE_FILE"] = os.path.join(LOG_DIR, "execution-traces.jsonl")
os.environ["RESOLVE_MCP_OPERATION_LOG_FILE"] = os.path.join(LOG_DIR, "operation-log.jsonl")

import src.server as s  # noqa: E402 - after the env redirects above
from src.utils import destructive_hook  # noqa: E402

MISSING_ID = f"__mcp_live_check_missing_clip_{uuid.uuid4().hex}__"
TIMELINE_NAME = f"__mcp_live_check_timeline_{uuid.uuid4().hex}__"
EXPORT_PATH = os.path.join(LOG_DIR, "metadata-must-not-exist.csv")
READ_METHODS = frozenset({"GetRootFolder", "GetCurrentFolder"})


class TripwireMediaPool:
    """Forwards the two reads the clip actions need; intercepts everything else."""

    def __init__(self, real):
        self._real = real
        self.intercepted = []

    def __getattr__(self, name):
        if name in READ_METHODS:
            return getattr(self._real, name)

        def blocked(*args):
            self.intercepted.append((name, args))
            return False

        return blocked


def _refuse_launch():
    raise RuntimeError("live_clip_ids_check never launches Resolve")


def _walk(folder, names=(), out=None):
    """Every folder at or below `folder` as (folder, names, parent_id)."""
    out = [(folder, names, None)] if out is None else out
    for sub in (folder.GetSubFolderList() or []):
        sub_names = names + (sub.GetName(),)
        out.append((sub, sub_names, folder.GetUniqueId()))
        _walk(sub, sub_names, out)
    return out


def _census(root):
    """({clip_id: folder_id}, {folder_id: parent_id}) for the whole Media Pool."""
    clips, folders = {}, {}
    for folder, _, parent_id in _walk(root):
        fid = folder.GetUniqueId()
        folders[fid] = parent_id
        for clip in (folder.GetClipList() or []):
            clips[clip.GetUniqueId()] = fid
    return clips, folders


def _probe_candidate(mp, root):
    """A clip in the deepest folder whose path navigates back to that folder.

    move_clips addresses its target by name; with duplicate sibling names or a
    "/" inside a name, the path could name a different folder than the clip's
    own. The tripwire makes that harmless, but the readback of which target the
    action resolved would then be wrong, so such folders are passed over.
    """
    for folder, names, _ in sorted(_walk(root), key=lambda t: -len(t[1])):
        clips = folder.GetClipList() or []
        if not clips or any("/" in n for n in names):
            continue
        path = "Master/" + "/".join(names) if names else "Master"
        nav = s._navigate_folder(mp, path)
        if nav is not None and nav.GetUniqueId() == folder.GetUniqueId():
            return clips[0], folder, path
    return None


def _err_of(out):
    return (out or {}).get("error") or {}


def main() -> int:
    s._launch_resolve = _refuse_launch
    r = s._try_connect()
    if r is None:
        print("FAIL: Resolve is not reachable over scripting. This check never launches "
              "it — open Resolve (External scripting = Local) and re-run.")
        return 1

    real_pm, real_proj, real_mp, err = s._get_mp()
    if err:
        print(f"FAIL: no Media Pool: {err}")
        return 1
    tripwire = TripwireMediaPool(real_mp)
    s._get_mp = lambda: (real_pm, real_proj, tripwire, None)
    s._confirm_token_required = lambda: True
    destructive_hook.register_project_root_provider(lambda: None)
    audit_path = os.path.join(LOG_DIR, "security-audit.jsonl")
    destructive_hook._audit_log_path = lambda: audit_path

    root = real_mp.GetRootFolder()
    candidate = _probe_candidate(real_mp, root)
    if candidate is None:
        print(f"SKIP: {real_proj.GetName()} has no clip in its Media Pool; this check creates none.")
        return 0
    clip, clip_folder, clip_path = candidate
    cid, cname, folder_id = clip.GetUniqueId(), clip.GetName(), clip_folder.GetUniqueId()
    file_path_before = clip.GetClipProperty("File Path")

    before_clips, before_folders = _census(root)
    if MISSING_ID in before_clips:
        print("FAIL: the generated missing id exists in the pool; re-run.")
        return 1
    print(f"Connected: {r.GetProductName()} {r.GetVersionString()} — project "
          f"{real_proj.GetName()!r}: {len(before_folders)} folders, {len(before_clips)} clips")
    print(f"Probe clip: {cname} ({cid}) in {clip_path}")
    print(f"Logs for this run: {LOG_DIR}")

    def timeline_state():
        snap = s._timeline_append_readback_snapshot(real_proj)
        return real_proj.GetTimelineCount(), snap.get("item_count") if snap.get("available") else None

    timelines_before, items_before = timeline_state()

    # action -> (the other params it needs, the MediaPool method a whole batch reaches)
    cases = {
        "delete_clips": ({}, "DeleteClips"),
        "move_clips": ({"target_path": clip_path}, "MoveClips"),
        "relink": ({"folder_path": LOG_DIR}, "RelinkClips"),
        "unlink": ({}, "UnlinkClips"),
        "create_timeline_from_clips": ({"name": TIMELINE_NAME}, "CreateTimelineFromClips"),
        "append_to_timeline": ({}, "AppendToTimeline"),
        "export_metadata": ({"path": EXPORT_PATH}, "ExportMetadata"),
        "auto_sync_audio": ({}, "AutoSyncAudio"),
    }

    failures = []

    def step(label, action, params, *, expect_code=None, expect_calls=0):
        n = len(tripwire.intercepted)
        out = s.media_pool(action, params)
        calls = tripwire.intercepted[n:]
        err = _err_of(out)
        state = err.get("state") or {}
        print(f"{label:<44} -> code={err.get('code')!r} status={out.get('status')!r} "
              f"success={out.get('success')!r} intercepted={[c[0] for c in calls]}")
        if expect_code is not None:
            if err.get("code") != expect_code:
                failures.append(f"{label}: expected {expect_code}, got code={err.get('code')!r} "
                                f"status={out.get('status')!r} success={out.get('success')!r} "
                                f"message={err.get('message')!r}")
            if out.get("success") is True:
                failures.append(f"{label}: reported success on a refused batch")
            if out.get("confirm_token"):
                failures.append(f"{label}: a refused batch was issued a confirm_token")
        if len(calls) != expect_calls:
            failures.append(f"{label}: expected {expect_calls} MediaPool mutation call(s), "
                            f"got {[c[0] for c in calls]}")
        return out, calls, state

    # 1. Partial batches: refused before anything reaches Resolve, naming both sides.
    for action, (extra, _) in cases.items():
        _, _, state = step(f"{action}([probe, missing])", action,
                           {"clip_ids": [cid, MISSING_ID], **extra},
                           expect_code="CLIP_NOT_FOUND")
        if state and (state.get("unresolved_clip_ids") != [MISSING_ID]
                      or state.get("resolved_clip_ids") != [cid]):
            failures.append(f"{action}: error.state does not name both sides: {state}")

    # 2. All-missing batches: move/relink/unlink/append/export/auto-sync used to
    #    reach Resolve with [].
    for action, (extra, _) in cases.items():
        step(f"{action}([missing])", action, {"clip_ids": [MISSING_ID], **extra},
             expect_code="CLIP_NOT_FOUND")

    # 3. Shapes.
    step("delete_clips(bare string)", "delete_clips", {"clip_ids": cid},
         expect_code="INVALID_CLIP_IDS")
    step("unlink([])", "unlink", {"clip_ids": []}, expect_code="INVALID_CLIP_IDS")
    step("move_clips(no clip_ids)", "move_clips", {"target_path": clip_path},
         expect_code="MISSING_CLIP_IDS")
    step("create_timeline_from_clips(bare string)", "create_timeline_from_clips",
         {"name": TIMELINE_NAME, "clip_ids": cid}, expect_code="INVALID_CLIP_IDS")
    step("export_metadata([])", "export_metadata", {"path": EXPORT_PATH, "clip_ids": []},
         expect_code="INVALID_CLIP_IDS")
    step("auto_sync_audio(no clip_ids)", "auto_sync_audio", {},
         expect_code="MISSING_CLIP_IDS")

    # 4. A whole batch still resolves to the real clip. delete_clips stops at the
    #    confirm preview; the other seven reach the tripwire, never Resolve.
    out, _, _ = step("delete_clips([probe])", "delete_clips", {"clip_ids": [cid]})
    preview = out.get("preview") or {}
    if out.get("status") != "confirmation_required":
        failures.append(f"delete_clips([probe]) did not stop at confirmation_required: "
                        f"status={out.get('status')!r} error={_err_of(out)}")
    elif preview.get("clips_lost") != 1 or preview.get("names") != [cname]:
        failures.append(f"delete preview does not describe the probe clip: {preview}")

    for action, (extra, method) in cases.items():
        if action == "delete_clips":
            continue
        _, calls, _ = step(f"{action}([probe])", action, {"clip_ids": [cid], **extra},
                           expect_calls=1)
        if len(calls) == 1:
            name, args = calls[0]
            # CreateTimelineFromClips(name, clips) and ExportMetadata(path, clips)
            # take the clip list second; every other method takes it first.
            at = 1 if method in ("CreateTimelineFromClips", "ExportMetadata") else 0
            clip_arg = args[at] if len(args) > at else []
            handed = [c.GetUniqueId() for c in (clip_arg or [])]
            if name != method or handed != [cid]:
                failures.append(f"{action}([probe]) handed Resolve {name}({handed}), "
                                f"expected {method}([{cid}])")
            if method == "MoveClips" and (len(args) < 2 or args[1].GetUniqueId() != folder_id):
                failures.append("move_clips([probe]) resolved a different target folder")

    # 5. Nothing changed in the real Media Pool.
    after_clips, after_folders = _census(root)
    file_path_after = clip.GetClipProperty("File Path")
    print(f"After: {len(after_folders)} folders, {len(after_clips)} clips "
          f"(delta {len(after_folders) - len(before_folders):+d} folders, "
          f"{len(after_clips) - len(before_clips):+d} clips)")
    if after_clips != before_clips:
        failures.append("a clip was added, removed or moved (must not)")
    if after_folders != before_folders:
        failures.append("the folder tree changed (must not)")
    if file_path_after != file_path_before:
        failures.append(f"probe clip File Path changed {file_path_before!r} -> {file_path_after!r}")
    timelines_after, items_after = timeline_state()
    if timelines_after != timelines_before:
        failures.append(f"timeline count changed {timelines_before} -> {timelines_after} (must not)")
    if items_after != items_before:
        failures.append(f"current timeline item count changed {items_before} -> {items_after} (must not)")
    if os.path.exists(EXPORT_PATH):
        failures.append(f"a metadata file was written to {EXPORT_PATH} (must not)")

    print(f"Intercepted, never sent to Resolve: {[c[0] for c in tripwire.intercepted]}")
    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"\nPASS: partial and all-missing batches refused for all {len(cases)} actions with "
          f"no MediaPool call attempted; a whole batch resolves to the real clip; "
          f"{len(after_folders)} folders / {len(after_clips)} clips, the probe clip's "
          f"folder and File Path, the timeline count ({timelines_after}) and the current "
          f"timeline's items unchanged; no metadata file written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
