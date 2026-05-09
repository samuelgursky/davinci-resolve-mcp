# Script Plugin Authoring & Conversational Resolve Scripting

The `script_plugin` compound tool (introduced in v2.5.0) generates, installs,
and **executes** Resolve-page Lua/Python scripts. It closes the conversational
loop: an LLM with access to the MCP can describe a workflow, generate the
script, install it as a Resolve menu item, and execute it — all in one turn —
with the script's stdout streamed back into the conversation.

Unlike `fuse_plugin` (which authors Fusion image-processing tools) and `dctl`
(which authors color-page shaders), `script_plugin` targets the
**Workspace → Scripts** menu — the user-facing surface for general Resolve
automation.

## When to use what

| Goal | Use |
|---|---|
| One-off conversational query against Resolve | `script_plugin('run_inline', ...)` |
| Custom workflow you want as a permanent menu item | `script_plugin('install', ...)` then `('execute', ...)` |
| Image-processing node for the Fusion page | `fuse_plugin` |
| Color-page programmable transform | `dctl` |
| Anything the existing 28 wrapped Resolve API tools already cover | The wrapped tool — no scripting needed |

## Two template kinds

### `scaffold`
Minimal stub. Connects to Resolve, gets `resolve` / `project` / `mp` /
`timeline` handles, defines an empty `main()`. For when the LLM wants to
write everything from scratch.

### `media_rules`
The rules-and-variables DSL. Generates a self-contained script with three
top sections (VARIABLES, ENGINE GLOBALS, RULES) followed by an embedded
~300-line engine that interprets the rules. The LLM (or user) edits the
RULES table; the engine handles execution.

**Rules** are dicts with shape:
```lua
{
    name    = "rule description",
    target  = "media_pool_clips",  -- scope
    extract = {                     -- pull values from each item
        { source = "file_path", pattern = "DATE_PATTERN",
          into = {"yr", "mo", "dy"} },
    },
    apply = {                       -- side effects driven by the captures
        { type = "set_metadata", field = "Shoot Date",
          value = "{yr}-{mo}-{dy}" },
    },
    condition = function(vars) return ... end,  -- optional
    enabled = true,                              -- optional
    stop_on_match = false,                       -- optional
}
```

## DSL coverage

### Sources (where data comes from)
`file_path`, `filename`, `dirname`, `parent_dir`, `grandparent_dir`,
`file_extension`, `path_segment:N`, `clip_property:<Field>`,
`metadata:<Field>`, `embedded_metadata:<Field>`, `camera_metadata:<Field>`,
`previous_capture:<rule_id>`, `static_value`, `bin_name`, `media_pool_path`,
`clip_duration`, `clip_resolution`, `frame_rate`, `codec`, `audio_channels`,
`audio_format`, `start_tc`, `end_tc`, `creation_time`, `modification_time`,
`external_data:<column>` (loaded from CSV/JSON).

### Actions (what to do)
`set_metadata`, `set_clip_property`, `rename_clip`, `move_to_bin`,
`set_clip_color`, `flag_clip`, `add_keyword`, `add_marker`, `apply_lut`,
`set_in_out`, `tag_for_review`, `notify` / `print`.

### Targets (scope)
`media_pool_clips`, `current_bin_clips`, `bin_path:<path>`,
`selected_clips`, `timeline_items`, `selected_timeline_items`,
`unmatched_clips`, `clips_matching:<predicate>`, `timeline_items_in_track:N`.

### Transforms (variable pipes)
Plain substitution `{var}`, plus pipes: `upper`, `lower`, `title`, `slug`,
`pad(n, char)`, `lookup(table_name)`, `add(n)`, `sub(n)`, `mul(n)`, `div(n)`,
`date(format)`. Chainable: `{var | upper | slug}`.

### Engine globals
`DRY_RUN`, `LOG_LEVEL`, `LIMIT_TO_FIRST_N`, `EXTERNAL_DATA`,
`BACKUP_BEFORE_RUN`.

### External data (the killer feature)
`EXTERNAL_DATA = { csv = "/path/to/sheet.csv", match_on = {...} }` lets
rules reference any column in a spreadsheet via `external_data:<column>`.
Match strategies: `exact`, `regex`, `fuzzy` (Levenshtein nearest match —
useful for filename variations).

Real-world example: a script supervisor's CSV with Filename, Scene, Take,
Camera, Lens columns. Single rule maps each clip to its row and populates
all metadata fields plus organizes into Scene bins. Six lines of RULES.

## Conversational execution: `run_inline` and `execute`

The two actions that close the loop:

### `run_inline(source, language, timeout?)`
Run an ad-hoc Lua or Python snippet inside Resolve, get stdout + return
value back. No file persistence.

**Python**: writes source to a temp file with `resolve`/`project`/`mp`/
`timeline` pre-bound, runs as subprocess, captures stdout/stderr.

**Lua**: wraps source so `print()` is intercepted into a buffer, runs via
`fusion.RunScript()`, polls a completion sentinel, reads stdout + return
value back via `app:SetData()`/`fusion.GetData()`. (Note: `fusion.Execute()`
from the Python bridge is a no-op in Resolve 20.x — `RunScript()` against a
file is the only working path. The implementation handles this.)

Example:
```python
script_plugin('run_inline', {
    'source': '''
print(f"Project: {project.GetName()}")
print(f"Bins: {len(mp.GetRootFolder().GetSubFolderList() or [])}")
''',
    'language': 'py',
})
# → {success: True, stdout: "Project: My Show\nBins: 12\n", exit_code: 0}
```

### `execute(name, category, language, args?, timeout?)`
Run an installed script. Same return shape as `run_inline`.

**Python**: subprocess captures full stdout/stderr.
**Lua**: `fusion.RunScript()`; print() output goes to Resolve Console
(can't capture). For Lua scripts that need to return data, have them write
to `app:SetData()` and the caller reads via the existing `fusion_comp`
tooling.

## Install paths

Resolve scans these subdirs for the **Workspace → Scripts → \<category\>** menu:

| Platform | Root |
|---|---|
| macOS | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/<category>/` |
| Windows | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\<category>\` |
| Linux | `~/.local/share/DaVinciResolve/Fusion/Scripts/<category>/` |

Categories: `Edit`, `Color`, `Deliver`, `Comp`, `Tool`, `Utility`, `Views`.
`Utility` shows up everywhere; the others only on the matching page.

Resolve picks up new scripts **without a restart** — the menu refreshes each
time it's opened.

## Languages

Both Lua and Python are first-class. Lua is Fusion-native; Python is more
familiar for data-heavy workflows. The same RULES table syntax works in both
(Lua tables vs. Python dicts).

## Live verification

Verified on DaVinci Resolve Studio 20.3.2.9, macOS:

- ✅ Scripts appear in Workspace → Scripts → \<category\> after install (no restart needed)
- ⚠️ Installed Lua script execution via `fusion.RunScript(path)` can return
  `False` from the Python bridge even when install/read/list/remove work. Use
  `run_inline(language="lua")` when captured output or return values matter.
- ✅ Python scripts execute via subprocess with full stdout/stderr capture
- ✅ `run_inline` Lua: stdout captured (with tabs), return value captured, errors trapped with line numbers
- ✅ `run_inline` Python: full Resolve API access, project + media-pool + timeline pre-bound
- ✅ Both engines (Lua and Python) compile without errors
- ✅ DSL coverage tests confirm every documented source/action/target/transform/strategy is present in both engines

## Implementation notes (for maintainers)

Two non-obvious behaviors of Resolve's Lua bridge surfaced during live
testing and are encoded in the implementation:

1. **`fusion.Execute(luaSource)` is a no-op** when called from the Python
   `DaVinciResolveScript` bridge in Resolve 20.x. It returns `None` and has
   no observable side effects. Don't use it. Use `fusion.RunScript(filepath)`
   against a temp file instead.

2. **`fusion.RunScript()` is asynchronous.** It returns before the script
   finishes. Reading `fusion.GetData()` immediately gives stale values. The
   implementation polls a completion-sentinel slot (`__mcp_done__`) until
   the wrapped Lua sets it to `"1"`, then reads results.

These constraints are unique to the Lua side; Python's subprocess approach
is straightforwardly synchronous.

## Source media integrity

These tools generate workflows that READ Resolve's media-pool and timeline
state and WRITE metadata, bin organization, markers, and similar
non-destructive properties. The DSL's actions do not modify source files
on disk. If you build a custom action that exports media, transcodes, or
otherwise creates derivatives, that's outside the engine's defaults — be
explicit when authoring such rules.
