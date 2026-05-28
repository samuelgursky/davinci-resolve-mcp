# Resolve Color Decision Guide

This guide is the project-owned color correction and grading context for the
DaVinci Resolve MCP. It defines what an agent can actually create through the
public Resolve scripting API, what it can only apply as an opaque grade artifact,
and how to make color decisions without pretending the API exposes the full Color
page UI.

## API Reality

The public Resolve scripting API supports useful color automation, but it does
not expose most interactive Color page controls as editable parameters.

### Directly Creatable Or Controllable

These are the safest surfaces for procedural color work:

- CDL values on an existing node:
  - `NodeIndex`
  - `Slope`
  - `Offset`
  - `Power`
  - `Saturation`
- Color versions:
  - add, rename, delete, load, and snapshot local or remote grade versions
- Color groups:
  - create/delete groups
  - assign/remove timeline items
  - inspect group pre-clip and post-clip node graph availability
- Existing node graph state:
  - count nodes
  - read node labels, LUTs, cache state, enabled state, and tools
  - set LUT on an existing node
  - enable/disable an existing node
  - set node cache mode
- LUT and DCTL assets:
  - author/install MCP-marked DCTL files
  - refresh regular LUT/DCTL discovery
  - export LUTs from existing grades
  - apply discovered LUT paths to existing nodes
- Gallery and still assets:
  - grab stills
  - import/export stills and `.drx` grade files
  - label and delete stills
- Full-grade transfer:
  - copy an existing grade to other timeline items
  - apply a `.drx` grade to a graph
  - reset all grades on a graph

### Opaque Full-Grade Operations

These can represent fully featured Resolve grades, but the MCP cannot inspect or
edit every internal decision inside them:

- `CopyGrades([timelineItems])`
- `ApplyGradeFromDRX(path, gradeMode)`
- imported Gallery stills / `.drx` files
- exported LUTs
- existing node graphs created manually in Resolve

Treat these as whole-grade artifacts. They can include complex node trees,
windows, qualifiers, curves, keys, OFX, and tracking if they already exist in
the source grade, but the MCP is applying or copying them as a package.

Important: `ApplyGradeFromDRX` replaces the target graph. It is not an append
operation. Create a version snapshot before applying it.

### Not Directly Creatable From Structured Params

Do not claim the MCP can build these from scratch through the public API:

- new serial, parallel, layer, or outside nodes
- node reordering or mixer construction
- Lift/Gamma/Gain wheel values
- offset/log/HDR palette values
- custom curves or HSL curves
- qualifiers
- power windows
- tracker/window animation
- Color Warper changes
- detailed OFX or ResolveFX parameter edits in the Color page
- a fully editable node tree from JSON

If the user asks for one of these, the agent should either propose a manual
Resolve workflow, use a prebuilt `.drx`/still/LUT/DCTL artifact, or state that
the current API does not expose that control.

## Correction Priorities

Use this order when making or recommending corrections:

1. Technical transform and color management
2. Exposure and contrast
3. White balance and neutral placement
4. Skin tone and memory colors
5. Shot-to-shot continuity
6. Creative look
7. Output legality and deliverable constraints

Do not chase a look before the image is technically coherent. Do not make a shot
match by destroying the thing that matters most in that shot, usually the face,
the product, or the story point.

## Colorist Judgment Principles

The API can move values, but color decisions still need colorist judgment:

- start from representative frames, not metadata alone
- use both scopes and eyes when available; neither is enough alone
- establish black point, white point, and density before chasing style
- protect faces, skin tone, products, and story-critical details before the
  background
- judge memory colors deliberately: skin, sky, foliage, snow, practical lights,
  and known neutrals may be corrected or intentionally bent, but not ignored
- use the focus technique for exposure decisions: push darker/brighter or
  warmer/cooler far enough to find the boundary, then settle back to the useful
  point
- prefer restraint when the media is fragile, highly compressed, 8-bit, noisy,
  clipped, or already display-referred
- when the request is mood-based, such as "dusk", "noir", "warm", or "clean",
  translate that into observable targets: density, highlight level, shadow color,
  saturation, skin protection, and continuity across cuts

If a requested look requires secondaries, windows, curves, texture, or selective
relighting, say so. A CDL can suggest the direction, but it is not a substitute
for a full interactive color pass.

## What CDL Is Good For

CDL is the main procedural correction surface available to the MCP. Use it for
simple, reversible primary moves:

- small exposure balance through `Slope`
- black/mid/white density shaping through `Offset`, `Power`, and `Slope`
- gentle RGB balance shifts
- global saturation trims
- broad shot matching when a node already exists

CDL is not a replacement for:

- curved highlight roll-off
- qualified skin isolation
- windowed relighting
- hue-specific curve work
- texture, halation, glow, grain, or OFX looks
- full scene-level creative grading

Prefer conservative CDL values. Large CDL moves can break skin, clip channels,
or create unnatural color separation.

## What LUTs And DCTLs Are Good For

Use LUTs and DCTLs when the desired transform can be expressed as a reusable
mathematical or lookup-based operation:

- camera/log to viewing transform
- show LUT or creative contrast/saturation curve
- color matrix or channel operation
- technical IDT/ODT-style transform
- repeatable look preview

Use DCTL authoring only for transforms that are appropriate to code. DCTLs can
be powerful, but they are not a substitute for tracked windows, qualifiers, or
hand-shaped secondaries.

Regular LUT/DCTL installs require `project_settings(action="refresh_luts")`.
ACES IDT/ODT DCTLs require a Resolve restart.

## What DRX Is Good For

Use `.drx` and Gallery stills for full Resolve grades:

- prebuilt node trees
- manually created grades
- complex secondaries
- tracked windows
- OFX-based looks
- show looks that should be reused exactly

Before applying DRX:

- save or snapshot the current grade version
- confirm the target graph can be replaced
- use `grade_mode=0` unless source-timecode or start-frame alignment is
  explicitly needed
- verify the result visually with a still, thumbnail, or Gallery export

## Frame Comparison Requirements

For creative grading, shot matching, look development, or changing an existing
grade, compare pictures at matched timecodes whenever the API can safely provide
them:

- untreated or bypass frame: the source without the active grade, captured by
  loading a clean version or temporarily disabling grade nodes, then restoring
  the previous state
- current frame: the active creative baseline before the requested change
- after frame: the same timecode after the change

Use untreated frames as diagnostic evidence, not as permission to discard an
existing grade. If a current grade exists, it is the creative baseline. The
untreated frame explains what the image is made of; the current frame explains
what the colorist or user already chose.

All frame references must be Resolve-rendered and written only to sidecar,
session scratch, or the configured analysis root. Never create derivatives next
to source media. Record the frame, timecode, marker, contact sheet, or still path
that informed the decision.

If untreated/current/after comparison is not available through the API in the
moment, say which part is unavailable and whether the user wants a blind/global
pass. Do not imply that a grade was reviewed if no rendered frames were checked.

## Safe Color Workflow

Before changing color:

- switch to the Color page when required
- call `timeline_item_color(action="grade_boundary_report")`
- call `timeline_item_color(action="grade_version_snapshot")`
- call `timeline_item_color(action="probe_node_graph")`
- check whether the item is in a color group and whether group pre-clip or
  post-clip grades may affect the rendered result
- check whether the requested action is direct, opaque, or unsupported
- inspect representative Resolve-rendered frames for the target shot or shots
  before writing grade changes
- use timeline thumbnails, contact sheets, marker frames, Gallery stills, or
  existing visual analysis reports as the frame reference
- when there is an existing grade, capture current treated frames before making
  the adjustment
- when useful for diagnosis, capture untreated/bypass frames at the same
  timecodes and then restore the original active version or node-enabled state
- note the reference frame, timecode, marker, or contact sheet used to make the
  decision
- if frame review is unavailable, ask before applying a blind/global look unless
  the user explicitly requested blind/global grading

For sequence-wide creative looks:

- confirm the target scope first: current clip, selected clips, current timeline,
  duplicated timeline, color group, or every timeline using the same media
- duplicate the timeline unless the user explicitly wants an in-place/global pass
- create recoverable local grade versions across the whole target set before
  applying the look:
  - reference/base version: a clean version used for diagnosis and A/B
  - current/baseline version: the active creative grade before the new request
  - requested look version: the active version that receives the new pass
- do not call a reference version "ungraded" unless it is truly ungraded; if the
  best available base is `Version 1`, name or report it as a `Version 1`
  reference when its grade state has not been verified
- batch repeated version, group, and CDL operations through a single Resolve
  script or bulk helper when practical; avoid one tool call per clip per step
- use color groups when multiple clips should share scene-level intent, but keep
  per-shot balance and matching on clip versions

Use this group structure when it fits the work:

- group pre-clip: shared normalization or input trim, when the clips genuinely
  need the same upstream correction
- clip: shot-specific balance, exposure, skin, sky, and continuity decisions
- group post-clip: shared creative look or output trim for the sequence

Do not use groups as a shortcut around reviewing shots. A group look can establish
the broad direction, but clip-level review remains responsible for faces,
highlights, skies, foliage, and outliers.

For small corrections:

- use `timeline_item_color(action="safe_set_cdl", params={...})`
- dry-run first when possible
- target an existing node index
- read back grade state afterward, including node tools when exposed

For adjusting an existing grade:

- treat the current grade as the creative baseline, not disposable state
- inspect the active version, available local/remote versions, node count, LUTs,
  cache state, color group membership, and representative frames
- create or switch to a clearly named adjustment version before changing values
- make incremental changes through supported controls such as CDL, LUT assignment
  on existing nodes, node enable/cache state, or accepted grade-copy workflows
- avoid `reset_all_grades`, DRX application, or copied whole-grade replacement
  unless the user explicitly accepts replacement semantics
- explain whether the change adjusted the existing grade, copied a grade, or
  replaced a graph-level artifact
- do not describe Resolve's default one-node graph as an existing creative grade;
  distinguish "default/empty node graph" from "active grade tools present"

For matching:

- choose a hero/reference shot
- copy the grade only when the reference grade is already valid
- otherwise apply a conservative CDL match and review visually
- use color groups for shared scene-level intent when appropriate
- compare against the hero shot and the adjacent cuts, not just the shot in
  isolation

For look development:

- prefer a plan first: CDL, LUT/DCTL, DRX, or manual Resolve work
- generate DCTL/LUT assets only when the transform is suitable for code
- use DRX/stills for complex hand-built looks
- start with hero frames for the look, then test the look on outlier shots before
  applying it broadly
- sampling is acceptable for a fast first-pass direction, not final approval; for
  short sequences, inspect every target shot before handoff
- for long sequences where full review is not feasible in the current turn,
  clearly separate sampled look development from final validation and report the
  remaining unreviewed scope

After changing color:

- grab or export after frames for visual confirmation when useful
- compare against the same untreated/current reference frames or reference shot
- confirm no obvious clipping, bad skin tone, or mismatch was introduced
- check whether the intended effect actually reads as requested, and revise if
  the first pass is only technically different rather than creatively successful
- re-probe grade versions and node graph state when the change should have
  modified node tools, LUTs, cache, or enabled state
- keep the original grade recoverable through versions or Gallery stills
- confirm the active version at handoff and note whether a reference/base version
  was created, assumed from an existing version, or unavailable

## Review Notes And Handoff

Assistant-style documentation makes automated color work easier to trust:

- report the active version before and after the operation
- report the target scope and whether the operation happened on the original
  timeline, a duplicated timeline, a color group, or selected clips
- report any created reference/current/look versions and whether the reference
  was verified as truly ungraded
- report whether the node graph was default/empty, carried active tools, used a
  LUT, or belonged to a color group
- report the operation type: CDL adjustment, LUT assignment, copied grade, DRX
  replacement, DCTL/LUT asset creation, or review only
- report the frame references used for the decision and whether they were
  untreated, current, or after frames
- report known limits, such as compressed source, clipped highlights, missing
  thumbnails, unavailable Gallery export, or unsupported node construction
- use timeline markers, clip colors, or notes for review flags when the API
  supports them and the user wants persistent review state

Do not promise node labels or node colors unless the available API path can
actually write them. Existing labels, LUTs, tools, and cache state can be
inspected and reported.

## Pre-flight Coverage Check (required)

Before answering any shot-matching, look-development, or per-clip grade question,
call `timeline_item_color(action="grade_evidence_base", params={...})` against the
target clip. The action is a pure read — it never mutates and never triggers
analysis. It composes the version snapshot, node graph, color group, and
`coverage_report` for the underlying media pool item into a single one-line
`evidence_base` string. **Lead your response with that line — before any grade
recommendation.**

For sequence-wide checks (multiple clips, bin, timeline), use
`media_analysis(action="coverage_report")` as before — the broader pre-flight
covers all targets in one call.

The response carries an `evidence_base` string and per-clip details: layer
presence, source-trust tier, staleness reasons, relink supersedure, and a
`recommended_action`. **Lead your response to the user with the `evidence_base`
line — before any grade recommendation.**

For color work, source-trust matters more than for editorial. Use the
`min_source_trust` parameter to gate recommendations:

- `coverage_report(min_source_trust="medium")` for routine corrections.
- `coverage_report(min_source_trust="high")` for hero shots, look-development
  passes, and any decision that depends on confident scene/lighting recognition.

Clips below the threshold appear in `summary.clips_needs_higher_trust` and
should be re-analyzed with an explicit higher `source_trust` before being graded
from their visual descriptions.

Relink-superseded clips (`superseded_by_relink=true`) must never be reasoned
about as if the prior analysis still describes the current media. The prior
report is preserved for reference, but a re-analysis is required before
shot-matching or look development is grounded.

If existing analysis flags exposure issues, clipped highlights, color cast
warnings, or scene-of-interest notes, surface those before proposing CDL or
node-graph changes.

## Agent Response Rules

When answering a color request, classify the requested operation:

- Direct API grade: CDL, LUT assignment, version, group, cache, enable/disable
- Opaque full grade: copy grade, apply DRX, import/export stills
- Asset authoring: LUT or DCTL creation/install
- Review only: stills, thumbnails, visual analysis, boundary reports
- Unsupported direct control: windows, qualifiers, curves, wheels, node-tree
  construction, tracker controls, OFX parameter edits

Then explain the safest available route. Be explicit about limitations. A good
answer sounds like:

> "I can make this as a conservative CDL correction, or apply/copy a full grade
> from a DRX/still. I cannot construct the windowed qualifier node tree directly
> through the public API."

Do not invent Color page controls that are not exposed. Do not imply that a LUT,
DCTL, or CDL is equivalent to a full colorist pass.

## Useful MCP Calls

- `media_analysis(action="coverage_report", params={...})` — pre-flight evidence-base check
- `resolve_control(action="open_page", params={"page": "color"})`
- `timeline_item_color(action="grade_boundary_report", params={...})`
- `timeline_item_color(action="probe_grade_item", params={...})`
- `timeline_item_color(action="probe_node_graph", params={...})`
- `timeline_item_color(action="grade_version_snapshot", params={...})`
- `timeline_item_color(action="safe_set_cdl", params={...})`
- `timeline_item_color(action="safe_copy_grade", params={...})`
- `timeline_item_color(action="safe_apply_drx", params={...})`
- `timeline_item_color(action="safe_export_lut", params={...})`
- `graph(action="set_lut", params={...})`
- `graph(action="apply_grade_from_drx", params={...})`
- `gallery_stills(action="grab_and_export", params={...})`
- `dctl(action="install", params={...})`
- `project_settings(action="refresh_luts")`

Use `safe_*`, probe, snapshot, and dry-run actions before mutation whenever they
exist.
