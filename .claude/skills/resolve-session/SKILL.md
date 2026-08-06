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
   the bridge path (Workspace > Scripts > resolve_bridge) covers it, and is used
   automatically once running — `DAVINCI_RESOLVE_BRIDGE=1` only forces it.

   Report **both** versions: `version_string` is the Resolve build,
   `mcp.version` is this server. They fail differently, and one of them is
   easy to forget — a running MCP keeps executing the version it started with,
   so a `git pull` does not refresh its ledger until restart.

2. **Ask what this build cannot do.**

   `resolve_control(action="check_version_support")` — every recorded API gate
   this build does not clear.

   The scripting API changes per **patch** release, so "Resolve 21" is not a
   usable label: `GetFairlightPresets` needs 20.2.2, and three surfaces exist in
   21.0.4 but not 21.0.2. Knowing this at the top of the session is the
   difference between "that needs 21.0.4, here is the alternative" and
   discovering it halfway through a task.

   Two things to hold on to:

   - An empty list means **nothing recorded is missing**, not that everything
     exists. Most of the API has never been version-bisected, so a symbol with
     no gate returns `unknown` — which means probe it, not yes.
   - Probe with `name in dir(obj)`. Never bare `hasattr`: on a Resolve object it
     returns `True` for every name, real or invented, so it can only say yes.

3. **Report the current project.**

   `project_manager(action="get_current_project")`. If none is open, list
   available projects and stop — ask which to open rather than guessing.

4. **Report timelines.**

   `timeline(action="list")` plus the current timeline's frame rate,
   resolution, duration, and track layout. Frame rate and resolution matter
   before any edit decision; note them explicitly.

5. **Report media pool shape.**

   Bin structure and clip count. Enough to know what is available — not a full
   inventory.

6. **Flag anything that will bite later.**

   Offline or unlinked media, mixed frame rates in the pool, a timeline
   resolution that disagrees with the project, or missing render presets.

## Output

A short block: version and edition, project, current timeline with its format,
pool summary, then warnings — and list anything `check_version_support` reported
missing, since a capability gap changes what is worth proposing. Say what you are
ready to do and wait — do not
start editing off the back of this.

## Notes

- If Resolve is not running, the MCP tools will launch it; the first call can
  take up to 60 seconds. Say so rather than appearing to hang.
- Do not open, create, or switch projects without being asked. Reporting state
  is the whole job here.
