# Script Plugin Authoring

The `script_plugin` compound tool (introduced in v2.5.0) generates, validates
and installs Resolve-page Lua/Python scripts. **It does not run them.** Script
execution — `run_inline` and `execute` — was removed in v3.0.0, because this
server does not execute caller-supplied code. An installed script appears as a
Resolve menu item, and running it is the user's action, inside Resolve.

Unlike `fuse_plugin` (which authors Fusion image-processing tools) and `dctl`
(which authors color-page shaders), `script_plugin` targets the
**Workspace → Scripts** menu — the user-facing surface for general Resolve
automation.

## When to use what

| Goal | Use |
|---|---|
| One-off query or change against Resolve | The typed Resolve API tools — no script, no execution |
| Custom workflow you want as a permanent menu item | `script_plugin('install', ...)`, then the user runs it from Workspace → Scripts |
| Image-processing node for the Fusion page | `fuse_plugin` |
| Color-page programmable transform | `dctl` |
| Anything the wrapped Resolve API tools already cover | The wrapped tool — no scripting needed |

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

## Running an installed script

`script_plugin` installs scripts; it does not run them. v3.0.0 removed the two
actions that did:

- `run_inline` ran a caller's source directly — Python as a subprocess on the
  host, with a live Resolve handle, or Lua inside Resolve's Fusion engine with
  `os` and `io` in scope.
- `execute` ran an installed script, which `install` could have just written
  from caller-supplied source.

Neither passed any of the server's safety gates, and the maintainer policy is
that the server never executes caller-supplied code. Calling either now returns
an error that says so and points here.

After `install`, the user runs the script from **Workspace → Scripts →
\<category\>** inside Resolve; Python output appears in Resolve's Console. For
queries and edits in conversation, use the typed tools.

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
- ✅ Both engines (Lua and Python) compile without errors
- ✅ DSL coverage tests confirm every documented source/action/target/transform/strategy is present in both engines

## Resolve's Lua bridge — reference

Two measured facts about Resolve itself, found while building the now-removed
`run_inline`, stay true of Resolve and are kept here for reference:

1. **`fusion.Execute(luaSource)` is a no-op** from the Python
   `DaVinciResolveScript` bridge in Resolve 20.x: it returns `None` with no
   observable side effects.
2. **`fusion.RunScript(filepath)` is asynchronous**: it returns before the
   script finishes, so an immediate `fusion.GetData()` reads stale values.

## Source media integrity

These tools generate workflows that READ Resolve's media-pool and timeline
state and WRITE metadata, bin organization, markers, and similar
non-destructive properties. The DSL's actions do not modify source files
on disk. If you build a custom action that exports media, transcodes, or
otherwise creates derivatives, that's outside the engine's defaults — be
explicit when authoring such rules.
