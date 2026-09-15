# Project archive on Resolve 21.1

`ProjectManager.ArchiveProject` has no `api_truth` entry until now, and both of
this server's archive actions sat in the ratchet's unrated backlog. The native
defaults, `isArchiveSrcMedia=True` and `isArchiveRenderCache=True`, were
inherited by both the compound `project_manager archive` action and the granular
`archive_project` tool. On Studio 21.1.0.14 a default call crashes Resolve.

## Measured

Studio 21.1.0.14, local disk database, one disposable project with one synthetic
2-second clip on one timeline, archived by name. One isolated call per row, with
breadcrumbs written to disk before and after so a crash cannot hide which call
caused it. Presence was checked with `dir()` membership against a known-present
control, not `hasattr`, which Resolve answers True for any name.

| Case | Returns | Effect |
| --- | --- | --- |
| Open project, all flags off | `False` | nothing written, instantly |
| Closed project, all flags off | `False` | nothing written, instantly |
| Closed project, render cache only | `False` | nothing written, instantly |
| Closed project, source media | `None` | empty directory at the target, then Resolve crashes |
| Closed project, proxy media | `None` | empty directory at the target, then Resolve crashes |
| Unrelated file at target, flags off | `False` | file byte-identical |
| Populated directory at target, flags off | `False` | untouched |
| Source media onto an existing file | `None` | Resolve crashes; file byte-identical |

The crash is SIGSEGV, stamped the same second as the call. A crashing call comes
back through the bridge as `None`, not a bool, and every handle after it is dead.
Resolve logs nothing about the `False` returns.

**Media-flag calls crashed 4 of 4; flags-off calls crashed 0 of 5.** The four
crashes, one of them in a Blackmagic Cloud library on an earlier attempt, share
identical top stack frames in Fusion script-symbol teardown on the UI thread. A
fifth crash in the same session, during `DeleteProject` then `LoadProject` 44
seconds after a relaunch, has a different stack past the generic crash-handler
frames, so the archive signature is not a general instability. Crash uptimes were
1:45, 14:16, 1:31 and 0:45.

**The destination is never the casualty.** A file or folder already at the target
survived every case byte for byte, including the crash. Resolve cannot create its
bundle folder over an existing file and crashes anyway, so the crash is in starting
the archive job, not in writing the destination. What is lost is unsaved work in
the open project.

19.1.3.7 agrees on the part it measured: this repo's mode matrix (2026-08-02, GUI
and headless) and the project-lifecycle kernel recorded `False` for both a `.dra`
and a folder-style path with every flag off. No scriptable call on either build has
produced an archive.

## What changed

- `src/utils/archive_guard.py`: every flag defaults off; only real booleans are
  accepted, since `bool("false")` is `True` and two flags crash; source media and
  proxy media are refused unless `acknowledge_trap=true`; the result reports the
  native return as observed (`True`, `False` with "wrote nothing", or `None` with
  "likely crashed") rather than a bare bool.
- Compound `project_manager archive` and `safe_project_archive` use it.
  `safe_project_archive` keeps its existing `allow_media_archive` size guard and
  now also needs `acknowledge_trap` for the crashing flags: one guards size, the
  other the crash.
- Granular `archive_project`: defaults off, `acknowledge_trap` for the crashing
  flags, `DESTRUCTIVE_TOOL` annotation and `@granular_destructive_op()`.
- Both compound actions are registered, rated MEDIUM, and removed from the ratchet
  backlog. `safe_project_archive` honours `dry_run` natively and is listed as such.
- `api_truth` gains a `ProjectManager.ArchiveProject` entry and `ACTION_SYMBOLS`
  maps both compound actions to it, so the measured fact rides on every result.

## A design question for the maintainer

The entry deliberately does **not** set `destroys_prior_work`. That flag is
symbol-level, so every mapped action would refuse until acknowledged, including
the flags-off call, which is a harmless no-op. The refusal here is parameter-level
instead, in the wrappers. If the symbol-level trap is preferred, it is a one-line
change plus the granular confirmation tier.

## Not tested

No scriptable call produced an archive, so a `RestoreProject` round-trip could not
be measured. Also untested: render cache on a project that has one, headless mode
on 21.1, builds after 21.1.0.14, and Windows or Linux.
