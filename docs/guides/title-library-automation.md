# Native title and subtitle library automation

Keep Resolve Studio open. Discover the installed factory Fusion presets with
`timeline_ai(action="list_title_presets", params={})`. The inventory names the
local archive, category and full template ID; it does not imply live acceptance.
Use `templates_archive` when automatic discovery cannot find a custom installation.
Factory inventory does not enumerate third-party packs or the basic non-template
Text/Scroll generators. Installed fonts and tool availability remain host-specific.

## Ordinary Fusion titles

Insert with `timeline(action="insert_fusion_title", params={"name":
"Templates/Edit/Titles/Candy"})`, then identify the inserted clip and use
`fusion_comp.probe_fusion_comp` / `probe_fusion_tool` with `clip_id` or an explicit
timeline-item selector. Read the actual graph and controls before editing.
`safe_set_inputs` can set literal inputs on the inspected tool, including text,
font, size and colour. Many presets use TextPlus; others use sText or Text3D.
Do not assume every template has a tool called `Template`, flatten connected
animation controls, or overwrite text instances linked to another tool.

`timeline.set_title_text` also supports literal TextPlus, sText, Text3D and
MultiText inputs. For a connected StyledTextFollower it edits the modifier's
literal `Text` input; for PublishText it uses `Value`. MultiText uses the native
`TextN.StyledText` controls in native `TextOrder`; `TextValueN` changes list
labels without changing rendered text. Expressions and
unknown modifier chains are refused rather than flattened. The default text
action edits the first supported text target; use explicit Fusion tools when
changing multiple independent title lines. Render to verify the resulting text.

Use the full template ID rather than a leaf name: `Statement` exists both as an
ordinary title and an animated subtitle. Probe `comp.GetData("TEMPLATE_ID")`
to confirm which template native insertion selected.

## Subtitle-track presets

```json
{"action":"set_subtitle_preset","params":{
  "preset":"Templates/Edit/Titles/Subtitles/Animated/Rotate",
  "inputs":{"size":0.06,"position":[0.5,0.25],
            "textRed":0.15,"textGreen":0.85,"textBlue":1}
}}
```

The live helper captures the installed template in its own temporary timeline,
exports its native composition, restores the working timeline and removes only
that temporary capture. It swaps the exported subtitle holder composition,
imports a recoverable revision, checks edit/media inventory and re-exports the
revision to confirm native preset/control retention. The original timeline and
exports remain intact. It never writes an open Project.db or changes source files.

Common mapped literal controls are `font`, `fontStyle`, `size`, `position`,
`textRed`, `textGreen`, `textBlue` and `textAlpha`. Highlight/outline mappings are
specific to Word Highlight. Unsupported controls/layouts and animated or
connected input replacements are refused. An imported preset readback is not a
rendered check. Inspect caption word phases, gaps and safe margins.

Gradient/image fills do not render their dormant solid RGB values. A subtitle
colour edit refuses that case unless `textFillMode:"solid"` explicitly requests
replacement of the fill mode. Grey with Shadow uses a native gradient; preserve
it when editing only font/size/position, or explicitly select solid fill when
requesting a uniform colour. The gradient data/reference stays recoverable.
For ordinary Fusion titles, inspect the active shading mode/gradient controls;
a raw RGB readback alone does not establish the rendered fill colour.

Word Highlight and Lollipop have bundled native references. Other factory
subtitle presets require the local installation or an explicit native subtitle
`preset_reference`. Unbundled dry runs require a pre-existing reference so no
live temporary title is created during preview.

## Repeatable acceptance

The [Windows acceptance record](../notes/title-library-acceptance.md) documents
134 final passing cases and an interrupted ordinary-title retest that required
automatic Studio crash recovery. It does not establish universal restart-free
reliability or Mac compatibility.

`tests/live_title_library_validation.py` requires an already-open disposable
`MCP_QA_*` project with the synthetic caption fixture. It refuses to launch
Resolve, renders representative native frames, records property readback and
pixel differences, persists every case, retains test timelines and restores the
original timeline/page/playhead. Only synthetic project contents may be used.

```powershell
venv/Scripts/python.exe tests/live_title_library_validation.py --output-dir logs/title-library-full
```

The image metrics require Pillow and NumPy; `--image-python` can use an independent
Python installation with those packages. It runs in isolated mode, avoiding
Resolve's Python environment. `--only` selects exact names/IDs for a focused
retest. `scripts/title_library_report.py` builds a local HTML matrix and contact
sheets from one or more reports; a later retest replaces the same template's case.
The HTML uses relative links to copied QA renders under its `frames/` folder;
move the entire output folder to view it on another machine. Saved QA records
replace host workspace/home paths with anonymous markers; they do not retain
the local account name or workspace folder identity.

Acceptance distinguishes native application, literal property readback and
sampled rendered appearance. It does not certify all controls, every animation
frame, third-party packs, or Mac compatibility. Test Mac separately before
claiming cross-platform live acceptance.
