# DaVinci Resolve MCP — Autonomous API Coverage Program

This is an experiment adapted from [karpathy/autoresearch](https://github.com/karpathy/autoresearch) to have an AI agent autonomously expand and refine the DaVinci Resolve MCP server toward 100% API coverage.

## Setup

To set up a new session, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar8`). The branch `autoresearch/<tag>` must not already exist — this is a fresh run.
2. **Create the branch**: `git checkout -b autoresearch/<tag>` from current main.
3. **Read the in-scope files**: Read these files for full context:
   - `README.md` — repository context and current feature set.
   - `docs/FEATURES.md` — comprehensive feature matrix with implementation/verification status.
   - `src/resolve_mcp_server.py` — the main server file. All MCP tools are defined here.
   - `src/api/` — helper modules (color_operations.py, delivery_operations.py, media_operations.py, project_operations.py, timeline_operations.py).
   - `src/utils/` — utility modules (platform.py, resolve_connection.py, object_inspection.py, layout_presets.py, app_control.py, cloud_operations.py, project_properties.py).
4. **Initialize results.tsv**: Create `results.tsv` with header row and baseline entry from the current tool count and known state.
5. **Confirm and go**: Confirm setup looks good.

Once you get confirmation, kick off the experimentation.

## Goal

**The goal is simple: achieve 100% coverage of the DaVinci Resolve scripting API with working, well-structured MCP tools.**

The DaVinci Resolve scripting API (documented in `docs/resolve_scripting_api.txt`) exposes **345 unique non-deprecated methods** across these object classes:

| Object Class | Methods | Description |
|---|---|---|
| **Resolve** | 21 | Top-level app: pages, layout presets, keyframe modes, render/burn-in presets |
| **ProjectManager** | 27 | Database, project CRUD, folders, cloud projects, import/export/archive |
| **Project** | 46 | Settings, timelines, rendering, presets, color groups, gallery, LUTs |
| **MediaStorage** | 11 | Mounted volumes, file/folder browsing, add items to media pool, mattes |
| **MediaPool** | 27 | Bins, clips, timelines, import/export, folders, mattes, stereo, audio sync |
| **Folder** | 10 | Clip/subfolder listing, export, transcription |
| **MediaPoolItem** | 33 | Properties, metadata, markers, flags, colors, proxy, transcription, audio mapping |
| **Timeline** | 57 | Tracks, items, markers, timecode, generators, titles, Fusion, stills, subtitles, scene detection, stereo, export |
| **TimelineItem** | 83 | Properties, markers, flags, Fusion comps, versions, takes, CDL, color groups, stabilize, smart reframe, magic mask, LUTs, cache |
| **Gallery** | 8 | Album management, stills, power grades |
| **GalleryStillAlbum** | 6 | Stills CRUD, labels, import/export |
| **GalleryStill** | 0 | Object type only (used by other classes) |
| **Graph** | 11 | Node operations: LUTs, cache, labels, tools, enable/disable, grades |
| **ColorGroup** | 5 | Name, clips, pre/post-clip node graphs |

### Current State (v1.3.8 on main)

- **83 MCP tools** defined in a single monolithic server file
- **202 features tracked** in FEATURES.md, but only **17 verified working (8%)**
- **0% coverage**: MediaStorage, Fusion Page, Fairlight Page
- **Known bugs**: AddRenderJob, AddNode, SetColorWheelPrimaryParam, proxy operations
- **Architecture**: Monolithic — all tools in one ~4,600-line file

### Target: 345 MCP Tools (100% API Coverage)

- **Full API coverage**: Every documented method on every Resolve scripting object should have a corresponding MCP tool (345 methods → 345 tools)
- **Current baseline**: 83 tools = **24.1% coverage**
- **Modular architecture**: Break monolithic server into organized modules as tool count grows
- **Bug fixes**: Fix 19 known failing tools
- **Quality**: Clean error handling, consistent parameter naming, good docstrings

## Experimentation

Each experiment is a focused unit of work: adding tools for one API object, fixing a category of bugs, or refactoring a module. Unlike autoresearch's 5-minute training runs, here the "run" is: implement → commit → validate (syntax check + import test).

**What you CAN do:**
- Add new MCP tool definitions to `src/resolve_mcp_server.py`
- Create new helper modules in `src/api/` or `src/utils/`
- Create new tool modules in `src/tools/` (for modular expansion)
- Fix bugs in existing tool implementations
- Refactor existing code for clarity and modularity
- Update `docs/FEATURES.md` to reflect changes

**What you CANNOT do:**
- Break existing working tools (the 17 verified ones are sacred)
- Change the MCP protocol interface (FastMCP)
- Remove the core connection/platform logic
- Change `requirements.txt` or add new dependencies without user approval
- Modify `.gitignore` or git configuration

**Validation**: After each change, run:
```bash
python -c "import ast; ast.parse(open('src/resolve_mcp_server.py').read()); print('OK: server parses')" 2>&1
```
For new modules:
```bash
python -c "import ast; ast.parse(open('src/api/NEW_MODULE.py').read()); print('OK: module parses')" 2>&1
```
If you have access to a running Resolve instance, also test:
```bash
python -c "from src.resolve_mcp_server import mcp; print(f'OK: {len(mcp._tool_manager._tools)} tools registered')" 2>&1
```

## Output Format

After each experiment, the key metrics are:

```
tools_added:      N
tools_fixed:      N
tools_total:      NNN
coverage_pct:     XX.X%
syntax_valid:     true/false
```

Coverage percentage = (tools_total / 345) * 100, where 345 is the exact unique non-deprecated API method count from the official Resolve Scripting API (see `docs/resolve_scripting_api.txt`).

## Logging Results

When an experiment is done, log it to `results.tsv` (tab-separated, NOT comma-separated).

The TSV has a header row and 6 columns:

```
commit	tools_total	coverage_pct	status	category	description
```

1. git commit hash (short, 7 chars)
2. total MCP tools after this change
3. coverage percentage (e.g. 45.2)
4. status: `keep`, `discard`, or `error`
5. category: which API area (e.g. `MediaStorage`, `Timeline`, `bugfix`, `refactor`)
6. short text description of what this experiment did

Example:

```
commit	tools_total	coverage_pct	status	category	description
a1b2c3d	83	24.5	keep	baseline	baseline from v1.3.8 main
b2c3d4e	91	26.8	keep	MediaStorage	add 8 MediaStorage tools (mounted volumes, file browsing)
c3d4e5f	91	26.8	discard	Fusion	attempted Fusion tools but API not accessible
d4e5f6g	99	29.2	keep	Timeline	add missing timeline methods (DuplicateTimeline, Export, etc.)
```

## The Experiment Loop

The experiment runs on a dedicated branch (e.g. `autoresearch/mar8`).

LOOP FOREVER:

1. **Assess**: Look at current coverage. What API objects/methods are missing? What's buggy? Consult `docs/FEATURES.md` and the Resolve scripting API reference.
2. **Plan**: Pick the highest-impact next experiment. Prioritize:
   - **Bug fixes** for existing tools (especially the 19 with known issues)
   - **Missing core API objects** (MediaStorage has 0% coverage)
   - **High-value gaps** (render job management, timeline import/export, scene detection)
   - **Unimplemented planned features** (marked with a plan emoji in FEATURES.md)
   - **Refactoring** only when it enables the above
3. **Implement**: Write the code. Keep changes focused — one API area per experiment.
4. **Validate**: Run syntax check. If it fails, fix and re-check.
5. **Commit**: `git add` the changed files and `git commit` with a descriptive message.
6. **Log**: Record results in results.tsv.
7. **Decide**:
   - If the change is valid and adds value → `keep`, advance the branch
   - If the change introduces errors or doesn't work → `discard`, `git reset --hard HEAD~1`
   - If something crashes → fix it or skip it, log as `error`

### Priority Order for API Coverage

Work through these in roughly this order:

1. **MediaStorage** (0% → target 100%) — GetMountedVolumes, GetSubFolderList, GetFileList, AddItemListToMediaPool, RevealInStorage
2. **Bug fixes** — Fix the 19 known broken tools (render jobs, color nodes, proxy operations)
3. **Timeline gaps** — DuplicateTimeline, CreateCompoundClip, CreateFusionClip, ImportIntoTimeline, Export, scene detection
4. **MediaPoolItem gaps** — All missing clip property methods, matte operations
5. **Project gaps** — GetPresetList, SetPreset, render format/codec control
6. **Gallery/GalleryStillAlbum** — Complete still management
7. **ColorGroup** — Group management, node graph operations
8. **Delivery gaps** — Render status, format control, quick export, batch rendering
9. **Fairlight** — Audio operations (if API supports it)
10. **Fusion** — Composition access (if API supports it)
11. **Architecture** — Break monolithic file into modules if tool count exceeds ~150

### Simplicity Criterion

All else being equal, simpler is better. A tool that wraps one Resolve API call cleanly is better than a tool that tries to do five things. Each MCP tool should:
- Map to one or a small number of related Resolve API calls
- Have a clear, descriptive name
- Have typed parameters with good defaults
- Return structured data (dicts/lists, not raw strings)
- Handle errors gracefully with informative messages

### DaVinci Resolve Scripting API Reference

**The authoritative reference is `docs/resolve_scripting_api.txt`** — this is the official Blackmagic API doc (copied from `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/README.txt`). READ THIS FILE before each experiment to find methods you haven't covered yet.

Key API patterns:
- All operations go through: `resolve = dvr_script.scriptapp("Resolve")` → `projectManager` → `project` → `mediaPool` / `timeline` / etc.
- Methods return `None` on failure, actual values on success
- Boolean operations return `True`/`False`
- List operations return Python lists
- Property operations use string keys
- Some methods have overloaded signatures (e.g. `AddItemListToMediaPool` has 3 forms) — implement the most useful form(s)
- The API doc includes important enum values, settings keys, and data structure formats — reference these when implementing tools
- Deprecated methods (listed at end of doc) should NOT be implemented
- Unsupported methods (listed at end of doc) should NOT be implemented

**NEVER STOP**: Once the experiment loop has begun, do NOT pause to ask the human if you should continue. The human might be asleep or away. You are autonomous. If you run out of ideas, re-read the API reference, look at FEATURES.md for planned features, try combining approaches, or attempt more ambitious architectural changes. The loop runs until the human interrupts you, period.

As an example use case, a user might leave you running while they sleep. Each experiment takes ~2-5 minutes (implement + validate + commit). You can run 12-30 experiments per hour, potentially 100+ overnight. The user wakes up to a comprehensive results.tsv and a branch with dramatically expanded API coverage.
