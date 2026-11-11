# Resolve / Live film workflow

These helpers join existing film cue export, stem delivery and conform inspection.
They do not compose music, automatically reconform a score, change source media,
or establish that unobserved audio hardware settings are correct.

## Capture the picture baseline

Call `timeline(action="film_snapshot")`. Retain the returned `cue_sheet`,
`snapshot` and `picture_fingerprint` with the picture version being scored.
The snapshot is read-only. Its fingerprint covers exposed video structure and
cues, not rendered frames, grades, effects or the contents of source files.
Audio-track changes do not invalidate this picture baseline.

`timeline_markers(action="compare_cue_sheets", params={"before": old_sheet,
"after": new_sheet})` reports cue additions, removals, timing and metadata changes.
See [picture-change reports](film-picture-changes.md) for stable identity rules.
Resolve's exported `marker:<frame>` IDs are positional, not persistent identities.
Do not treat a name match or nearby marker as proof that a cue moved.

For picture-edit impact, also supply `before_snapshot` and `after_snapshot` from
the two `film_snapshot` results. The action reuses the existing conform comparison
and reports cues overlapping changed video spans in either version. This is a
conservative track/array-position comparison, not inferred clip correspondence;
insertions may flag later spans too. Unknown source/timeline coordinates remain
explicitly unknown. No grade/effect or media-content equivalence is claimed.
Without snapshots, picture-edit impact is unknown even if every marker matches.

## Read the saved score tempo

On the Ableton MCP call `film_tempo_read(source_set_path="absolute/file.als")`.
The receipt contains `tempo_map_beats` for region bouncing and `tempo_map_seconds`
for `film_cues_plan`. Maps start at arrangement zero; a different picture origin
requires an explicit rebase. Ramps, modulation and unknown tempo topology refuse.
The receipt binds the source file hash; it excludes unsaved Live changes.

## Calibrate before trusting captured origins

Ableton provides `generate_calibration_probe`, `measure_capture_calibration` and
`validate_capture_calibration`. The first creates a new probe WAV; measurement
needs two to five independent captures through the exact intended audio path.
Validation remeasures the bound files against the current declared configuration.
See Ableton's `docs/FILM_CALIBRATION.md` for settings and the disposable-set procedure.
No tool applies compensation or changes a production score automatically.

The offset is relative to the probe, not an absolute picture-origin measurement.
Driver/buffer/routing/plugin settings and capture provenance are caller assertions.
Do not subtract a measured offset twice if the recorder already compensates it.

## Prepare and return stems

Use Ableton's `film_stems_prepare` and `film_stems_audit` to produce a new
`film-stems/v1` package. Each capture needs a known signed `source_start_sample`.
Keep the delivered directory in a stable location: Resolve references its WAVs;
the importer does not copy them or collect project media.

Preview on Resolve:

```json
{
  "action": "film_stems_return",
  "params": {
    "delivery_dir": "D:/exports/ch5/music-v2",
    "preview": true
  }
}
```

Pass this to `timeline`. On approval, call the same action with `preview:false`,
`expected_timeline_id` from the preview's `timeline_id`, and
`expected_fingerprint` from its `fingerprint`. A stale preview refuses.

The importer independently checks PCM24 WAV headers, sample counts, hashes and
the target timeline rate. New tracks are named `FILM_<package-hash>_<stem-name>`.
Placement adds the timeline's absolute start exactly once. Source-frame lengths
use the imported media item's FPS, which need not equal the timeline FPS.
On the verified Resolve 21.0.4.5 build, audio append end frames are exclusive.
Every append is checked against actual timeline items, not just the API receipt.
Timing readback tolerance is one audio sample expressed in timeline frames.

Complete matching imports report `already_present`; wrong placement, duplicate
instances, name collisions or partial prior imports require manual review.
An interrupted/failed write reports `partial_failure` with created tracks and
readable media receipts. `partially_created_unknown` means the API may have
created additional media without usable receipts. Nothing is automatically deleted
and no rollback is promised. Existing tracks and clips are never replaced.

The preview is rated a low-risk read and archives nothing. The apply call is
rated medium risk on the timeline. Like other timeline edits, it first archives
a copy of the timeline to the Archive bin (once per run); the imported stems
still land in the bin that was current before the call.
Existing stems are matched by their resolved path, so a delivery folder reached
through a symlink (such as `/tmp` or `/var` on macOS) is still recognised.

## Preflight the handoff

Call `timeline(action="film_preflight", params={...})`. Optional evidence:

| Parameter | Meaning |
|---|---|
| `expected_picture_fingerprint` | Baseline from `film_snapshot` or prior preflight |
| `delivery_dir` | Existing film-stems/v1 directory |
| `tempo_evidence` | Full `film_tempo_read` receipt |
| `calibration_evidence` | Full measured film-calibration/v1 receipt |
| `capture_profile` | Current configuration object used by Ableton's calibration tools |
| `loudness_path` | Explicit final mix/stem to measure through existing ffmpeg meter |
| `target_lufs`, `true_peak_max` | Explicit delivery limits; no delivery standard is guessed |

Checks independently report `pass`, `warn`, `fail` or `unknown`. Missing evidence
never passes. Aggregate status is `failed`, `incomplete`, `warnings` or `passed`.
The operation envelope maps these to failed, blocked, partial and success rather
than presenting an incomplete check as a successful handoff. Cue extent uses the
video end, not audio extending beyond picture. A media-pool ID without a readable
source path is unknown, not proof that the media is present.
Endpoint quietness is measured over the final 10 ms at -60 dBFS; it cannot decide
whether a musically appropriate reverb tail has finished. Coverage compares the
package body to cue intervals; picture markers may include non-music notes.
Loudness uses whole-file integrated LUFS with ±0.5 LU tolerance and a true-peak
ceiling; this is not dialogue-gated measurement. No automatic gain changes occur.

Resolve checks calibration receipt/configuration/file integrity, not fresh DSP.
Use Ableton's validation tool for remeasurement. Even valid receipts remain
warnings for current hardware settings and absolute picture alignment.

## Verification

Unit tests: `tests/test_film_stem_return.py`, `test_film_preflight.py`,
`test_film_picture_changes.py` and `test_film_lifecycle.py`.

`venv/Scripts/python.exe tests/live_film_stem_return_validation.py` creates one
owned temporary timeline in the current project and imports synthetic media via
real MCP. It restores the original timeline, deletes only the successful probe
timeline, retains synthetic files in scratch, and never saves the project.
Failure retains the probe for inspection. This is a mutating synthetic test, not
a command to run unattended against an actively edited project.

Ableton's `tests/live_film_workflow_validation.py` checks both configured servers,
the current Resolve cue sheet, a supplied saved ALS, synthetic calibration,
cross-MCP packaging/preflight and stale configuration refusal without live edits.
Synthetic calibration evidence is not a measured hardware latency profile.

On Resolve Studio 21.0.4.5, the real 24 fps probe verified one-hour-origin
placement, exact duration and duplicate refusal. NTSC timing is unit-tested;
the optional `--ntsc` live probe could not set 29.97 fps in the current project.
No project-wide frame-rate setting was changed to force that test through.
