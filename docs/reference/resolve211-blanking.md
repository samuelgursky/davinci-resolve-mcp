# Resolve 21.1 output blanking

The native setters are exposed in both interfaces:

| Compound tool/action | Granular tool |
|---|---|
| timeline set_output_blanking | set_timeline_output_blanking |
| timeline_item set_output_blanking | set_timeline_item_output_blanking |
| timeline_item set_use_timeline_for_output_blanking | set_timeline_item_use_timeline_for_output_blanking |

Blanking setters take `options` containing one or more Top/Bottom/Left/Right
pixel coordinates. These are bounds, not four independent margin widths. For a
640x360 frame, full picture is Top0/Bottom360/Left0/Right640. Whole-valued floats
from native getter results are accepted; fractional/non-finite values, booleans,
unknown keys and empty dictionaries are refused. No undocumented geometry bounds
are invented, and partial dictionaries are forwarded unchanged to Resolve.

The inheritance setter requires a strict `use_timeline` boolean. To set a clip
override, disable inheritance explicitly first. On the measured build, setting
clip blanking while inheritance was enabled returned false and changed nothing.
The wrapper preserves that failure and never silently changes inheritance.
Re-enabling inheritance returns the clip to the timeline's blanking. Native
getter payloads may be empty when the clip inherits timeline blanking.

All three actions have 21.1 method floors, registered destructive MEDIUM-risk
writes in both classifier tables, and destructive granular annotations. Explicit
compound dry-run requests are refused before writes. Native failure is preserved
as success:false. Clip locators use the existing 1-based tracks/0-based item
indexes.

## Contributor validation

Contributor-validated on macOS Studio 21.1.0.14 using a generated solid red clip
in a disposable 640x360 project, through both actual community interfaces.
Resolve-exported PNGs showed exact lit-pixel bounds:

- Full picture: left0/top0/right640/bottom360.
- Timeline blanking: left64/top36/right576/bottom324.
- Clip override: left128/top72/right512/bottom288.
- Inheritance restored: timeline bounds64/36/576/324 again.

The override frame was visually inspected; both interfaces returned the same
bounds. Inherited clip-set refusal was also verified live. This is sampled-frame
and readback evidence, not whole-movie verification, or proof of
negative-coordinate, out-of-frame or audio-item behavior. A native-only partial
update with Top80.0 also succeeded and preserved Bottom/Left/Right in readback;
that extra case was not image-verified. Those cases are not
claimed tested.

`tests/live_resolve211_blanking.py OUTPUT_DIR` requires the disposable project
Codex Blanking Validation 20260909 with one synthetic red.mov video clip, at
640x360/24 fps with timeline start00:00:00:00. Generate red.mov using the color
fixture in resolve211-native-transitions.md. The script invokes both wrappers,
exports comparison PNGs and restores full timeline blanking/inheritance before
saving the scratch project. Never substitute production media.
