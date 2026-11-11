# Picture-change reports

Compare two exported `film-cues/v1` documents without touching Resolve, Live,
source media or either input document. This is a cue-sheet comparison, not a
visual edit detection system or automatic musical reconform.

## Python interface

```python
from src.utils.film_picture_changes import compare_film_cues

report = compare_film_cues(before, after)
# Caller-confirmed identity: old cue ID -> new cue ID.
mapped_report = compare_film_cues(
    before, after, identity_map={"marker:240": "marker:264"}
)
```

Signature:
`compare_film_cues(before: dict, after: dict, identity_map: dict[str, str] | None = None) -> dict`.
Malformed documents, duplicate IDs and invalid/conflicting mappings raise
`ValueError`; there is no partial comparison on invalid input. Main integrates
this helper with the existing `timeline_markers` action `compare_cue_sheets`.
This module does not register or invoke an MCP tool.

Each input requires `schema: "film-cues/v1"`, a rational `frame_rate` object with
positive integer `numerator` and `denominator`, a `timeline` object containing
string `name` and `start_timecode` plus nonnegative integer `start_frame`, and a
`cues` list. Each cue requires a unique nonempty string `id`, string `name`,
nonnegative integer `start_frame` and positive integer `duration_frames`.
Optional `note`, `color` and `custom_data` are strings. Other JSON metadata is
preserved and compared. Optional numeric seconds fields must be finite and
nonnegative, but timing is always derived from frames, never these approximations.
Booleans, floats and numeric strings are refused as frame coordinates.

Limits: 10,000 cues, 8 MiB of canonical JSON per document, nesting depth 64,
frame rate at most 1,000 fps, and coordinates/rational components no larger than
`2**53 - 1`. Cue exclusive endpoints must also fit that integer limit.

## Identity rules

- IDs outside the reserved `marker:` namespace are assumed caller-stable and
  match exactly. The comparator cannot verify whether a producer reused an ID.
- Exported IDs such as `marker:240` encode position and must agree with their
  cue's `start_frame`. They do **not** survive a move. Names, notes and proximity
  never establish identity.
- Identical unmapped position-based cues at the same frame rate count only as
  unchanged observations, listed in `position_only_unchanged`; human review stays
  required. This does not prove that the same picture content remains there.
- Changed position-based cues, including metadata edits at the same frame, are
  reported as unmatched removal/addition unless explicitly mapped. Those labels
  describe document differences, not proof that the creative cue was deleted.
- `identity_map` maps existing before IDs to existing after IDs, one-to-one.
  It takes precedence over automatic matching. A mapping that would steal the
  destination of another implicit stable-ID match is refused. Explicitly map
  all participants if identities have been reassigned.

For example, a 48-frame cue at frame 240 moving to 264 at 24 fps is an unmatched
removal/addition when exported as `marker:240` and `marker:264`. With the explicit
map above, it is `moved`: +24 frames, exactly `{"numerator": 1, "denominator": 1}`
seconds. This mapping is the caller's assertion, not measured evidence.

## Reading the report

The report schema is `film-picture-changes/v1`. `status` is `compared` or
`incompatible_frame_rates`. Equivalent rationals such as 24/1 and 48/2 are
compatible. A rate change still permits stable/mapped cue comparison in rational
seconds, but `delta_frames` is `null`; do not use it as an automatic frame edit.
`compared` means a comparison was computed, not that the picture is unchanged
or delivery-ready.

`changes` contains entries with `before_id`, `after_id`, `match_basis`, `kinds`
and `before_range`/`after_range`. A matched cue can have several kinds: `moved`,
`resized`, and `metadata_edited`. Matched edits also include signed
`delta_frames`/`delta_seconds` for start, exclusive end and duration, plus
`metadata_changes`. A move means elapsed start seconds changed; a resize means
elapsed duration changed. Incompatible rates can cause these even when raw
frame coordinates are identical.

Unmatched entries have `added` or `removed` kinds and include detached
`before_cue`/`after_cue` snapshots. The absent side is `null`. Changes are
deterministic: before IDs in sorted order, then unmatched after IDs in sorted
order. Matched unchanged cues are counted in `unchanged_count`.

Each affected range is half-open `[start_frame, end_frame)` in its own picture's
relative frame coordinates, with exact rational start/end seconds. Keep before
and after ranges separate. A `timeline.start_frame` of 86400 at 24 fps is a
one-hour timecode origin; it does not add an hour of silence or move relative
cue positions. Timeline metadata edits set `picture_metadata_changed`.

`before` and `after` contain detached timeline metadata, normalised frame rates
and `fingerprint_sha256`. Fingerprints bind the complete supplied documents:
SHA-256 of ASCII JSON with sorted keys and compact separators, including cue
list order and optional approximate seconds fields. They do not hash picture
media or prove timeline identity. `media_identity_verified` is always false.

`requires_human_review` is true for incompatible rates, timeline metadata
changes, unmatched cues or position-only unchanged observations. A false value
does not approve a musical reconform: `automatic_reconform` is always false.
Review the changes and make musical decisions separately.

## Verification

From the repository root on Windows:

```powershell
venv/Scripts/python.exe -B -m pytest tests/test_film_picture_changes.py tests/test_film_cues.py -q -p no:cacheprovider
```

The comparison tests use plain JSON-shaped fixtures and exact expected
fractions. They cover unchanged/empty sheets, shifts, shortening, metadata
changes, additions/removals, position-ID ambiguity, explicit mapping conflicts,
NTSC/equivalent/changed rates, one-hour origins and validation on both inputs.
No live application or production media is involved.

## Picture cuts beneath unchanged markers

Cue-sheet changes alone cannot detect a picture cut when the markers stay put.
Supply the two existing conform snapshots for structural picture impact:

```python
from src.utils.film_picture_changes import compare_picture_impact

# Main obtains this through its existing _compare_timeline_snapshots helper.
impact = compare_picture_impact(
    before, after, before_snapshot, after_snapshot, editorial_comparison
)
```

`compare_picture_impact(before: dict, after: dict, before_snapshot: dict,
after_snapshot: dict, editorial_comparison: dict) -> dict` is a separate pure
function. Main may expose snapshots as optional `before_snapshot` and
`after_snapshot` parameters on `compare_cue_sheets`; this module neither calls
the server nor edits its registration. The supplied `editorial_comparison` is
returned as a detached copy, without modifying its conclusions or matching
clips anew.

Snapshots use the existing Resolve conform shape:
`tracks.video.tracks[].items`, with `track_index`, `item_count` and overall
`track_count`. Item `start` and exclusive `end` are **absolute timeline frames**;
`source_start`, `source_end`, `source_fps`, `file_path` and other item fields
describe the structural source selection. Cue-sheet and snapshot origins must
agree within each version, as must their names when the snapshot supplies one.
Duplicate track indices refuse rather than silently discarding a track.

Video items are compared conservatively by track index and array slot. This
does not establish correspondence, even when two slots have the same item ID.
Regenerated `timeline_item_id` values and enumeration-only `item_index` fields
are excluded from the picture signature. `media_pool_item_id` is also excluded
when a nonempty `file_path` is available: that path remains in the signature,
so different paths still count as changes. Source timing/rates and other
semantic properties remain compared. Full snapshot fingerprints retain these
IDs and can therefore change even when structural picture impact is empty.
Any differing item marks both the old and new spans; additions, removals,
unmatched tail items and removed tracks mark every available span. Inserting an
item near a track's start can therefore mark much of that track for review.
File-path/source-rate changes are considered even if the supplied editorial
comparison, which inspects fewer fields, says `match: true`.

Before intersecting with cues, subtract **each snapshot's own** `start_frame`
from its item bounds. An origin-only change does not create relative picture
impact. A frame-rate change marks all available video spans conservatively and
sets `frame_rates_compatible: false`; exact seconds are calculated separately
using each cue sheet's rational frame rate. Audio/subtitle changes are excluded
from the impact calculation. Snapshot fingerprints still cover the full supplied
snapshots, including audio/subtitle metadata, so they can differ without video
impact.

The `film-picture-impact/v1` report contains:

- `before_affected_cue_ids` and `after_affected_cue_ids`: sorted cue IDs affected
  or potentially affected in their own version. Half-open intersections avoid
  flagging a cue that starts exactly at a changed span's end.
- `changed_ranges`: each affected slot's version (`side`), track and item
  indices, relative frame bounds, rational seconds, and `evidence_status`.
  These ranges deliberately remain separate; they are not edit instructions.
- `before_snapshot_fingerprint` / `after_snapshot_fingerprint`: SHA-256 using
  the same compact, sorted-key ASCII JSON convention as cue fingerprints.
- `editorial_comparison`: the existing comparison supplied by main.
- `unknowns`, `unlocated_impact` and `requires_human_review`: uncertainty is
  never converted into a finding of no impact.

Unknown source coordinates/rates or media paths mark the known timeline span
as uncertain. An unknown timeline coordinate or incomplete video enumeration
can affect an unlocated region: **every cue on that side is then potentially
affected**, and `unlocated_impact[side]` is true. Missing video data is not treated
as an empty picture. Fully enumerated zero video tracks are an empty structural
picture. Missing/inconsistent enumeration counts are unknown; malformed JSON
and misbound cue/snapshot origins raise `ValueError`.

`status` is `unknown` when evidence is incomplete, otherwise
`incompatible_frame_rates` for differing clocks, otherwise `compared`.
Known changes and incompatible rates also require human review.
This remains **structural only**: snapshots are not rendered-picture or source
media hashes, grades/effects are unverified, no clip correspondence is inferred,
and no automatic movement or musical reconform is performed.
