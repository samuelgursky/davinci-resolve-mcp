---
name: resolve-session
description: Start a Resolve working session — connect, confirm the bridge and edition, open the project, and report timeline and media-pool state before any editing begins.
disable-model-invocation: true
---

# Start a Resolve Session

Run this at the top of an editing conversation so the session begins with known
state instead of four rounds of discovery. Report findings compactly; this is
orientation, not an audit.

## Steps

1. **Connect and identify the host.**

   `resolve_control(action="get_version")` — or the nearest capability action.

   Capture: Resolve version, Studio vs free edition, and whether this connected
   over external scripting or the in-app bridge. If the connection fails, read
   the error's own `remediation` field and follow it — it names the applicable
   fix. A connection error does **not** mean the free edition is unsupported;
   the bridge path (`DAVINCI_RESOLVE_BRIDGE=1`, Workspace > Scripts >
   resolve_bridge) covers it.

2. **Report the current project.**

   `project_manager(action="get_current_project")`. If none is open, list
   available projects and stop — ask which to open rather than guessing.

3. **Report timelines.**

   `timeline(action="list")` plus the current timeline's frame rate,
   resolution, duration, and track layout. Frame rate and resolution matter
   before any edit decision; note them explicitly.

4. **Report media pool shape.**

   Bin structure and clip count. Enough to know what is available — not a full
   inventory.

5. **Flag anything that will bite later.**

   Offline or unlinked media, mixed frame rates in the pool, a timeline
   resolution that disagrees with the project, or missing render presets.

## Output

A short block: version and edition, project, current timeline with its format,
pool summary, then warnings. Then say what you are ready to do and wait — do not
start editing off the back of this.

## Notes

- If Resolve is not running, the MCP tools will launch it; the first call can
  take up to 60 seconds. Say so rather than appearing to hang.
- Do not open, create, or switch projects without being asked. Reporting state
  is the whole job here.
