"""Live check: media_pool folder ids resolve at any depth, and partial batches fail.

Covers delete_folders and move_folders against the Media Pool of the project
that is open in a running Resolve.

STRICTLY NON-DESTRUCTIVE, and it never launches Resolve:

- Connects only to a Resolve that is already running (`_try_connect`), never
  `get_resolve()`, which starts the application when nothing answers.
  `_launch_resolve` is replaced with a function that raises.
- **Tripwire.** The MediaPool handed to the actions forwards only
  GetRootFolder / GetCurrentFolder. Every other MediaPool method — DeleteFolders,
  MoveFolders and anything else — is recorded and answered False without
  reaching Resolve. So nothing is deleted or moved whatever the code under test
  does, including a regressed build. The folder objects the actions resolve are
  the real ones; only their read methods are called.
- Confirm-token gating is forced on and no token is ever passed, so
  delete_folders can at most *issue* a token (kept in memory, never used).
- The move probes aim at the probe folder's CURRENT parent, so even a call that
  somehow got past the tripwire would move it nowhere.
- The destructive hook's project-root provider is disabled for the run, so no
  auto-run or media_pool_changes row is written into the project's analysis
  root, and the execution-trace, operation and security-audit logs go to a temp
  directory instead of the operator's trail under logs/.
- Creates nothing. It needs an existing folder at least two levels below Master
  and SKIPs when the open project has none.

It records every folder's parent and every clip's folder before and after, and
proves all of it is unchanged.

Run (Resolve open, Preferences > General > External scripting = Local):
  venv/bin/python tests/live_nested_folder_ids_check.py
"""
import os
import sys
import tempfile
import uuid

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

LOG_DIR = tempfile.mkdtemp(prefix="live-nested-folder-ids-check-")
os.environ["RESOLVE_MCP_TRACE_FILE"] = os.path.join(LOG_DIR, "execution-traces.jsonl")
os.environ["RESOLVE_MCP_OPERATION_LOG_FILE"] = os.path.join(LOG_DIR, "operation-log.jsonl")

import src.server as s  # noqa: E402 - after the env redirects above
from src.utils import destructive_hook  # noqa: E402

MISSING_ID = f"__mcp_live_check_missing_folder_{uuid.uuid4().hex}__"
READ_METHODS = frozenset({"GetRootFolder", "GetCurrentFolder"})


class TripwireMediaPool:
    """Forwards the two reads the folder actions need; intercepts everything else."""

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
    raise RuntimeError("live_nested_folder_ids_check never launches Resolve")


def _walk(folder, names=(), depth=0, out=None):
    """Every folder below `folder` as (folder, names, depth, parent_id)."""
    out = [] if out is None else out
    parent_id = folder.GetUniqueId()
    for sub in (folder.GetSubFolderList() or []):
        sub_names = names + (sub.GetName(),)
        out.append((sub, sub_names, depth + 1, parent_id))
        _walk(sub, sub_names, depth + 1, out)
    return out


def _census(root):
    """({folder_id: parent_id}, {clip_id: folder_id}) for the whole Media Pool."""
    walked = _walk(root)
    folders = {root.GetUniqueId(): None}
    folders.update({f.GetUniqueId(): pid for f, _, _, pid in walked})
    clips = {}
    for f in [root] + [f for f, _, _, _ in walked]:
        fid = f.GetUniqueId()
        for clip in (f.GetClipList() or []):
            clips[clip.GetUniqueId()] = fid
    return folders, clips


def _probe_candidate(mp, root):
    """The deepest folder at depth >= 2 whose parent path navigates back to it.

    The path check matters because move_folders addresses its target by name:
    with duplicate sibling names, "Master/A" could name a different A than the
    real parent, and the no-op-move guarantee would not hold.
    """
    for folder, names, depth, parent_id in sorted(_walk(root), key=lambda t: -t[2]):
        if depth < 2 or any("/" in n for n in names):
            continue
        parent_path = "Master/" + "/".join(names[:-1])
        nav = s._navigate_folder(mp, parent_path)
        if nav is not None and nav.GetUniqueId() == parent_id:
            return folder, names, depth, parent_id, parent_path
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
    root_id = root.GetUniqueId()
    candidate = _probe_candidate(real_mp, root)
    if candidate is None:
        print(f"SKIP: {real_proj.GetName()} has no folder two or more levels below Master; "
              "this check creates none.")
        return 0
    folder, names, depth, parent_id, parent_path = candidate
    fid = folder.GetUniqueId()

    before_folders, before_clips = _census(root)
    if MISSING_ID in before_folders:
        print("FAIL: the generated missing id exists in the pool; re-run.")
        return 1
    print(f"Connected: {r.GetProductName()} {r.GetVersionString()} — project "
          f"{real_proj.GetName()!r}: {len(before_folders)} folders, {len(before_clips)} clips")
    print(f"Probe folder: Master/{'/'.join(names)} (depth {depth}, id {fid})")
    print(f"Logs for this run: {LOG_DIR}")

    failures = []

    def step(label, action, params, *, expect_code=None, expect_calls=0):
        n = len(tripwire.intercepted)
        out = s.media_pool(action, params)
        calls = tripwire.intercepted[n:]
        err = _err_of(out)
        print(f"{label:<48} -> code={err.get('code')!r} status={out.get('status')!r} "
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
        return out, calls, err.get("state") or {}

    # 1. A nested id resolves: delete_folders stops at confirmation_required,
    #    and the preview names exactly that folder. Pre-fix: "No folders found".
    out, _, _ = step("delete_folders([nested])", "delete_folders", {"folder_ids": [fid]})
    preview = out.get("preview") or {}
    if out.get("status") != "confirmation_required":
        failures.append(f"nested id did not reach confirmation_required: "
                        f"status={out.get('status')!r} error={_err_of(out)}")
    elif preview.get("folders_lost") != 1 or preview.get("names") != [names[-1]]:
        failures.append(f"preview does not describe the probe folder: {preview}")

    # 2. move_folders hands Resolve the nested folder and its current parent —
    #    intercepted by the tripwire, so nothing moves.
    _, calls, _ = step("move_folders([nested] -> parent)", "move_folders",
                       {"folder_ids": [fid], "target_path": parent_path}, expect_calls=1)
    if len(calls) == 1:
        name, args = calls[0]
        handed = [f.GetUniqueId() for f in (args[0] if args else [])]
        target = args[1].GetUniqueId() if len(args) > 1 else None
        if name != "MoveFolders" or handed != [fid] or target != parent_id:
            failures.append(f"move_folders([nested]) handed Resolve {name}({handed}, {target}), "
                            f"expected MoveFolders([{fid}], {parent_id})")

    # 3. Partial and all-missing batches fail before anything reaches Resolve.
    for label, ids, resolved in (("[nested, missing]", [fid, MISSING_ID], [fid]),
                                 ("[missing]", [MISSING_ID], [])):
        for action, extra in (("delete_folders", {}),
                              ("move_folders", {"target_path": parent_path})):
            _, _, state = step(f"{action}({label})", action, {"folder_ids": ids, **extra},
                               expect_code="FOLDER_NOT_FOUND")
            if state and (state.get("unresolved_folder_ids") != [MISSING_ID]
                          or state.get("resolved_folder_ids") != resolved):
                failures.append(f"{action}({label}): error.state does not name both sides: {state}")

    # 4. Master is refused; shapes are refused.
    step("delete_folders([Master])", "delete_folders", {"folder_ids": [root_id]},
         expect_code="ROOT_FOLDER_NOT_ELIGIBLE")
    step("move_folders([Master] -> parent)", "move_folders",
         {"folder_ids": [root_id], "target_path": parent_path},
         expect_code="ROOT_FOLDER_NOT_ELIGIBLE")
    step("delete_folders(bare string)", "delete_folders", {"folder_ids": fid},
         expect_code="INVALID_FOLDER_IDS")
    step("move_folders([])", "move_folders", {"folder_ids": [], "target_path": parent_path},
         expect_code="INVALID_FOLDER_IDS")
    step("delete_folders(no folder_ids)", "delete_folders", {},
         expect_code="MISSING_FOLDER_IDS")

    # 5. Nothing changed in the real Media Pool.
    after_folders, after_clips = _census(root)
    print(f"After: {len(after_folders)} folders, {len(after_clips)} clips "
          f"(delta {len(after_folders) - len(before_folders):+d} folders, "
          f"{len(after_clips) - len(before_clips):+d} clips)")
    if after_folders != before_folders:
        failures.append("a folder was added, removed or moved (must not)")
    if after_clips != before_clips:
        failures.append("a clip was added, removed or moved (must not)")

    print(f"Intercepted, never sent to Resolve: {[c[0] for c in tripwire.intercepted]}")
    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"\nPASS: nested id resolved at depth {depth}; partial and all-missing batches, "
          f"Master and bad shapes refused for both actions with no MediaPool mutation "
          f"attempted; {len(after_folders)} folders / {len(after_clips)} clips and every "
          f"parent unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
