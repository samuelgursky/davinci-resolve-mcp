# Category Patterns

Every category hooks into Resolve slightly differently. This file shows the **minimum viable skeleton** for each, and what changes between them. Start with the shape that matches your target category, then modify.

## 1. Edit Effect (clip filter)

**Role:** pixel filter applied to a single clip. Reads the clip, writes a processed version.

**Hook:** exactly one `MainInput1` connected to the internal "entry" node's `Input` parameter.

```lua
{
    Tools = ordered() {
        MyEffect = GroupOperator {
            Inputs = ordered() {
                MainInput1 = InstanceInput {
                    SourceOp = "Blur1",
                    Source   = "Input",
                },
                Strength = InstanceInput {
                    SourceOp = "Blur1",
                    Source   = "XBlurSize",
                    Default  = 5,
                    MinScale = 0,
                    MaxScale = 100,
                },
            },
            Outputs = {
                MainOutput1 = InstanceOutput {
                    SourceOp = "Blur1",
                    Source   = "Output",
                },
            },
            Tools = ordered() {
                Blur1 = Blur {
                    Inputs = {
                        Filter    = Input { Value = FuID { "Fast Gaussian" } },
                        XBlurSize = Input { Value = 5 },
                        LockXY    = Input { Value = 1 },
                    },
                },
            },
        },
    },
    ActiveTool = "MyEffect",
}
```

**Install path:** `Templates/Edit/Effects/`.

## 2. Edit Transition

**Role:** blends between two clips over a duration.

**Hook:** two MainInputs — `MainInput1` (Background, the outgoing clip) and `MainInput2` (Foreground, the incoming clip). Both feed a `Dissolve` or `Merge` node.

**Progress animation:** driven by a `LUTLookup` reading `FuID { "Duration" }` with an easing curve. Fusion automatically evaluates the curve across the transition length and outputs a 0→1 ramp.

```lua
{
    Tools = ordered() {
        MyTransition = GroupOperator {
            Inputs = ordered() {
                MainInput1 = InstanceInput {
                    SourceOp = "Dissolve1",
                    Source   = "Background",
                },
                MainInput2 = InstanceInput {
                    SourceOp = "Dissolve1",
                    Source   = "Foreground",
                },
                Softness = InstanceInput {
                    SourceOp = "Dissolve1",
                    Source   = "DFTLumaRamp.Softness",
                    Default  = 0.05,
                    MinScale = 0,
                    MaxScale = 1,
                },
            },
            Outputs = {
                MainOutput1 = InstanceOutput {
                    SourceOp = "Dissolve1",
                    Source   = "Output",
                },
            },
            Tools = ordered() {
                Dissolve1 = Dissolve {
                    Inputs = {
                        Operation = Input { Value = FuID { "DFTDissolve" } },
                        Mix = Input {
                            SourceOp = "ProgressCurve",
                            Source   = "Value",
                        },
                    },
                },
                ProgressCurve = LUTLookup {
                    Inputs = {
                        Source = Input { Value = FuID { "Duration" } },
                        Curve  = Input { Value = FuID { "Easing" } },
                        EaseIn  = Input { Value = FuID { "Cubic" } },
                        EaseOut = Input { Value = FuID { "Cubic" } },
                        Lookup = Input {
                            SourceOp = "ProgressCurveLookup",
                            Source   = "Value",
                        },
                    },
                },
                ProgressCurveLookup = LUTBezier {
                    KeyColorSplines = {
                        [0] = {
                            [0] = { 0, RH = { 0.333, 0.333 }, Flags = { Linear = true } },
                            [1] = { 1, LH = { 0.666, 0.666 }, Flags = { Linear = true } }
                        }
                    },
                    SplineColor = { Red = 255, Green = 255, Blue = 255 },
                },
            },
        },
    },
    ActiveTool = "MyTransition",
}
```

**Install path:** `Templates/Edit/Transitions/`.

**Transition operations worth knowing (for `Dissolve.Operation`):**

| FuID | Effect |
|------|--------|
| `DFTDissolve` | Straight cross-dissolve |
| `DFTLumaRamp` | Wipe driven by the `Map` input's luma — lets you shape the wipe with any image |
| `DFTAdditiveDissolve` | Additive blend |

`DFTLumaRamp` is the workhorse for wipes: pipe a gradient or shape into `Map` and you get a controllable wipe. Box Wipe and most stock transitions use this pattern.

## 3. Edit Title

**Role:** text generator with stretched animation.

**Hooks:** no MainInput. Wraps a `TextPlus` node. Internal animation is piped through a `KeyStretcher` so it stretches to the clip's actual duration.

```lua
{
    Tools = ordered() {
        MyTitle = GroupOperator {
            Inputs = ordered() {
                Input1 = InstanceInput { SourceOp = "Text", Source = "StyledText" },
                Input2 = InstanceInput { SourceOp = "Text", Source = "Font",  ControlGroup = 2 },
                Input3 = InstanceInput { SourceOp = "Text", Source = "Style", ControlGroup = 2 },
                Size   = InstanceInput { SourceOp = "Text", Source = "Size",   Default = 0.08 },
                Pos    = InstanceInput { SourceOp = "Text", Source = "Center", Name = "Position" },
                Red    = InstanceInput { SourceOp = "Text", Source = "Red",   Name = "Color", ControlGroup = 10, Default = 1 },
                Green  = InstanceInput { SourceOp = "Text", Source = "Green", Name = "Color", ControlGroup = 10, Default = 1 },
                Blue   = InstanceInput { SourceOp = "Text", Source = "Blue",  Name = "Color", ControlGroup = 10, Default = 1 },
                Alpha  = InstanceInput { SourceOp = "Text", Source = "Alpha", Name = "Color", ControlGroup = 10, Default = 1 },
            },
            Outputs = {
                MainOutput1 = InstanceOutput {
                    SourceOp = "Stretcher",
                    Source   = "Result",
                },
            },
            Tools = ordered() {
                Text = TextPlus {
                    Inputs = {
                        GlobalOut = Input { Value = 500 },
                        Width     = Input { Value = 1920 },
                        Height    = Input { Value = 1080 },
                        UseFrameFormatSettings = Input { Value = 1 },
                        StyledText = Input { Value = "SAMPLE" },
                        Font       = Input { Value = "Open Sans" },
                        Style      = Input { Value = "Bold" },
                        Size       = Input { Value = 0.08 },
                        VerticalJustificationNew   = Input { Value = 3 },
                        HorizontalJustificationNew = Input { Value = 3 },
                    },
                },
                Stretcher = KeyStretcher {
                    Inputs = {
                        Keyframes = Input {
                            SourceOp = "Text",
                            Source   = "Output",
                        },
                        SourceEnd   = Input { Value = 119 },
                        StretchStart = Input { Value = 10 },
                        StretchEnd   = Input { Value = 100 },
                    },
                },
            },
        },
    },
    ActiveTool = "MyTitle",
}
```

**Install path:** `Templates/Edit/Titles/`.

Key details:

- `MainOutput1` pulls `Source = "Result"` from the `KeyStretcher` (not `"Output"` — that's the unstretched pixels).
- Animation on the `TextPlus` (via `BezierSpline` inputs for Alpha, Size, Color, etc.) gets stretched to match the clip length by `KeyStretcher`.
- Stock titles often expose *many* text controls (font, style, size, tracking, line spacing, V/H anchor, color, background color). Copy the pattern from `Edit/Titles/Background Reveal.setting` if you want the full treatment.

## 4. Edit Generator

**Role:** pure pixel source. No input clip — just produces an image.

**Hooks:** no MainInput. One `MainOutput1`.

```lua
{
    Tools = ordered() {
        MyGenerator = GroupOperator {
            Inputs = ordered() {
                Detail = InstanceInput {
                    SourceOp = "Noise1",
                    Source   = "Detail",
                    Default  = 5,
                    MinScale = 0,
                    MaxScale = 10,
                },
                Scale = InstanceInput {
                    SourceOp = "Noise1",
                    Source   = "XScale",
                    Default  = 10,
                    MinScale = 1,
                    MaxScale = 50,
                },
            },
            Outputs = {
                MainOutput1 = InstanceOutput {
                    SourceOp = "Noise1",
                    Source   = "Output",
                },
            },
            Tools = ordered() {
                Noise1 = FastNoise {
                    Inputs = {
                        Width  = Input { Value = 1920 },
                        Height = Input { Value = 1080 },
                        UseFrameFormatSettings = Input { Value = 1 },
                        Detail = Input { Value = 5 },
                        XScale = Input { Value = 10 },
                    },
                },
            },
        },
    },
    ActiveTool = "MyGenerator",
}
```

**Install path:** `Templates/Edit/Generators/`.

## 5. Fusion Tool

**Role:** pixel filter applied on the Fusion page. Reads an upstream image, writes a processed version. Functionally identical to an Edit Effect but installed on the Fusion page.

**Hook:** `GroupOperator` with `MainInput1` wired to the first internal node's `Input`. Internal nodes can carry `UserControls` on sub-nodes — those controls surface automatically without needing to be re-declared as `InstanceInput`. The duplicate-top-level-node artifact: nodes referenced from inside the group also appear again at the outer top level of the file (a serialization quirk) — do not try to remove them.

```lua
{
    Tools = ordered() {
        MyFusionTool = GroupOperator {
            Inputs = ordered() {
                MainInput1 = InstanceInput {
                    SourceOp = "Transform1",
                    Source   = "Input",
                },
                Magnitude = InstanceInput {
                    SourceOp = "Expr1",
                    Source   = "n1",
                    Name     = "Overall Magnitude",
                    Default  = 0.5,
                },
            },
            Outputs = {
                MainOutput1 = InstanceOutput {
                    SourceOp = "Transform1",
                    Source   = "Output",
                },
            },
            Tools = ordered() {
                Expr1 = Custom {
                    -- drives transform amounts
                },
                Transform1 = Transform {
                    Inputs = {
                        Input = Input { SourceOp = "...", Source = "Output" },
                        -- ...
                    },
                },
            },
        },
        -- serialization artifact: inner nodes appear here too
        Transform1 = Transform { -- ...
        },
    },
    ActiveTool = "MyFusionTool",
}
```

**Install path:** `Templates/Fusion/Tools/`.

**Key details:**

- Structure is identical to an Edit Effect — `GroupOperator` + `MainInput1` + `MainOutput1`.
- Sub-nodes can have `UserControls` blocks (e.g., `RangeControl` pairs on `Shake` nodes) that surface in the inspector without needing extra `InstanceInput` declarations.
- The top-level `Tools` block will contain duplicate entries for inner nodes — this is normal and required by Resolve's serializer; do not delete them.

---

## 6. Fusion Background

**Role:** pure 3D pixel source — no input clip, produces a rendered image. Backgrounds are typically full 3D scene pipelines, not 2D procedural generators.

**Hook:** two valid shapes exist in the stock library. (a) Wrapped: a `GroupOperator` with no `MainInput` and a single output (either `MainOutput1` or `Output1`) sourced from a `Renderer3D`. (b) Unwrapped: raw top-level nodes with `ActiveTool` pointing to the terminal `Renderer3D`. The canonical pipeline is `Shape3D → [Bender3D / Transform3D] → Merge3D → Camera3D → Renderer3D`.

```lua
-- Wrapped variant (e.g., Blue Rays.setting)
{
    Tools = ordered() {
        MyBackground = GroupOperator {
            Inputs = ordered() {
                Color = InstanceInput {
                    SourceOp = "Shape3D1",
                    Source   = "MtlStdInputs.Diffuse.Color.Red",
                    ControlGroup = 1,
                    Default  = 0.08,
                },
                -- more color / glow controls ...
            },
            Outputs = {
                MainOutput1 = InstanceOutput {
                    SourceOp = "Renderer3D1",
                    Source   = "Output",
                },
            },
            Tools = ordered() {
                Shape3D1  = Shape3D  { -- geometry source
                    Inputs = { Shape = Input { Value = FuID { "SurfaceCylinderInputs" } } },
                },
                Merge3D1  = Merge3D  { Inputs = { SceneInput1 = Input { SourceOp = "Shape3D1",  Source = "Output" } } },
                Camera3D1 = Camera3D { },
                Renderer3D1 = Renderer3D {
                    Inputs = {
                        SceneInput = Input { SourceOp = "Merge3D1", Source = "Output" },
                        Width  = Input { Value = 1920 },
                        Height = Input { Value = 1080 },
                    },
                },
            },
        },
    },
    ActiveTool = "MyBackground",
}

-- Unwrapped variant (e.g., Bender.setting): raw nodes at top level
-- ActiveTool = "Renderer3D1_2"  -- Resolve previews this node
```

**Install path:** `Templates/Fusion/Backgrounds/`.

**Key details:**

- No `MainInput` — these are pure sources.
- Wrapped files may use either `MainOutput1` or `Output1` for the group output. `MainOutput1` is preferred for consistency with Edit categories; `Output1` also works.
- Unwrapped files have no `GroupOperator` at all. `ActiveTool` must point to the `Renderer3D` so Resolve knows what to preview in the browser.
- The minimum 3D pipeline is `Shape3D → Merge3D → Camera3D → Renderer3D`. Lights (`LightPoint`, `AmbientLight`) are added into the `Merge3D` as additional scene inputs.

---

## 7. Fusion Generator

**Role:** 3D geometry generator, not a 2D pixel source. Unlike Edit Generators (which wrap `FastNoise` or similar 2D nodes), Fusion Generators produce 3D geometry and expose their `MainInput` slots as **material** inputs, not image inputs.

**Hook:** `GroupOperator` with `MainInput1`…`N` wired to `MaterialInput` on `Shape3D` nodes (one per geometry part). The output is a rendered image from a `Renderer3D`.

```lua
{
    Tools = ordered() {
        MyGenerator = GroupOperator {
            Inputs = ordered() {
                MainInput1 = InstanceInput {
                    SourceOp = "Shape3D1",
                    Source   = "MaterialInput",
                    Name     = "Outer Material",
                },
                MainInput2 = InstanceInput {
                    SourceOp = "Shape3D2",
                    Source   = "MaterialInput",
                    Name     = "Inner Material",
                },
                -- geometry controls (radius, height, subdivision, etc.)
                OutRadius = InstanceInput {
                    SourceOp = "Shape3D1",
                    Source   = "SurfaceCylinderInputs.Radius",
                    Name     = "Outer Radius",
                },
            },
            Outputs = {
                MainOutput1 = InstanceOutput {
                    SourceOp = "Renderer3D1",
                    Source   = "Output",
                },
            },
            Tools = ordered() {
                Shape3D1    = Shape3D    { Inputs = { Shape = Input { Value = FuID { "SurfaceCylinderInputs" } } } },
                Shape3D2    = Shape3D    { -- ...
                },
                Merge3D1    = Merge3D    { Inputs = { SceneInput1 = Input { SourceOp = "Shape3D1", Source = "Output" },
                                                      SceneInput2 = Input { SourceOp = "Shape3D2", Source = "Output" } } },
                Camera3D1   = Camera3D   { },
                Renderer3D1 = Renderer3D { Inputs = { SceneInput = Input { SourceOp = "Merge3D1", Source = "Output" } } },
            },
        },
    },
    ActiveTool = "MyGenerator",
}
```

**Install path:** `Templates/Fusion/Generators/`.

**Key details:**

- `MainInput1`…`MainInputN` are **material** connections (wired to `Shape3D.MaterialInput`), not image inputs. Users plug in Shader presets or `MtlBlinn` materials, not video clips.
- Each geometry part that should accept a custom material needs its own `MainInputN` slot.
- The file still renders a preview image via `Renderer3D` — `MainOutput1` sources from it.
- Geometry controls (radius, height, subdivision) are surfaced as `InstanceInput` entries targeting the specific `Shape3D` sub-parameters.

---

## 8. Fusion How To

**Role:** pedagogical comp — illustrates a technique, not a reusable tool. Not designed to be wired into a user's timeline.

**Hook:** no standard I/O. Typically nested `GroupOperator` wrappers that output via `Output1` (not `MainOutput1`). `ActiveTool` points to an intermediate node the author wants to highlight, not the final output.

```lua
{
    Tools = ordered() {
        Group2 = GroupOperator {
            -- No Inputs block (no MainInput1)
            Outputs = {
                Output1 = InstanceOutput {
                    SourceOp = "Merge3D2",
                    Source   = "Output",
                },
            },
            ViewInfo = GroupInfo {
                Flags = {
                    AllowPan = false,
                    GridSnap = true,
                    AutoSnap = true,
                    RemoveRouters = true,
                },
                -- ...
            },
            Tools = ordered() {
                -- full scene graph demonstrating the technique
                -- inner groups also use Output1, not MainOutput1
            },
        },
    },
    ActiveTool = "BrightnessContrast1",  -- intermediate node, pedagogically interesting
}
```

**Install path:** `Templates/Fusion/How To/`.

**Key details:**

- No `MainInput1` / `MainOutput1`. These files are not filters or sources — they are demonstrations.
- All files in this category share a single `_default.png` / `_default@2x.png` thumbnail pair (no per-file thumbnails).
- Output ports use `Output1`, not `MainOutput1`.
- `ActiveTool` is set to the node the author wants to draw attention to (e.g., a `BrightnessContrast` or `MatteControl` mid-graph), not necessarily the terminal output.
- Multiple `ActiveTool` entries can appear if the file contains nested groups that each declare one — the outermost one wins.

---

## 9. Fusion Lens Flare

**Role:** HotSpot-based lens flare preset. Unlike every other category, the root node is a raw `HotSpot` — not a `GroupOperator`. A single `.setting` file ships as multiple switchable preset variants stored inside `CustomData.AltSettings9`.

**The AltSettings9 preset-bank pattern:** `CustomData.AltSettings9` is a numbered `Settings` block. Each numbered entry is a complete `HotSpot` configuration. `CurrentSettings` on the outer `HotSpot` indicates which preset is currently active (1-based). This is how the Effects Library browser shows multiple "variants" for a single flare file.

```lua
{
    Tools = ordered() {
        Lens_Flare_V01 = HotSpot {
            CtrlWZoom = false,
            NameSet   = true,
            CustomData = {
                AltSettings9 = {
                    -- preset variant 1
                    Tools = ordered() {
                        HotSpot1 = HotSpot {
                            Inputs = {
                                Input = Input {
                                    SourceOp = "Background1",  -- feed a background image here
                                    Source   = "Output",
                                },
                                PrimaryCenter   = Input { Value = { 0.26, 0.62 } },
                                HotSpotSize     = Input { Value = 0.52 },
                                Red   = Input { SourceOp = "HotSpot1Red",   Source = "Value" },
                                Green = Input { SourceOp = "HotSpot1Green", Source = "Value" },
                                Blue  = Input { SourceOp = "HotSpot1Blue",  Source = "Value" },
                                -- BezierSpline nodes drive color over angle
                            },
                        },
                        -- BezierSpline color-curve nodes ...
                    },
                },
                -- AltSettings9[2], [3], ... for additional presets
            },
            -- outer HotSpot mirrors the active preset's inputs:
            Inputs = {
                -- same structure as HotSpot1 above
            },
        },
    },
    ActiveTool = "Lens_Flare_V01",
}
```

**Install path:** `Templates/Fusion/Lens Flares/`.

**Key details:**

- Root node is `HotSpot`, not `GroupOperator`. There is no `MainInput1` or `MainOutput1`.
- Background image feeds via `HotSpot.Input` (not `MainInput1`).
- Preset variants live in `CustomData.AltSettings9` as numbered entries. `CurrentSettings = N` (on the outer `HotSpot`) selects the active preset.
- BezierSpline nodes inside each preset drive color tints over the flare's angular position.
- The outer `HotSpot` (at the `Tools` level) mirrors the currently-active preset's inputs — it is what Resolve renders.

---

## 10. Fusion Motion Graphic

**Role:** standalone animated graphic — title card, lower third, animated element. Ships as raw top-level nodes with no `GroupOperator` wrapper. Users get the full node graph dropped into their comp.

**Hook:** no wrapper. `ActiveTool` must point to the **terminal composite node** (usually a `Merge`) — Resolve uses it to determine what the browser preview renders. Thumbnails follow a distinct convention: `wide.png` / `wide@2x.png` plus `small.active.png`.

```lua
{
    Tools = ordered() {
        Background1 = Background {
            Inputs = {
                Width  = Input { Value = 1920 },
                Height = Input { Value = 1080 },
                UseFrameFormatSettings = Input { Value = 1 },
            },
        },
        TextPlus1 = TextPlus {
            Inputs = {
                StyledText = Input { Value = "SAMPLE" },
                -- animation via BezierSpline inputs ...
            },
        },
        RectangleMask1 = RectangleMask { Inputs = { -- ...
        } },
        Merge10 = Merge {
            Inputs = {
                Background = Input { SourceOp = "Background1", Source = "Output" },
                Foreground = Input { SourceOp = "TextPlus1",   Source = "Output" },
            },
        },
        -- PublishNumber, Shake, BezierSpline nodes also appear at top level
    },
    ActiveTool = "Merge10",
}
```

**Install path:** `Templates/Fusion/Motion Graphics/`.

**Key details:**

- No `GroupOperator` wrapper — the entire node graph is exposed at the top level.
- `ActiveTool` must be the terminal `Merge` (or equivalent composite). Resolve uses this to render the browser thumbnail and insert the comp correctly.
- Can use any Fusion node: `PublishNumber`, `Shake`, `BezierSpline`, `TextPlus`, `Merge`, `Background`, `RectangleMask`, etc. There is no I/O contract.
- Thumbnail files use `wide.png` / `wide@2x.png` + `small.active.png` naming — different from Backgrounds (which use `large.png`).

---

## 11. Fusion Particle

**Role:** particle system preset. Root node is a raw `pEmitter`. Multiple preset variants (e.g., different emitter configurations) are stored inside `CustomData.Settings` on the outer `pEmitter`, with `CurrentSettings = N` selecting the active one.

**Hook:** minimum working pipeline is `pEmitter → pRender → [Merge3D with Camera3D] → Renderer3D`. The `pRender` node is required to convert the particle stream into a renderable image; omitting it results in an invisible output.

```lua
{
    Tools = ordered() {
        pEmitter1 = pEmitter {
            CurrentSettings = 1,
            CustomData = {
                Settings = {
                    [1] = {
                        Tools = ordered() {
                            pEmitter1 = pEmitter {
                                Inputs = {
                                    Number = Input { Value = 100 },
                                    Style  = Input { Value = FuID { "ParticleStyleBitmap" } },
                                    -- ["ParticleStyle.Size"] = Input { Value = 0.08 },
                                    -- region, spin, color-over-life, etc.
                                },
                            },
                        },
                    },
                    -- [2] = { ... } additional presets
                },
            },
            Inputs = {
                -- mirrors active preset inputs
            },
        },
        pRender1 = pRender {
            Inputs = {
                SceneInput = Input { SourceOp = "pEmitter1", Source = "Output" },
                Width  = Input { Value = 1920 },
                Height = Input { Value = 1080 },
            },
        },
        Camera3D1   = Camera3D   { },
        Merge3D1    = Merge3D    {
            Inputs = {
                SceneInput1 = Input { SourceOp = "pRender1",  Source = "Output" },
                SceneInput2 = Input { SourceOp = "Camera3D1", Source = "Output" },
            },
        },
        Renderer3D1 = Renderer3D {
            Inputs = { SceneInput = Input { SourceOp = "Merge3D1", Source = "Output" } },
        },
    },
    ActiveTool = "Renderer3D1",
}
```

**Install path:** `Templates/Fusion/Particles/`.

**Key details:**

- Root node is `pEmitter`, not `GroupOperator`.
- `pRender` is mandatory — it converts the particle stream to an image that `Renderer3D` can process. Without it the output is invisible.
- Preset variants live in `CustomData.Settings` (numbered from 1). `CurrentSettings = N` selects the active one. This is the same preset-bank pattern as Lens Flares, but uses `Settings` instead of `AltSettings9`.
- `ActiveTool` points to `Renderer3D` (the terminal rendered output), not the `pEmitter`.

---

## 12. Fusion Shader

**Role:** 3D material (shader) preset. Designed to be plugged into a `Shape3D.MaterialInput` or used standalone with its own preview geometry. Root node is a `GroupOperator`.

**Hook:** `GroupOperator` with no `MainInput`. Output is `Output1` (not `MainOutput1`). The output can carry either (a) a rendered image (`Source = "Output"` from a `Renderer3D` inside the group — for standalone preview) or (b) a raw material (`Source = "MaterialOutput"` from a material node — for direct plug-in to another Shape3D). The `Anisotropic.setting` uses option (a): it wraps its own `Shape3D + Renderer3D` so the shader can be previewed directly. The `GroupInfo.Flags` block (`AllowPan`, `GridSnap`, etc.) is present in Shader group operators and typically absent in Edit effects.

```lua
{
    Tools = ordered() {
        MyShader = GroupOperator {
            CtrlWZoom = false,
            NameSet   = true,
            Inputs = ordered() {
                Comments = Input { Value = "Apply to any shape; requires lights." },
            },
            Outputs = {
                Output1 = InstanceOutput {
                    SourceOp = "Renderer3D1",   -- option (a): rendered preview
                    Source   = "Output",
                    -- OR, for a raw material output:
                    -- SourceOp = "MtlBlinn1",
                    -- Source   = "MaterialOutput",
                },
            },
            ViewInfo = GroupInfo {
                Flags = {
                    AllowPan = false,
                    GridSnap = true,
                    AutoSnap = true,
                    RemoveRouters = true,
                },
                -- ...
            },
            Tools = ordered() {
                MtlBlinn1   = MtlBlinn   { Inputs = { -- material properties
                } },
                BumpMap1    = BumpMap    { Inputs = { Input = Input { SourceOp = "...", Source = "Output" } } },
                Shape3D1    = Shape3D    { Inputs = { MaterialInput = Input { SourceOp = "MtlBlinn1", Source = "MaterialOutput" } } },
                Merge3D1    = Merge3D    { Inputs = { SceneInput1 = Input { SourceOp = "Shape3D1", Source = "Output" } } },
                Renderer3D1 = Renderer3D { Inputs = { SceneInput = Input { SourceOp = "Merge3D1", Source = "Output" } } },
            },
        },
    },
    ActiveTool = "MyShader",
}
```

**Install path:** `Templates/Fusion/Shaders/`.

**Key details:**

- Output field is `Output1`, not `MainOutput1`.
- Two output modes: rendered image (`Source = "Output"` from `Renderer3D`) or raw material (`Source = "MaterialOutput"` from a material node). Choose based on how the user will consume it: standalone preview vs. plug-in to another Shape3D.
- `GroupInfo.Flags` block with `AllowPan`, `GridSnap`, `AutoSnap`, `RemoveRouters` is characteristic of Shader groups — it controls the group's internal canvas behavior.
- No `MainInput` — shaders do not accept upstream images.

---

## 13. Fusion Styled Text

**Role:** per-character animated text preset. Unlike Edit Titles (which use `KeyStretcher`), Styled Text presets are raw node trees with no `GroupOperator` wrapper. They are defined by two nodes that do not appear in any other category: `StyledTextFollower` and `PublishNumber`.

**Hook:** no wrapper. `ActiveTool` points to the primary `TextPlus` node (e.g., `"Text1_2"`), not the terminal `Merge`. `PublishNumber` nodes share scalar or color values across multiple `TextPlus` nodes. `StyledTextFollower` drives per-character follower animations.

```lua
{
    Tools = ordered() {
        Background6 = Background {
            Inputs = {
                Width  = Input { Value = 1920 },
                Height = Input { Value = 1080 },
                UseFrameFormatSettings = Input { Value = 1 },
            },
        },
        Publish1_2 = PublishNumber { Inputs = { Value = Input { Value = 0.8 } } },
        Publish2_2 = PublishNumber { Inputs = { Value = Input { Value = 0.2 } } },
        Follower1_2 = StyledTextFollower {
            Inputs = {
                -- per-character timing / offset controls
            },
        },
        Text1_2 = TextPlus {
            Inputs = {
                StyledText = Input { Value = "SAMPLE" },
                Red1   = Input { SourceOp = "Publish1_2", Source = "Value" },
                Green1 = Input { SourceOp = "Publish2_2", Source = "Value" },
                -- animation splines, TV / SoftGlow effects piped in ...
            },
        },
        TV1_2     = TV     { Inputs = { Input = Input { SourceOp = "Text1_2", Source = "Output" } } },
        SoftGlow1 = SoftGlow { Inputs = { Input = Input { SourceOp = "TV1_2",  Source = "Output" } } },
        Merge12   = Merge  {
            Inputs = {
                Background = Input { SourceOp = "Background6", Source = "Output" },
                Foreground = Input { SourceOp = "SoftGlow1",   Source = "Output" },
            },
        },
    },
    ActiveTool = "Text1_2",
}
```

**Install path:** `Templates/Fusion/Styled Text/`.

**Key details:**

- No `GroupOperator` — the full node tree is raw at the top level.
- `StyledTextFollower` and `PublishNumber` are the defining nodes. An author who omits them produces something that looks nothing like the stock library.
- `ActiveTool` points to the primary `TextPlus` (e.g., `"Text1_2"`), not the terminal `Merge` — this is the opposite convention from Motion Graphics.
- `PublishNumber` nodes share values (color channels, scalar parameters) across multiple `TextPlus` nodes so a single "Color" slider controls all text elements at once.
- `BezierSpline` inputs on `TextPlus` (alpha, size, tracking) provide the per-character animation timing.

---

## Role → Shape Cheat Sheet

| Role | Wrap in GroupOperator? | MainInput1 | MainInput2 | MainOutput1 source | Output field |
|------|-----------------------|------------|------------|---------------------|-------------|
| Edit Effect | Yes | Required → `Input` of first node | — | Terminal node | `Output` |
| Edit Transition | Yes | Required → `Background` | Required → `Foreground` | Dissolve/Merge | `Output` |
| Edit Title | Yes | — | — | KeyStretcher | `Result` |
| Edit Generator | Yes | — | — | Terminal node | `Output` |
| Fusion Tool | Yes | Required → `Input` of first node | Optional | Terminal node | `Output` |
| Fusion Background | Yes (wrapped) or No (unwrapped) | — | — | `Renderer3D` | `MainOutput1` or `Output1`; unwrapped: `ActiveTool` on `Renderer3D` |
| Fusion Generator | Yes | Material → `Shape3D.MaterialInput` | Material → `Shape3D.MaterialInput` | `Renderer3D` | `MainOutput1` |
| Fusion How To | Yes (nested groups) | — | — | Intermediate node of interest | `Output1` |
| Fusion Lens Flare | No — raw `HotSpot` at top | — | — | — | `HotSpot.Input` for background; no `MainOutput1` |
| Fusion Motion Graphic | No — raw top-level nodes | — | — | Terminal `Merge` | `ActiveTool` on `Merge` |
| Fusion Particle | No — raw `pEmitter` at top | — | — | `Renderer3D` | `ActiveTool` on `Renderer3D` |
| Fusion Shader | Yes | — | — | `Renderer3D` (preview) or material node | `Output1` |
| Fusion Styled Text | No — raw top-level nodes | — | — | Primary `TextPlus` | `ActiveTool` on `TextPlus` |
