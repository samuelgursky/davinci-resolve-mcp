# Authoring DaVinci Resolve Custom Effects (`.setting` files)

Guide and reference for hand-authoring DaVinci Resolve effects, transitions,
titles, generators, and Fusion macros as `.setting` files — the serialized
Fusion-composition format Resolve indexes from its Templates directory. No
plugin SDK, no compile step. Start from a [template](templates/) and consult the
[reference docs](#reference-docs) for the format and the hard-won gotchas.

Use this when a task touches building a new effect, packaging a Fusion comp as a
reusable template, making a title or transition preset, editing
`InstanceInput`/`UserControls`, or the `.setting` file format, thumbnail
conventions, or the Fusion Templates install directory.

## What a `.setting` file actually is

A `.setting` file is a **Fusion composition serialized as a Lua table**. It is NOT a custom binary format — it's a readable, hand-editable text file. When Resolve loads it, Fusion instantiates every node described in the file; when the user drops the template onto a clip, Fusion wires the clip into the node graph using the `MainInput*` hooks declared at the top of the file.

Everything you need to build a custom Resolve effect lives in that single text file plus a handful of PNG thumbnails that sit next to it. No plugin SDK, no code signing, no compile step.

## The Five Categories You Can Ship

There are five roles a `.setting` file can play. Each hooks into a different part of the Resolve UI and has different wiring requirements:

| Role | Location (user install) | MainInputs | MainOutputs | Typical top-level node |
|------|-------------------------|-----------|-------------|------------------------|
| **Edit Effect** (clip filter) | `Templates/Edit/Effects/` | `MainInput1` → source clip | `MainOutput1` → result | GroupOperator |
| **Edit Transition** | `Templates/Edit/Transitions/` | `MainInput1` (Background) + `MainInput2` (Foreground) | `MainOutput1` | GroupOperator |
| **Edit Title** | `Templates/Edit/Titles/` | *(none — generates)* | `MainOutput1` | GroupOperator wrapping TextPlus |
| **Edit Generator** | `Templates/Edit/Generators/` | *(none — generates)* | `MainOutput1` | GroupOperator or raw node |
| **Fusion Macro** (Tools / Backgrounds / Generators / Particles / Shaders / Styled Text / Motion Graphics / Lens Flares / How To) | `Templates/Fusion/<subfolder>/` | Optional — whatever makes sense for that node type | Optional | GroupOperator OR raw tool(s) |

**Fusion/Looks is different — it is NOT a `.setting` file.** Looks are `.alut3` files (plain-text 3D LUTs with an `F5LT3` header). They apply via the Color page, not Fusion. Don't confuse them with the composition-based categories.

## Install Paths

User-installed templates go here (create any missing subfolders):

- **Windows**: `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Templates\<role>\<category>\`
- **macOS (user)**: `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Templates/<role>/<category>/`
- **macOS (system-wide)**: `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Templates/<role>/<category>/`

`<role>` is literally `Edit` or `Fusion`. `<category>` mirrors the folders you see in the effects library (`Effects`, `Transitions`, `Titles`, `Generators`, `Tools`, `Backgrounds`, etc.). Restart Resolve after dropping new files in; they get indexed at launch.

**The `<category>` subfolder is not optional.** A file at `Templates/Edit/MyEffect.setting` (loose in `Edit/`, no category folder) is invisible to the Edit page — it falls through to the Fusion-page library instead, which silently indexes anything under `Templates/`. Always write the full path including the category: `Templates/Edit/Effects/MyEffect.setting`. Same rule applies to Fusion macros (`Fusion/Tools/`, not loose in `Fusion/`). See gotcha 18.

## Anatomy of a `.setting` File

The outermost structure is always a table containing a `Tools` list and (optionally) an `ActiveTool` pointer:

```lua
{
    Tools = ordered() {
        MyEffect = GroupOperator {
            Inputs = ordered() { ... exposed controls ... },
            Outputs = { MainOutput1 = InstanceOutput { ... } },
            Tools = ordered() { ... the internal node graph ... }
        }
    },
    ActiveTool = "MyEffect"
}
```

- `ordered() { ... }` preserves the order of keys (regular `{}` tables do not). Use it anywhere the order matters — the `Inputs` list drives the display order of controls in the inspector.
- `MyEffect` is the internal tool ID. It must be a valid identifier (letters/digits/underscore) and match `ActiveTool`.
- The **outer** `Tools` list is the top level of the composition; the **inner** `Tools` list inside the GroupOperator is the macro's internal graph.

Inside the GroupOperator you have three sections:

1. **`Inputs = ordered() { ... }`** — the controls the user sees in the inspector. Each entry is an `InstanceInput` that re-exposes one parameter of one internal node. `MainInput1` / `MainInput2` are reserved for clip wiring.
2. **`Outputs = { ... }`** — what the rest of the pipeline sees. `MainOutput1` is the pixel output Resolve reads.
3. **`Tools = ordered() { ... }`** — the actual internal nodes (Blur, Merge, Background, ofx.*, TextPlus, etc.) with their parameters and connections between each other via `SourceOp` / `Source`.

## Wiring Rules That Matter

- **`SourceOp = "NodeName"`, `Source = "OutputName"`** is how you connect nodes. The referenced node must exist in the same `Tools` list. Outputs are typed — image tools use `"Output"`, mask tools use `"Mask"`, value nodes use `"Value"`, text outputs `"Result"`.
- **`MainInput1`'s `Source` must be the node input Resolve should feed the clip into.** On effects, that's typically `"Input"` on the first node. On transitions, `MainInput1` and `MainInput2` both point at a `Merge` or `Dissolve` node's `Background` / `Foreground`.
- **Transition progress is automatic** — don't try to wire a "progress" parameter. The idiom is: drive your transition with a `Dissolve` node whose `Mix` is sourced from an `AnimCurves = LUTLookup` using `Curve = FuID { "Easing" }`. Fusion evaluates that curve across the clip length and you get a free 0→1 ramp shaped by the easing you chose.
- **Titles use `KeyStretcher`** to make their internal animation stretch to fit the clip length. Wrap your animated `TextPlus` output with a `KeyStretcher` and output that from `MainOutput1`.
- **Generators / Backgrounds have no MainInput** — they're pure sources. Just expose the interesting params and point `MainOutput1` at the terminal node.

## Exposing Controls

Every user-visible control in the inspector is an `InstanceInput` that re-publishes an input of one of your internal nodes. Pattern:

```lua
Intensity = InstanceInput {
    SourceOp = "PrismBlur1",       -- the internal node
    Source   = "AberrationStrength", -- its parameter
    Name     = "Aberration",       -- label in the inspector (optional — defaults to Source)
    Default  = 0.4,                -- initial value
    MinScale = 0,                  -- soft slider minimum
    MaxScale = 1,                  -- soft slider maximum
    Page     = "Controls",         -- which inspector tab this sits on
    ControlGroup = 4,              -- group with other inputs sharing this number (colors, etc.)
    Width    = 0.5,                -- horizontal width fraction (0-1) for side-by-side layouts
},
```

See `references/controls.md` for the complete control-attribute catalog, how `ControlGroup` collapses R/G/B/A into a single color picker, and how to add **new** controls (buttons, checkboxes, labels) that aren't tied to an existing node input using `UserControls`.

## Thumbnails

Each `.setting` ships with a bundle of PNG thumbnails named after the `.setting` file. Thumbnail shape depends on the category:

| Category | Files you need |
|----------|---------------|
| Edit/Effects, Generators, Fusion/Tools, Backgrounds, Generators, Particles, Shaders, Lens Flares, Motion Graphics, How To, Styled Text | `Name.large.png` (128×128), `Name.large@2x.png` (256×256), `Name.small.png` (30×30), `Name.small@2x.png`, plus `.small.active/hover/push` button-state variants |
| Edit/Transitions | `Name.small.*` suite (30×30) + `Name.wide.png` (52×29) + `@2x` versions |
| Edit/Titles | `Name.wide.png` (52×29) + `Name.wide@2x.png` (104×58) — no `.large` or `.small` |

Resolve will render a missing thumbnail from a generic placeholder (`_default.png` exists as a fallback in some stock folders). You can ship with only `.large.png` + `@2x` for a quick-and-dirty effect; the inspector degrades gracefully. See `references/thumbnails.md` for the exhaustive list.

## The Five-Minute Recipe

1. **Decide the role.** Effect / Transition / Title / Generator / Fusion macro. This sets your MainInputs, template file, and install path.
2. **Prototype the node graph in Fusion first.** Open Resolve → Fusion page → build your composition → select your nodes → right-click → **Macro → Create Macro…**. Save it. That gives you a working `.setting` file with the outer structure correct. 99% of real-world authoring starts from a working Fusion comp, not from a blank text editor.
3. **Open the resulting `.setting` file** in a text editor and rename / reorder / prune the `Inputs` list until the inspector shows only the controls you want, in the order you want.
4. **Set `Default`, `MinScale`, `MaxScale`, `Name`, `Page`, `ControlGroup`, `Width`** on each `InstanceInput` to tune presentation.
5. **Drop it into the correct Templates subfolder**, add thumbnails alongside, restart Resolve, and test from the Effects Library.

Templates for each category live in `templates/`. Copy one and modify.

## When NOT to Use This Skill

- **OFX plugins.** Those are compiled C++ shared libraries — completely separate system, not `.setting` files.
- **Color grade LUTs.** `.cube` / `.3dl` / `.alut3` files go in the LUT directory and apply from the Color page. Don't confuse `Fusion/Looks/*.alut3` with custom effects.
- **Project-wide scripting.** If you want to *drive* Resolve (build timelines, apply grades, queue renders), use this server's MCP tools (see [docs/SKILL.md](../../SKILL.md)) — not a custom template.

## Reference Docs

| File | What's in it |
|------|-------------|
| `references/format.md` | Full `.setting` Lua-table syntax: `ordered()`, `Input`, `FuID`, `BezierSpline`, `LUTLookup`, `GroupOperator`, `InstanceOutput`, `CustomData`, `UserControls` shape |
| `references/controls.md` | Every `InstanceInput` attribute + `UserControls` control types (SliderControl, ButtonControl, CheckboxControl, LabelControl, MultiButtonControl) with examples |
| `references/category-patterns.md` | Side-by-side minimal skeletons for Effect vs Transition vs Title vs Generator vs Fusion macro — shows what's different about each |
| `references/thumbnails.md` | Exact filename grid, dimensions, which files are required vs optional per category |
| `references/gotchas.md` | Hard-won rules: transition progress curves, `KeyStretcher` on titles, what breaks when you rename `ActiveTool`, SourceOp name collisions, the difference between `Inputs = {}` (unordered) and `Inputs = ordered() {}` |
| `templates/MCP Test Blur.setting` | Minimal clip-filter effect — one Blur exposed as "Strength" (Edit / Effects) |
| `templates/MCP Test Vignette.setting` | Ellipse-mask vignette darkening the edges — exercises mask-feeding + Merge.Blend (Edit / Effects) |
| `templates/MCP Test Color Tint.setting` | Tint via colored Background → Merge, with `ControlGroup` collapsing R/G/B/A into a single color picker (Edit / Effects) |
| `templates/MCP Test Wipe.setting` | Gradient-map luma wipe transition with an easing curve (Edit / Transitions) |
| `templates/MCP Test Iris.setting` | Circular iris transition using an EllipseMask as the Dissolve.Map (Edit / Transitions) |
| `templates/MCP Test Cross Dissolve.setting` | Dead-simplest transition — `DFTDissolve` with no Map, just a Mix ramp (Edit / Transitions) |
| `templates/MCP Test Title.setting` | Minimal TextPlus title with Color/Size/Position controls (Edit / Titles) |
| `templates/MCP Test Lower Third.setting` | TextPlus + RectangleMask-bordered Background composite — exercises multi-node title composition (Edit / Titles) |
| `templates/MCP Test Fade Title.setting` | TextPlus with animated alpha via a `BezierSpline`, stretched by `KeyStretcher` (Edit / Titles) |
| `templates/MCP Test Noise.setting` | FastNoise generator with Detail/Contrast/Scale/Speed controls (Edit / Generators) |
| `templates/MCP Test Solid Color.setting` | Solid-color Background with `ControlGroup` color picker (Edit / Generators) |
| `templates/MCP Test Gradient.setting` | Linear gradient Background with exposed Start/End points and Gradient colors widget (Edit / Generators) |
| `templates/MCP Test Glow.setting` | Minimal Fusion-page tool with MainInput + one control (Fusion / Tools) |

**Start from a template.** Copying `templates/MCP Test Blur.setting` and renaming it is ~10x faster than writing one from scratch and the result will always be well-formed. The filenames match what shows up in Resolve's Effects Library, so renaming the copy is all you need to do to change the display name.
