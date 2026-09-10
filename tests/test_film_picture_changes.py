"""Pure picture comparison fixtures; no Resolve, media, files or fuzzy identity."""
from copy import deepcopy
import importlib
import json

import pytest


def compare(*args, **kwargs):
    return importlib.import_module("src.utils.film_picture_changes").compare_film_cues(
        *args, **kwargs
    )


def cue(identity="cue-A", start=240, duration=48, **metadata):
    return {"id": identity, "start_frame": start, "duration_frames": duration,
            "name": "Entrance", "note": "Cello", "color": "Blue",
            "custom_data": "", **metadata}


def sheet(*cues, fps=(24, 1), origin=86400):
    return {"schema": "film-cues/v1",
            "frame_rate": {"numerator": fps[0], "denominator": fps[1]},
            "timeline": {"name": "Picture v1", "start_frame": origin,
                         "start_timecode": "01:00:00:00"},
            "cues": list(cues)}


def test_unchanged_and_empty_sheets_are_pure_and_fingerprinted():
    before = sheet(cue())
    original = deepcopy(before)
    report = compare(before, deepcopy(before))
    assert report["status"] == "compared"
    assert report["changes"] == [] and report["unchanged_count"] == 1
    assert report["before"]["fingerprint_sha256"] == report["after"]["fingerprint_sha256"]
    assert len(report["before"]["fingerprint_sha256"]) == 64
    assert before == original
    report["before"]["timeline"]["name"] = "Caller mutates report"
    assert before == original
    assert compare(sheet(), sheet())["changes"] == []


def test_moved_shortened_and_metadata_edits_have_exact_relative_ranges():
    report = compare(sheet(cue()), sheet(cue(start=264, duration=24, note="Flute")))
    change, = report["changes"]
    assert change["kinds"] == ["moved", "resized", "metadata_edited"]
    assert change["match_basis"] == "stable_id"
    assert change["delta_frames"] == {"start": 24, "end": 0, "duration": -24}
    assert change["delta_seconds"] == {
        "start": {"numerator": 1, "denominator": 1},
        "end": {"numerator": 0, "denominator": 1},
        "duration": {"numerator": -1, "denominator": 1}}
    assert change["metadata_changes"] == {"note": {"before": "Cello", "after": "Flute"}}
    assert change["before_range"]["start_frame"] == 240
    assert change["before_range"]["end_frame"] == 288
    assert change["before_range"]["start_seconds"] == {"numerator": 10, "denominator": 1}
    assert change["after_range"]["start_frame"] == 264
    assert report["before"]["timeline"]["start_frame"] == 86400


def test_added_removed_and_names_never_imply_identity():
    report = compare(sheet(cue("old")), sheet(cue("new", start=300)))
    assert [c["kinds"] for c in report["changes"]] == [["removed"], ["added"]]
    assert report["changes"][0]["after_range"] is None
    assert report["changes"][1]["before_range"] is None


def test_position_ids_need_mapping_to_claim_a_move():
    before, after = sheet(cue("marker:240")), sheet(cue("marker:264", start=264))
    report = compare(before, after)
    assert [c["kinds"] for c in report["changes"]] == [["removed"], ["added"]]
    assert report["requires_human_review"] is True
    mapped = compare(before, after, {"marker:240": "marker:264"})
    change, = mapped["changes"]
    assert change["kinds"] == ["moved"] and change["match_basis"] == "explicit_mapping"
    assert change["before_id"] == "marker:240" and change["after_id"] == "marker:264"


def test_unchanged_position_is_an_observation_not_a_stable_identity():
    report = compare(sheet(cue("marker:240")), sheet(cue("marker:240")))
    assert report["changes"] == [] and report["unchanged_count"] == 1
    assert report["position_only_unchanged"] == ["marker:240"]
    assert report["requires_human_review"] is True


def test_reused_position_id_with_changed_metadata_remains_ambiguous():
    before, after = sheet(cue("marker:240")), sheet(cue("marker:240", name="New scene"))
    report = compare(before, after)
    assert [c["kinds"] for c in report["changes"]] == [["removed"], ["added"]]
    mapped = compare(before, after, {"marker:240": "marker:240"})
    assert mapped["changes"][0]["kinds"] == ["metadata_edited"]


def test_ntsc_deltas_use_exact_rationals_and_equivalent_rates_match():
    report = compare(sheet(cue(start=1), fps=(30000, 1001)),
                     sheet(cue(start=2), fps=(60000, 2002)))
    assert report["frame_rates_compatible"] is True
    assert report["changes"][0]["delta_seconds"]["start"] == {
        "numerator": 1001, "denominator": 30000}


def test_rate_change_is_explicit_even_when_raw_frames_are_identical():
    report = compare(sheet(cue()), sheet(cue(), fps=(25, 1)))
    assert report["status"] == "incompatible_frame_rates"
    assert report["requires_human_review"] is True
    change, = report["changes"]
    assert change["kinds"] == ["moved", "resized"]
    assert change["delta_frames"] is None
    assert change["delta_seconds"]["start"] == {"numerator": -2, "denominator": 5}


def test_timeline_identity_change_does_not_rebase_relative_cues():
    before, after = sheet(cue()), sheet(cue(), origin=0)
    after["timeline"]["name"] = "Picture v2"
    report = compare(before, after)
    assert report["changes"] == []
    assert report["picture_metadata_changed"] is True
    assert report["before"]["fingerprint_sha256"] != report["after"]["fingerprint_sha256"]


def test_derived_seconds_are_not_used_as_timing_or_metadata():
    before, after = sheet(cue(start_seconds=10.0)), sheet(cue(start_seconds=99.0))
    assert compare(before, after)["changes"] == []


@pytest.mark.parametrize("mapping", [[], {"missing": "cue-A"}, {"cue-A": "missing"},
    {"cue-A": "cue-A", "cue-B": "cue-A"}, {"cue-A": "cue-B"}, {"cue-A": True}])
def test_invalid_or_implicit_identity_conflicts_refuse(mapping):
    document = sheet(cue(), cue("cue-B", start=400))
    with pytest.raises(ValueError):
        compare(document, document, mapping)


@pytest.mark.parametrize("mutate", [
    lambda s: s.update(schema="wrong"),
    lambda s: s.update(cues=[None]),
    lambda s: s["cues"].append(deepcopy(s["cues"][0])),
    lambda s: s["cues"][0].update(start_frame=True),
    lambda s: s["cues"][0].update(start_frame=-1),
    lambda s: s["cues"][0].update(start_frame=1.5),
    lambda s: s["cues"][0].update(duration_frames=0),
    lambda s: s["cues"][0].update(name=123),
    lambda s: s["cues"][0].update(id=""),
    lambda s: s["cues"][0].update(id="marker:241"),
    lambda s: s["cues"][0].update(start_seconds=float("nan")),
    lambda s: s["frame_rate"].update(numerator=True),
    lambda s: s["frame_rate"].update(denominator=0),
    lambda s: s.update(timeline=[]),
    lambda s: s["timeline"].update(start_frame=-1),
    lambda s: s.update(extra={1: "non-JSON-key"}),
])
@pytest.mark.parametrize("side", ["before", "after"])
def test_invalid_documents_are_rejected_on_either_side(mutate, side):
    documents = {"before": sheet(cue()), "after": sheet(cue())}
    mutate(documents[side])
    with pytest.raises(ValueError):
        compare(**documents)


def test_non_object_root_rejected_and_output_is_json_serialisable():
    with pytest.raises(ValueError):
        compare([], sheet())
    json.dumps(compare(sheet(cue()), sheet(cue(start=241))), allow_nan=False)


def impact(before, after, old_snapshot, new_snapshot, editorial=None):
    return importlib.import_module("src.utils.film_picture_changes").compare_picture_impact(
        before, after, old_snapshot, new_snapshot,
        {"match": True, "difference_count": 0, "differences": []} if editorial is None else editorial)


def shot(start=86400, end=86448, **extra):
    return {"timeline_item_id": "clip1", "name": "Scene", "start": start, "end": end,
            "source_start": 0, "source_end": 48, "source_fps": 24.0,
            "file_path": "D:/picture/scene.mov", **extra}


def snapshot(*items, origin=86400):
    return {"id": "timeline1", "name": "Picture v1", "start_frame": origin,
            "end_frame": origin + 1000,
            "tracks": {"video": {"track_count": 1, "tracks": [
                {"track_index": 1, "item_count": len(items), "items": list(items)}]}}}


def test_picture_source_cut_impacts_unchanged_cues_and_preserves_existing_comparison():
    cues = sheet(cue(start=24, duration=12), cue("outside", start=48))
    before, after = snapshot(shot()), snapshot(shot(source_start=24, source_end=72))
    supplied = {"match": False, "difference_count": 1,
                "differences": [{"kind": "item_mismatch", "changes": {"source_start": {"left": 0, "right": 24}}}]}
    originals = deepcopy((cues, before, after, supplied))
    assert compare(cues, cues)["changes"] == []
    report = impact(cues, cues, before, after, supplied)
    assert report["before_affected_cue_ids"] == ["cue-A"]
    assert report["after_affected_cue_ids"] == ["cue-A"]
    assert report["requires_human_review"] is True
    assert report["editorial_comparison"] == supplied
    assert report["before_snapshot_fingerprint"] != report["after_snapshot_fingerprint"]
    assert [(r["side"], r["start_frame"], r["end_frame"]) for r in report["changed_ranges"]] == [
        ("before", 0, 48), ("after", 0, 48)]
    report["editorial_comparison"]["differences"].clear()
    assert (cues, before, after, supplied) == originals


def test_picture_insertion_marks_shifted_slots_and_unmatched_tail():
    cues = sheet(cue(start=0, duration=10), cue("tail", start=96, duration=10))
    old = snapshot(shot(), shot(86448, 86496, timeline_item_id="clip2", source_start=48, source_end=96))
    new = snapshot(shot(file_path="D:/picture/insert.mov"),
                   shot(86448, 86496), shot(86496, 86544, timeline_item_id="clip2",
                                          source_start=48, source_end=96))
    report = impact(cues, cues, old, new)
    assert report["before_affected_cue_ids"] == ["cue-A"]
    assert report["after_affected_cue_ids"] == ["cue-A", "tail"]
    assert len(report["changed_ranges"]) == 5
    assert report["clip_correspondence_inferred"] is False
    assert report["automatic_reconform"] is False


def test_picture_removed_track_marks_all_old_spans_only():
    cues = sheet(cue(start=24))
    before, after = snapshot(shot()), snapshot()
    after["tracks"]["video"] = {"track_count": 0, "tracks": []}
    report = impact(cues, cues, before, after)
    assert report["before_affected_cue_ids"] == ["cue-A"]
    assert report["after_affected_cue_ids"] == []
    assert [r["side"] for r in report["changed_ranges"]] == ["before"]


def test_picture_origin_only_change_does_not_create_relative_impact():
    before, after = sheet(cue(start=24)), sheet(cue(start=24), origin=0)
    report = impact(before, after, snapshot(shot()), snapshot(shot(0, 48), origin=0))
    assert report["changed_ranges"] == []
    assert report["before_affected_cue_ids"] == report["after_affected_cue_ids"] == []
    assert report["status"] == "compared"


def test_picture_rate_change_keeps_each_versions_ranges_and_seconds():
    before, after = sheet(cue(start=24)), sheet(cue(start=24), fps=(25, 1), origin=0)
    report = impact(before, after, snapshot(shot()), snapshot(shot(0, 48), origin=0))
    assert report["status"] == "incompatible_frame_rates"
    assert report["frame_rates_compatible"] is False
    assert report["before_affected_cue_ids"] == report["after_affected_cue_ids"] == ["cue-A"]
    assert report["changed_ranges"][0]["end_seconds"] == {"numerator": 2, "denominator": 1}
    assert report["changed_ranges"][1]["end_seconds"] == {"numerator": 48, "denominator": 25}


@pytest.mark.parametrize("field,value", [("start", None), ("end", None), ("end", 86399),
                                         ("start", True), ("source_start", None), ("source_fps", None)])
def test_picture_unknown_coordinates_cannot_report_no_impact(field, value):
    cues = sheet(cue(start=24), cue("distant", start=500))
    incomplete = snapshot(shot(**{field: value}))
    report = impact(cues, cues, incomplete, deepcopy(incomplete))
    assert report["status"] == "unknown" and report["requires_human_review"] is True
    assert report["unknowns"]
    if field in ("start", "end"):
        assert report["before_affected_cue_ids"] == ["cue-A", "distant"]
    else:
        assert report["before_affected_cue_ids"] == ["cue-A"]


def test_picture_missing_video_enumeration_is_unknown_not_empty_picture():
    cues = sheet(cue(start=24))
    broken = snapshot()
    broken["tracks"] = {}
    report = impact(cues, cues, broken, snapshot(shot()))
    assert report["status"] == "unknown"
    assert report["before_affected_cue_ids"] == ["cue-A"]


def test_picture_file_path_change_counts_even_if_editorial_comparison_says_match():
    cues = sheet(cue(start=24))
    report = impact(cues, cues, snapshot(shot()), snapshot(shot(file_path="D:/other.mov")))
    assert report["editorial_comparison"]["match"] is True
    assert report["before_affected_cue_ids"] == ["cue-A"]
    assert report["structural_only"] is True and report["media_identity_verified"] is False


def test_picture_snapshot_origin_mismatch_refuses_misbound_evidence():
    with pytest.raises(ValueError):
        impact(sheet(cue()), sheet(cue()), snapshot(shot(), origin=0), snapshot(shot()))


def test_picture_unchanged_video_ignores_audio_changes():
    before, after = snapshot(shot()), snapshot(shot())
    after["tracks"]["audio"] = {"tracks": [{"items": [{"name": "new stem"}]}]}
    report = impact(sheet(cue(start=24)), sheet(cue(start=24)), before, after)
    assert report["changed_ranges"] == []
    assert report["requires_human_review"] is False


def test_picture_duplicate_track_indices_refuse_silent_overwrite():
    before = snapshot(shot())
    before["tracks"]["video"]["tracks"].append(deepcopy(before["tracks"]["video"]["tracks"][0]))
    with pytest.raises(ValueError):
        impact(sheet(cue()), sheet(cue()), before, snapshot(shot()))


@pytest.mark.parametrize("field,old_value,new_value", [
    ("timeline_item_id", "old-timeline-item", "copied-timeline-item"),
    ("media_pool_item_id", "old-pool-item", "reimported-pool-item"),
    ("item_index", 0, 7),
])
def test_picture_regenerated_ids_and_enumeration_do_not_change_content(field, old_value, new_value):
    cues = sheet(cue(start=24))
    old = snapshot(shot(**{field: old_value}))
    new = snapshot(shot(**{field: new_value}))
    report = impact(cues, cues, old, new)
    assert report["changed_ranges"] == []
    assert report["before_affected_cue_ids"] == report["after_affected_cue_ids"] == []
    assert report["requires_human_review"] is False
    assert report["before_snapshot_fingerprint"] != report["after_snapshot_fingerprint"]


def test_picture_semantic_property_changes_still_impact_with_regenerated_ids():
    cues = sheet(cue(start=24))
    old = snapshot(shot(timeline_item_id="old", media_pool_item_id="pool1", opacity=100))
    new = snapshot(shot(timeline_item_id="new", media_pool_item_id="pool2", opacity=50))
    report = impact(cues, cues, old, new)
    assert report["before_affected_cue_ids"] == report["after_affected_cue_ids"] == ["cue-A"]
