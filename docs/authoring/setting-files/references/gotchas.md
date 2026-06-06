# Gotchas

Hard-won rules that are not obvious from the stock files. Check against this list whenever an effect "loads but doesn't work."

## 1. `ordered()` vs `{}` — Order Actually Matters

`Inputs = ordered() { ... }` preserves the order you wrote. `Inputs = { ... }` does **not** — Fusion may re-order, which scrambles your inspector layout, breaks `ControlGroup` pairings (consecutive grouping stops working), and shuffles your Page tabs. Always use `ordered()` for:

- `GroupOperator.Inputs`
- `GroupOperator.Tools` (order determines evaluation order for some purposes)
- `UserControls`

The internal `Inputs = { ... }` of individual nodes can be unordered — node params are keyed by name.

## 2. `ActiveTool` Must Match a Top-Level Key

`ActiveTool = "MyEffect"` has to name an entry in the outermost `Tools` list. If you rename the GroupOperator without updating `ActiveTool`, the file loads but Resolve doesn't know which node is the "primary" — some categories (titles especially) misbehave.

If there's exactly one top-level node, `ActiveTool` is effectively optional — but set it anyway for clarity.

## 3. `SourceOp` References Must Resolve

Every `SourceOp = "Name"` has to name a node in the *same* `Tools` list. A reference from an `InstanceInput` points into the GroupOperator's internal `Tools`. A reference from inside one internal node's `Input` points to a sibling in that same internal `Tools`. You cannot reach across groups.

Typos here cause silent failures: the effect loads, the control exists, but it doesn't affect anything. When debugging, grep for all `SourceOp = "..."` values and verify each one is defined.

## 4. `Source` Names Are Case-Sensitive and Exact

`XBlurSize` is not the same as `xBlurSize` or `XBlursize`. When you're not sure of the exact parameter name, build the effect in Fusion, save it, and open the `.setting` file — it will contain the authoritative names.

## 5. Transition Progress is Automatic — Don't Look for a "Progress" Parameter

There is no `Progress` or `Time` parameter on the transition GroupOperator. Fusion evaluates internal `LUTLookup` nodes with `Source = FuID { "Duration" }` across the clip duration and produces a 0→1 ramp for free. Use that ramp to drive any animated parameter.

If your transition "plays" in one frame or doesn't animate at all, you probably fed a static value into `Dissolve.Mix` instead of a `LUTLookup`.

## 6. Titles Need `KeyStretcher` or They Don't Stretch

A TextPlus with baked-in `BezierSpline` animation has a fixed length in frames (e.g., the animation runs from frame 1 to frame 120). If you expose its `Output` directly as `MainOutput1`, the title shows its animation in the first 120 frames regardless of clip length — a 5-second title clip will play the animation for the first 4 seconds and freeze for the last 1 second.

Fix: wrap the output in a `KeyStretcher` and output `Source = "Result"`. Set `SourceEnd` to the animation's native length and `StretchStart` / `StretchEnd` to the range you want stretched.

## 7. `MainOutput1.Source` for Titles is `"Result"`, Not `"Output"`

Easy to miss. If your title renders but the animation doesn't stretch properly, check whether you pulled `Output` (unstretched) or `Result` (stretched) from the `KeyStretcher`.

## 8. `Width`, `Height`, `UseFrameFormatSettings` on Generator Nodes

Nodes that generate pixels (`Background`, `FastNoise`, `TextPlus`, `RectangleMask`, `EllipseMask`) have a `Width` / `Height` pair that defines the canvas size. For Edit-page use, always set `UseFrameFormatSettings = Input { Value = 1 }` so the node inherits the timeline's resolution instead of being locked to 1920×1080. Stock effects all do this; skipping it makes your effect break on 4K timelines.

## 9. Namespaced Parameter Keys Need Quoting

Any parameter with a `.` in its name must be wrapped in brackets and quoted:

```lua
-- wrong
Gamut.SLogVersion = Input { Value = FuID { "SLog2" } },

-- right
["Gamut.SLogVersion"] = Input { Value = FuID { "SLog2" } },
```

This bites hardest on 3D nodes (`Transform3DOp.Translate.X`, `Diffuse.Color.Red`, `SurfaceCylinderInputs.Radius`) and ofx nodes.

## 10. `FuID` Enum Values Must Be Exact

`FuID { "Fast Gaussian" }` is one of several possible enum values for `Blur.Filter`. If you guess the wrong name, the file loads but the parameter falls back to the default and silently ignores you. Don't guess — inspect a working composition or grep the stock files for the node type you're using to find valid values.

## 11. Don't Reuse Internal Node Names Across Groups

Each `GroupOperator` has its own namespace for internal `Tools`. Within a single group, names must be unique. If you want two `Blur` nodes, call them `Blur1` and `Blur2`. Fusion appends `_1`, `_2` when you create duplicates in the UI; in hand-authored files, just number them yourself.

Name collisions produce "last one wins" behavior: only the last definition is honored, and any `SourceOp` references resolve to that last one.

## 12. `Instance_NodeName` is a Magic Pattern

When stock effects need the same internal node available at two points in the graph with slightly different routing, they use the `Instance_` prefix:

```lua
Rectangle1 = RectangleMask { ... actual params ... },

Instance_Rectangle1 = RectangleMask {
    SourceOp = "Rectangle1",   -- creates an instance that shares Rectangle1's params
    Inputs   = { ... different routing ... },
},
```

An `Instance_X` with `SourceOp = "X"` at the node level (not inside an `Input`) creates a live clone. Edits to `Rectangle1` propagate to `Instance_Rectangle1`. Use this when you need the same mask / text / curve to appear in two places in the graph.

## 13. `CustomData` is Optional — Strip It

Stock effects carry large `CustomData.Settings` blocks because Fusion saves the full UI state of preset variations into them. You can delete the entire `CustomData = {...}` block from any node you're hand-editing; the effect will still load and work. The blocks just bloat the file and obscure the real logic.

## 14. Restart Resolve Picks Up New Templates

Resolve indexes the Templates folder at launch. Dropping a new `.setting` file in while Resolve is running will NOT make it appear in the Effects Library until you quit and relaunch. (Refreshing via right-click in the library works sometimes, not reliably.)

## 15. A Broken `.setting` Crashes the Category, Not Resolve

If you ship malformed Lua, Resolve skips the file and logs a warning. But a subtler problem — a file that parses but has a dangling `SourceOp` reference or a wrong `Source` name — can make an entire subfolder look empty in the Effects Library. When nothing shows up, move your new file out of the folder temporarily and check whether the rest of the category reappears.

## 16. `Dissolve.Map` is the Wipe Shape

For luma-ramp transitions (`Operation = FuID { "DFTLumaRamp" }`), `Dissolve.Map` takes an image input that defines the shape of the wipe. Bright areas reveal the foreground first, dark areas last. Generate the map with any node: `Background` with a gradient for a linear wipe, `FastNoise` for a dissolve, `RectangleMask` + `Transform` for a box wipe, etc.

## 17. `Fuse.Wireless` is a Carrier, Not a Real Node

`Fuse.Wireless` exists to host `UserControls` entries (buttons, labels, etc.) that don't belong to any real node. It has no pixel output. Don't try to use it in the render graph. Think of it as a "control panel node."

## 18. Files Loose in `Templates/Edit/` Silently Fall Through to the Fusion Library

The Edit-page Effects Library only indexes `.setting` files that live inside a **category subfolder**: `Templates/Edit/Effects/`, `Templates/Edit/Transitions/`, `Templates/Edit/Titles/`, `Templates/Edit/Generators/`. A file dumped directly into `Templates/Edit/` (no category subfolder) is invisible to the Edit page — but the Fusion-page library is laxer and picks it up anyway, so the effect *appears to install successfully*, just in the wrong UI.

Symptom: "I wrote an Edit effect, restarted Resolve, and it's showing up under the Fusion page's Effects Library instead of on the Edit page." Cause: you skipped the `<category>` folder. Always write to the full path including the subfolder:

```
%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Templates\Edit\Effects\MyBlur.setting
```

not

```
%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Templates\Edit\MyBlur.setting
```

Same rule for Fusion macros: they need a category subfolder too (`Fusion/Tools/`, `Fusion/Backgrounds/`, etc.), not loose in `Fusion/`.

## 19. `.alut3` Files Are LUTs, Not Compositions

`Fusion/Looks/*.alut3` live in the same `Core Davinci Effects` folder structure but they're **plain-text 3D LUTs**, not `.setting` files. Header: `F5LT3\nSize: 33\nType: float32\n\n` followed by R G B triples. They install to the LUT folder and apply from the Color page. Do not try to edit them as Fusion comps.

## 20. `ControlGroup = N` Must Equal the Anchor Input's Number

Fusion collapses controls into one inspector row when they share a `ControlGroup` integer. That integer must equal the `InputN` number of the preceding label/anchor Input in the list — not a free-choice group ID. In `CCTV.setting`, `Font` (Input2) and `Style` (Input3) both carry `ControlGroup = 2` because they share a row anchored to `Input2`. In `Background Reveal Lower Third.setting`, `VerticalJustificationTop`, `VerticalJustificationCenter`, and `VerticalJustificationBottom` (Input7/8/9) all carry `ControlGroup = 6`, grouping them under the `Input6` row anchor. If you pick sequential integers starting from 1, grouping silently breaks: controls render on separate rows and multi-button radios disappear.

Rule: count from the top of your `Inputs = ordered() { ... }` block and use the anchor row's `InputN` number as the group ID for all siblings that share that row.

## 21. `Width` on `InstanceInput` Is Inspector Column Width, Not Mask Size

`Width` means two completely different things depending on context. On mask nodes (`EllipseMask`, `RectangleMask`) it is the physical mask size as a fraction of image width — e.g., `Ellipse1.Width = 0.5069` in `Binoculars.setting` is the mask diameter, not a UI hint. On an `InstanceInput`, `Width` is a fractional inspector column width (0.0–1.0): `DSLR.setting` exposes five timecode fields each with `Width = 0.5`, packing them two-per-row in the inspector. `Width = 1` (the default when omitted) gives the control its own full row.

A related field, `ICD_Width`, serves the same purpose inside `UserControls` button definitions. Authors packing button grids who accidentally copy a mask-scale value like `0.5069` produce weirdly-wide or full-row controls.

## 22. `GlobalOut` on Internal Generator Nodes — Set It, Keep It Consistent

`GlobalOut` on a generator or text node caps its internal frame timeline. Every `TextPlus`, `Background`, and `FastNoise` inside an effect with baked animation must carry `GlobalOut = Input { Value = N }`, and all nodes in the same group must share the same `N`. In `CCTV.setting`, every generator node carries `GlobalOut = 716`. If you omit `GlobalOut`, the node's internal timeline is unbounded and Resolve may render garbage or refuse to stretch the effect to clip length. If siblings in the same group have different `GlobalOut` values, animation phases drift out of sync.

## 23. Fusion Bare-Node Comps Don't Work as Edit Effects — Edit Requires `GroupOperator`

All `Edit/Effects/`, `Edit/Transitions/`, `Edit/Titles/`, and `Edit/Generators/` stock files wrap their graph in a `GroupOperator` with `InstanceInput`s. Several Fusion categories — especially `Fusion/Styled Text/` — ship raw top-level node trees with no `GroupOperator` and no exposed `InstanceInput`s at all. In those cases, users customize by opening the node graph on the Fusion page. On the Edit page this model fails silently: the effect loads, appears in the Effects Library, but has a blank inspector.

If you copy `Fusion/Styled Text/Alien.setting` (bare nodes, no GroupOperator) as a starting point for a new Edit effect, you get an unusable empty-inspector result. Always wrap Edit-page effects in a `GroupOperator`. `Edit/Effects/Binoculars.setting` is a clean example of the required structure.

## 24. Transition Easing Uses `LUTLookup` + `LUTBezier`, Not `BezierSpline`

For parameters that need to follow transition progress (0→1 over clip duration), the stock pattern is a `LUTLookup` node with its `Lookup` input connected to a sibling `LUTBezier`. `LUTBezier` uses `KeyColorSplines` with an outer `[0]` (single channel index) and inner float keys 0.0–1.0 (normalized position). This is completely different from `BezierSpline`, which uses `KeyFrames` with absolute frame numbers. Hand-authored effects that drive transition progress via a `BezierSpline` with frame keys play at wrong timing or freeze.

A bare `LUTLookup {}` with no `Lookup` input (as in `Cross Dissolve.setting`) automatically consumes the built-in `Duration` source for a default linear 0→1 ramp — leaving `Lookup` disconnected is valid shorthand for "linear progress." `Box Wipe.setting` shows the full explicit form with a custom `LUTBezier` easing curve.

## 25. `BTNCS_Execute` Lua References `InputN` Keys, Not Internal Node Parameter Names

`Fuse.Wireless` buttons use `BTNCS_Execute` to call `tool:SetInput(...)`. The first argument must be the exposed `InstanceInput` key name (e.g., `'Input9'`), not the underlying node's parameter name (e.g., `'Start'`). In `Box Wipe.setting`, direction-preset buttons call `tool:SetInput('Input9', {x,y})` to write the wipe start position — `Input9` is the `InstanceInput` key that wraps `Background2.Start`. Writing `tool:SetInput('Start', ...)` silently does nothing because `Start` isn't a top-level `GroupOperator` input. Authors naturally reach for the internal param name since that's what they see in the node graph.

## 26. OFX Nodes Require a Mandatory Boilerplate Input Block

Every `ofx.com.blackmagicdesign.resolvefx.*` node in the stock files carries seven required OFX overlay parameters: `blendGroup`, `blendIn`, `blend`, `ignoreContentShape`, `legacyIsProcessRGBOnly`, `refreshTrigger`, and `resolvefxVersion`. Both `Binoculars.setting` and `Digital Glitch.setting` include this block on every OFX node. Omitting any one of these causes the node to fall back to defaults that may differ from your intent, or the effect fails to load entirely. `resolvefxVersion` should match the version the effect was authored against (e.g., `"2.2"`); mismatches can cause parameter layout changes in newer Resolve versions.

Authors hand-writing OFX invocations rather than copying from a stock file invariably omit this block. Copy the seven-field block verbatim from any working stock OFX node.
