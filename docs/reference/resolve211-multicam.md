# Native Resolve 21.1 multicam creation and flattening

Compound `media_pool create_multicam_clip` accepts `clip_ids` (media-pool unique
IDs) and optional `options`. Granular `create_multicam_clip` takes the same
arguments. Every ID must resolve before the native call; missing/duplicate IDs
are errors, never silently dropped angles. Success returns the IDs and names of
all returned multicam clips. An empty native result is success:false. This does
not replace the existing stacked-timeline preparation workflow on older Resolve.

All eleven MulticamOptions fields are supported: name, startTimecode, frameRate,
angleSyncMode, channelConfig, multicamAudioMode, angleNameMode, splitAtGaps,
useFullClipExtents, createBinForSourceClips and detectSameCameraClipsMode.
Documented Resolve constant names (for example MULTICAM_ANGLE_SYNC_TIMECODE) are
resolved against the live Resolve object. Integral native numeric constant values
are also accepted; the wrapper does not invent their numbering. Unknown option
keys, invalid named constants, malformed booleans and non-positive/non-finite
frame rates are refused. Omitted options stay omitted. Resolve controls native
defaults, including createBinForSourceClips=true, which can reorganize source
clips in the media pool. No source files are modified by this wrapper.

Compound `timeline_item flatten_multicam` and granular
`flatten_timeline_item_multicam` use the normal 1-based track/0-based item
locators and optional `grade_option`, default FLATTEN_MULTICAM_COPY_GRADE.
FLATTEN_MULTICAM_RETAIN_GRADE_FROM_ANGLE is also accepted. This replaces the
multicam item with its active angle, so re-query the timeline afterward. Native
false stays success:false. Both methods require 21.1 and callable APIs; both
compound actions are registered as destructive MEDIUM-risk writes in the two
risk tables. Granular annotations also declare destructive writes. Explicit
compound dry-run requests are refused before mutation.

## Contributor validation

Contributor-validated on macOS Studio 21.1.0.14 using generated red/blue media in
a disposable 640x360/24 fps project. Both interfaces created a native Multicam
media-pool item, appended it to a timeline, rendered it, flattened with COPY_GRADE,
and rendered again. All four complete decoded RGB movies were identical, each
144 frames. Flattened media type changed from Multicam to Video; start0 and
144-frame duration were preserved. This proves preservation of the native-selected angle video in
an ungraded fixture. It does not prove second-angle switching, grade-copy versus
retained-grade differences, audio routing, audio synchronization, gap splitting
or camera-detection behavior. These options are documented pass-through, not
claimed live verified.

`tests/live_resolve211_multicam.py OUTPUT_DIR` requires the named disposable
project Codex Multicam Validation 20260909 with synthetic red.mov and blue.mov
six-second clips. It creates timelines and render jobs and saves that project.
Use the synthetic FFmpeg fixture commands in resolve211-native-transitions.md;
never run the fixture against production media. Compare complete decoded frames
from compound-before/compound-flattened/granular-before/granular-flattened.mov.

Smart Switch and AutoAlignClips remain separate work. Native timecode alignment
has positive position-readback evidence, but rendered/waveform acceptance remains
open. Silent color-card Smart Switch returned false and is not a meaningful
positive speaking-camera test. This contribution does not claim the entire
multicam family completed.

Do not infer angle order from clip_ids order. The wrapper forwards the requested
source order, but this measurement establishes the selected angle and its
preservation, not a contract for Resolve's default angle selection.
