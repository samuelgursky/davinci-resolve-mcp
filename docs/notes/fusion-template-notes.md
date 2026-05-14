# DaVinci Resolve Fusion Template Notes

Blackmagic's Fusion Templates README documents `.setting` templates used by the
Edit and Cut page Effects Library. This is relevant to the MCP because several
timeline actions insert named Fusion generators and titles, and failures often
come down to template location, category, naming, or Resolve needing a restart.

## Current MCP Surface

The scripting API overlap is useful but narrow:

- `timeline(action="insert_fusion_generator", params={"name": "..."})` wraps
  `Timeline.InsertFusionGeneratorIntoTimeline(generatorName)`.
- `timeline(action="insert_fusion_title", params={"name": "..."})` wraps
  `Timeline.InsertFusionTitleIntoTimeline(titleName)`.
- `timeline(action="insert_fusion_composition")` inserts an empty Fusion
  composition into the current timeline.
- `timeline_item_fusion` manages Fusion comps already attached to timeline
  items, including import/export of Fusion compositions.
- `fusion_comp` edits the node graph of the active Fusion comp or a scoped
  timeline-item comp.

Fusion template `.setting` files are not the same thing as exported Fusion comp
files used by `timeline_item_fusion.import_comp`. Treat template installation
and Fusion-comp import as different workflows.

## Template Categories

Fusion templates are macro or group `.setting` files saved into category folders:

| Category | Shape |
|---|---|
| Transitions | Two image inputs and one output. |
| Generators | No image inputs and one output. |
| Titles | Generator-style templates centered on Text+ or Text3D. |
| Effects | One image input and one output, applied to clips from the Effects tab. |

The MCP currently has direct timeline insertion helpers for Fusion generators
and Fusion titles. The Resolve scripting API does not expose a general
"install Fusion template" or "list Fusion templates" method.

## Template Paths

Fusion templates live under `Fusion/Templates/` in platform-specific roots:

| Platform | All users | Specific user |
|---|---|---|
| macOS | `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Templates/` | `/Users/<UserName>/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Templates/` |
| Windows | `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Fusion\Templates\` | `C:\Users\<UserName>\AppData\Roaming\Blackmagic Design\DaVinci Resolve\Support\Fusion\Templates\` |
| Linux | `/var/BlackmagicDesign/DaVinci Resolve/Fusion/Templates/` or `/home/resolve/Fusion/Templates/` | `$HOME/.local/share/DaVinciResolve/Fusion/Templates/` |

Only templates under this Edit-page hierarchy show up on the Cut and Edit pages:

```text
Edit/
  Transitions/
  Titles/
  Generators/
  Effects/
```

Templates saved elsewhere may still be visible from the Fusion page Effects
Library but not from the Edit/Cut page categories used by timeline insertion.

## Animation Guidance

Fusion template animation should generally use the Anim Curves modifier instead
of fixed-time keyframes. Edit/Cut page template duration is driven by the edit
length or transition curve, so fixed-time keyframes will not adapt cleanly when
an editor changes duration.

Anim Curves timing sources:

- `Duration` times animation to the edit duration.
- `Transition` follows duration and also uses the Edit page transition curve.
- `Custom` reveals an input that can be driven manually by another spline or
  modifier.

Anim Curves supports linear, easing, and custom curves, plus mirror, invert,
scale, offset, clipping, time scale, and time offset controls.

## Assets, Icons, And DRFX Bundles

Since Resolve 17.2, Fusion templates can include bundled assets such as images,
FBX models/cameras, and LUTs. Inside templates, the `Setting:` path map points
to the directory containing the loaded `.setting` file. Examples:

```text
Setting:leaf.jpg
Setting:Models/object.fbx
```

Resolve also supports a `.png` icon next to a `.setting` file when both share
the same base name. Blackmagic recommends `104 x 58`; very large icons may slow
Resolve startup.

`.drfx` bundles are ordinary zip files renamed with a lower-case `.drfx`
extension. They can contain multiple templates, icons, and assets. For Edit/Cut
recognition, keep the same `Edit/Titles`, `Edit/Generators`,
`Edit/Transitions`, and `Edit/Effects` folder hierarchy inside the bundle.

## Practical Failure Checks

If `insert_fusion_generator` or `insert_fusion_title` fails:

- Confirm the template is in the matching `Edit/Generators` or `Edit/Titles`
  folder.
- Restart Resolve after adding template files.
- Confirm the display/template name matches the string passed to the API.
- Check whether the template category is wrong; transitions and effects are not
  inserted by the generator/title helpers.
- Check any `Setting:` assets are present beside the `.setting` file or in the
  expected subfolder.
- For animated templates, inspect whether fixed keyframes were used where Anim
  Curves were needed.

## Useful Future Additions

Good repo additions, if Fusion template workflows become common:

1. A read-only Fusion template inventory helper that scans known template roots
   and reports `.setting` files by category.
2. Better failure text for `insert_fusion_generator` and `insert_fusion_title`
   that points users to category folders, restart requirements, and name checks.
3. A small example that installs a user-local generator/title template and then
   inserts it with the existing timeline actions. Keep system-wide install
   paths explicit because they may require administrator privileges.
4. A DRFX inspection helper that verifies lower-case `.drfx`, zip structure,
   category folders, icons, and referenced `Setting:` assets.

## Source Media Integrity

Fusion templates and bundled assets affect Resolve's timeline/render pipeline.
They should not modify camera originals. Do not bake template effects into
source media, create rendered derivatives, or export/reimport processed media
unless the user explicitly asks for that workflow.
