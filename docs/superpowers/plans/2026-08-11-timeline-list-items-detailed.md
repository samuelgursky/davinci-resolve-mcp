# Timeline Detailed Item Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a generic `timeline(action="list_items_detailed")` read action that returns enabled-track metadata, stable track-local item selectors, timeline/source ranges, and source-media status in one call.

**Architecture:** Add one private inventory helper beside the existing timeline-item summary helpers and route one new action to it from the compound timeline dispatcher. Reuse `_timeline_item_summary`, `_media_pool_item_summary`, `_timeline_item_media_pool_item`, `_safe_clip_call`, and the standard `_ok`/`_err` envelopes; preserve the existing `get_items` contracts unchanged.

**Tech Stack:** Python 3.10+, `unittest`, `unittest.mock`, Resolve scripting API test doubles, FastMCP compound server.

## Global Constraints

- `track_types` defaults to `["video"]` and accepts a non-empty unique list drawn only from `video`, `audio`, and `subtitle`.
- `enabled_only` defaults to `true` and must be a real boolean.
- `track_index` is one-based; `item_index` is zero-based within its track.
- Unknown enabled state must include the track's items and emit a structured warning.
- Empty inventories are successful reads with `count: 0`.
- Existing `get_items` and `get_items_in_track` output must not change.
- No Instagram-specific policy, new dependency, or new granular MCP tool.
- Every production change follows red-green-refactor: observe the focused test fail for the intended missing behavior before implementation.

---

## File map

- Create `tests/test_timeline_items_detailed.py`: focused public-dispatch contract tests and Resolve test-double builders.
- Modify `src/server.py`: private inventory/validation helper, timeline action routing, action inventory, docstring, and pull-on-demand action help.
- Modify `tests/test_action_help.py`: action-help exposure regression test.

### Task 1: Core video inventory and rich item metadata

**Files:**
- Create: `tests/test_timeline_items_detailed.py`
- Modify: `src/server.py:2977-3006`
- Modify: `src/server.py:20821-20840`
- Modify: `src/server.py:21171-21176`

**Interfaces:**
- Consumes: `_timeline_item_summary(item, track_info=None)`, `_timeline_item_media_pool_item(item)`, `_media_pool_item_summary(clip)`, `_safe_clip_call(clip, method, *args)`, `_ok(**fields)`, `_err(message, ...)`.
- Produces: `_timeline_list_items_detailed(tl, p) -> Dict[str, Any]` and public `timeline(action="list_items_detailed", params={...})`.

- [ ] **Step 1: Create the focused test module with one failing default-contract test**

```python
"""Contract tests for timeline.list_items_detailed."""
import unittest
from unittest import mock

import src.server as s


def _media_pool_item(name="clip.mov", uid="mpi-1", path="D:/media/clip.mov", online="Online"):
    clip = mock.Mock()
    clip.GetName.return_value = name
    clip.GetUniqueId.return_value = uid
    clip.GetMediaId.return_value = "media-1"

    def get_property(key=""):
        properties = {
            "File Path": path,
            "Online Status": online,
            "Type": "Video + Audio",
            "Duration": "120",
        }
        return properties if key == "" else properties.get(key)

    clip.GetClipProperty.side_effect = get_property
    return clip


def _item(name="clip.mov", uid="ti-1", start=86400, duration=120,
          source_start=24, media_pool_item=None):
    item = mock.Mock()
    item.GetName.return_value = name
    item.GetUniqueId.return_value = uid
    item.GetStart.return_value = start
    item.GetEnd.return_value = start + duration
    item.GetDuration.return_value = duration
    item.GetSourceStartFrame.return_value = source_start
    item.GetMediaPoolItem.return_value = media_pool_item or _media_pool_item(name=name)
    return item


def _timeline(track_items=None, enabled=None):
    if track_items is None:
        track_items = {("video", 1): [_item()]}
    if enabled is None:
        enabled = {key: True for key in track_items}
    timeline = mock.Mock()
    timeline.GetTrackCount.side_effect = lambda track_type: max(
        (index for kind, index in track_items if kind == track_type), default=0
    )
    timeline.GetIsTrackEnabled.side_effect = lambda track_type, index: enabled[(track_type, index)]
    timeline.GetItemListInTrack.side_effect = lambda track_type, index: list(
        track_items.get((track_type, index), [])
    )
    return timeline


def _dispatch(timeline, params=None):
    project = mock.Mock()
    project.GetCurrentTimeline.return_value = timeline
    with mock.patch.object(s, "_check", return_value=(mock.Mock(), project, None)):
        return s.timeline("list_items_detailed", params or {})


class TimelineItemsDetailedTest(unittest.TestCase):
    def test_defaults_return_enabled_video_item_with_source_metadata(self):
        out = _dispatch(_timeline())

        self.assertTrue(out["success"], out)
        self.assertEqual(out["track_types"], ["video"])
        self.assertTrue(out["enabled_only"])
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["warnings"], [])
        self.assertEqual(
            out["tracks"],
            [{
                "track_type": "video", "track_index": 1, "enabled": True,
                "item_count": 1, "included_item_count": 1,
            }],
        )
        self.assertEqual(
            out["items"][0],
            {
                "timeline_item_id": "ti-1", "name": "clip.mov",
                "track_type": "video", "track_index": 1, "item_index": 0,
                "start": 86400, "end": 86520, "duration": 120,
                "source_start": 24, "source_end": 144,
                "media_pool_item_id": "mpi-1", "media_pool_item_name": "clip.mov",
                "file_path": "D:/media/clip.mov", "online_status": "Online",
            },
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m unittest tests.test_timeline_items_detailed.TimelineItemsDetailedTest.test_defaults_return_enabled_video_item_with_source_metadata -v
```

Expected: FAIL because `list_items_detailed` is not present in `_TIMELINE_ACTIONS` or the timeline dispatcher.

- [ ] **Step 3: Add the minimal inventory helper and route the action**

Add beside `_timeline_item_summary`:

```python
_DETAILED_ITEM_TRACK_TYPES = ("video", "audio", "subtitle")


def _timeline_list_items_detailed(tl, p: Dict[str, Any]) -> Dict[str, Any]:
    track_types = p.get("track_types", ["video"])
    enabled_only = p.get("enabled_only", True)
    tracks = []
    items = []
    warnings = []

    for track_type in track_types:
        for track_index in range(1, int(tl.GetTrackCount(track_type)) + 1):
            enabled = bool(tl.GetIsTrackEnabled(track_type, track_index))
            track_items = list(tl.GetItemListInTrack(track_type, track_index) or [])
            include = not enabled_only or enabled
            tracks.append({
                "track_type": track_type,
                "track_index": track_index,
                "enabled": enabled,
                "item_count": len(track_items),
                "included_item_count": len(track_items) if include else 0,
            })
            if not include:
                continue
            for item_index, item in enumerate(track_items):
                row = _timeline_item_summary(item, (track_type, track_index))
                row["item_index"] = item_index
                media_pool_item = _timeline_item_media_pool_item(item)
                media_summary = _media_pool_item_summary(media_pool_item) if media_pool_item else None
                online_status, _ = _safe_clip_call(
                    media_pool_item, "GetClipProperty", "Online Status"
                ) if media_pool_item else (None, None)
                row["file_path"] = media_summary.get("file_path") if media_summary else None
                row["online_status"] = online_status
                items.append(row)

    return _ok(
        count=len(items),
        track_types=track_types,
        enabled_only=enabled_only,
        tracks=tracks,
        items=items,
        warnings=warnings,
    )
```

Add `list_items_detailed` to `_TIMELINE_ACTIONS`, then add this dispatcher branch immediately before the existing `get_items` branch:

```python
    elif action == "list_items_detailed":
        return _timeline_list_items_detailed(tl, p)
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```powershell
python -m unittest tests.test_timeline_items_detailed.TimelineItemsDetailedTest.test_defaults_return_enabled_video_item_with_source_metadata -v
```

Expected: PASS.

- [ ] **Step 5: Commit the independently working core inventory**

```powershell
git add tests/test_timeline_items_detailed.py src/server.py
git commit -m "feat(timeline): add detailed item inventory"
```

### Task 2: Filtering, warnings, validation, and failure envelopes

**Files:**
- Modify: `tests/test_timeline_items_detailed.py`
- Modify: `src/server.py` (`_timeline_list_items_detailed` from Task 1)

**Interfaces:**
- Consumes: `_timeline_list_items_detailed(tl, p)` from Task 1.
- Produces: the complete validated API contract, structured track warnings, and structured top-level Resolve API failures.

- [ ] **Step 1: Add failing behavior tests below the default test**

```python
    def test_layered_tracks_keep_zero_based_item_index_per_track(self):
        out = _dispatch(_timeline({
            ("video", 1): [_item(uid="v1-a"), _item(uid="v1-b")],
            ("video", 2): [_item(uid="v2-a")],
        }))
        self.assertEqual(
            [(row["track_index"], row["item_index"], row["timeline_item_id"])
             for row in out["items"]],
            [(1, 0, "v1-a"), (1, 1, "v1-b"), (2, 0, "v2-a")],
        )

    def test_disabled_track_is_reported_but_omitted_by_default(self):
        tl = _timeline(
            {("video", 1): [_item(uid="enabled")], ("video", 2): [_item(uid="disabled")]},
            {("video", 1): True, ("video", 2): False},
        )
        out = _dispatch(tl)
        self.assertEqual([row["timeline_item_id"] for row in out["items"]], ["enabled"])
        self.assertEqual(out["tracks"][1]["item_count"], 1)
        self.assertEqual(out["tracks"][1]["included_item_count"], 0)

    def test_enabled_only_false_includes_disabled_items(self):
        tl = _timeline(
            {("video", 1): [_item(uid="disabled")]},
            {("video", 1): False},
        )
        out = _dispatch(tl, {"enabled_only": False})
        self.assertEqual([row["timeline_item_id"] for row in out["items"]], ["disabled"])

    def test_requested_track_types_preserve_caller_order(self):
        tl = _timeline({
            ("audio", 1): [_item(uid="a1")],
            ("video", 1): [_item(uid="v1")],
            ("subtitle", 1): [_item(uid="s1", media_pool_item=mock.Mock())],
        })
        out = _dispatch(tl, {"track_types": ["audio", "video", "subtitle"]})
        self.assertEqual(
            [(row["track_type"], row["timeline_item_id"]) for row in out["items"]],
            [("audio", "a1"), ("video", "v1"), ("subtitle", "s1")],
        )

    def test_unknown_enabled_state_warns_and_includes_items(self):
        tl = _timeline({("video", 1): [_item(uid="kept")]})
        tl.GetIsTrackEnabled.side_effect = RuntimeError("page busy")
        out = _dispatch(tl)
        self.assertEqual([row["timeline_item_id"] for row in out["items"]], ["kept"])
        self.assertIsNone(out["tracks"][0]["enabled"])
        self.assertEqual(out["warnings"][0]["code"], "TRACK_ENABLED_STATE_UNAVAILABLE")
        self.assertEqual(out["warnings"][0]["track_index"], 1)

    def test_item_without_media_pool_object_has_null_source_fields(self):
        item = _item()
        item.GetMediaPoolItem.return_value = None
        out = _dispatch(_timeline({("video", 1): [item]}))
        self.assertIsNone(out["items"][0]["media_pool_item_id"])
        self.assertIsNone(out["items"][0]["file_path"])
        self.assertIsNone(out["items"][0]["online_status"])

    def test_empty_timeline_is_successful(self):
        out = _dispatch(_timeline({}))
        self.assertTrue(out["success"], out)
        self.assertEqual(out["count"], 0)
        self.assertEqual(out["tracks"], [])
        self.assertEqual(out["items"], [])

    def test_invalid_parameters_return_structured_errors(self):
        invalid = [
            ({"track_types": "video"}, "INVALID_TRACK_TYPES"),
            ({"track_types": []}, "INVALID_TRACK_TYPES"),
            ({"track_types": ["bogus"]}, "INVALID_TRACK_TYPES"),
            ({"track_types": ["video", "video"]}, "INVALID_TRACK_TYPES"),
            ({"enabled_only": 1}, "INVALID_ENABLED_ONLY"),
        ]
        for params, code in invalid:
            with self.subTest(params=params):
                out = _dispatch(_timeline(), params)
                self.assertEqual(out["error"]["code"], code)
                self.assertEqual(out["error"]["category"], "invalid_input")

    def test_item_list_failure_is_a_top_level_error(self):
        tl = _timeline()
        tl.GetItemListInTrack.side_effect = RuntimeError("Resolve refused")
        out = _dispatch(tl)
        self.assertEqual(out["error"]["code"], "TRACK_ITEMS_READ_FAILED")
        self.assertEqual(out["error"]["category"], "resolve_api_failed")
```

- [ ] **Step 2: Run the complete focused module and verify RED**

Run:

```powershell
python -m unittest tests.test_timeline_items_detailed -v
```

Expected: failures for invalid parameter acceptance, unknown enabled-state handling, and top-level item-list failure handling.

- [ ] **Step 3: Replace the Task 1 helper with the complete validated implementation**

```python
_DETAILED_ITEM_TRACK_TYPES = ("video", "audio", "subtitle")


def _timeline_list_items_detailed(tl, p: Dict[str, Any]) -> Dict[str, Any]:
    track_types = p.get("track_types", ["video"])
    if not isinstance(track_types, list) or not track_types:
        return _err(
            "track_types must be a non-empty list",
            code="INVALID_TRACK_TYPES",
            category="invalid_input",
        )
    if any(not isinstance(value, str) or value not in _DETAILED_ITEM_TRACK_TYPES
           for value in track_types):
        return _err(
            "track_types values must be video, audio, or subtitle",
            code="INVALID_TRACK_TYPES",
            category="invalid_input",
        )
    if len(set(track_types)) != len(track_types):
        return _err(
            "track_types values must be unique",
            code="INVALID_TRACK_TYPES",
            category="invalid_input",
        )

    enabled_only = p.get("enabled_only", True)
    if not isinstance(enabled_only, bool):
        return _err(
            "enabled_only must be a boolean",
            code="INVALID_ENABLED_ONLY",
            category="invalid_input",
        )

    tracks = []
    items = []
    warnings = []
    for track_type in track_types:
        try:
            track_count = int(tl.GetTrackCount(track_type))
        except Exception as exc:
            return _err(
                f"Could not read {track_type} track count: {exc}",
                code="TRACK_COUNT_READ_FAILED",
                category="resolve_api_failed",
            )
        for track_index in range(1, track_count + 1):
            try:
                raw_enabled = tl.GetIsTrackEnabled(track_type, track_index)
                if isinstance(raw_enabled, bool):
                    enabled = raw_enabled
                elif raw_enabled in (0, 1):
                    enabled = bool(raw_enabled)
                else:
                    raise ValueError(f"unexpected enabled value: {raw_enabled!r}")
            except Exception as exc:
                enabled = None
                warnings.append({
                    "code": "TRACK_ENABLED_STATE_UNAVAILABLE",
                    "track_type": track_type,
                    "track_index": track_index,
                    "message": str(exc),
                })

            try:
                track_items = list(tl.GetItemListInTrack(track_type, track_index) or [])
            except Exception as exc:
                return _err(
                    f"Could not list {track_type} track {track_index}: {exc}",
                    code="TRACK_ITEMS_READ_FAILED",
                    category="resolve_api_failed",
                    state={"track_type": track_type, "track_index": track_index},
                )

            include = not enabled_only or enabled is not False
            tracks.append({
                "track_type": track_type,
                "track_index": track_index,
                "enabled": enabled,
                "item_count": len(track_items),
                "included_item_count": len(track_items) if include else 0,
            })
            if not include:
                continue

            for item_index, item in enumerate(track_items):
                row = _timeline_item_summary(item, (track_type, track_index))
                row["item_index"] = item_index
                media_pool_item = _timeline_item_media_pool_item(item)
                media_summary = _media_pool_item_summary(media_pool_item) if media_pool_item else None
                online_status, _online_error = _safe_clip_call(
                    media_pool_item, "GetClipProperty", "Online Status"
                ) if media_pool_item else (None, None)
                row["file_path"] = media_summary.get("file_path") if media_summary else None
                row["online_status"] = online_status
                items.append(row)

    return _ok(
        count=len(items),
        track_types=list(track_types),
        enabled_only=enabled_only,
        tracks=tracks,
        items=items,
        warnings=warnings,
    )
```

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
python -m unittest tests.test_timeline_items_detailed -v
```

Expected: all tests in the module PASS.

- [ ] **Step 5: Run existing selector regressions**

Run:

```powershell
python -m unittest tests.test_get_items_selector -v
```

Expected: all existing `get_items` and `get_items_in_track` tests PASS with unchanged payloads.

- [ ] **Step 6: Commit the completed behavior contract**

```powershell
git add tests/test_timeline_items_detailed.py src/server.py
git commit -m "test(timeline): cover detailed inventory safety"
```

### Task 3: Action help, documentation, and full verification

**Files:**
- Modify: `tests/test_action_help.py`
- Modify: `src/server.py:20846-20980`
- Modify: `src/server.py:22754-22766`

**Interfaces:**
- Consumes: public `list_items_detailed` behavior completed in Tasks 1-2.
- Produces: pull-on-demand action help and concise top-level tool documentation discoverable by MCP clients.

- [ ] **Step 1: Add a failing action-help contract test**

Add to `ActionHelpFullActionListTest`:

```python
    def test_detailed_item_inventory_has_pull_on_demand_help(self):
        out = compound._action_help("timeline", {"name": "list_items_detailed"})
        self.assertTrue(out.get("success"), out)
        self.assertEqual(out["action"], "list_items_detailed")
        self.assertIn("track_types", out["params"])
        self.assertIn("item_index", out["returns"])
        self.assertIn("list_items_detailed", out["example"])
```

- [ ] **Step 2: Run the new help test and verify RED**

Run:

```powershell
python -m unittest tests.test_action_help.ActionHelpFullActionListTest.test_detailed_item_inventory_has_pull_on_demand_help -v
```

Expected: FAIL with `HELP_NOT_REGISTERED`.

- [ ] **Step 3: Register action help and update the timeline docstring**

Add this entry to `_ACTION_HELP["timeline"]`:

```python
        "list_items_detailed": {
            "summary": "List detailed items across requested tracks, omitting confirmed-disabled tracks by default.",
            "params": "track_types? ([video|audio|subtitle], default [video]), enabled_only? (bool, default true)",
            "returns": "{success, count, tracks, items: [{track_type, track_index, item_index, timeline_item_id, source_start, source_end, media_pool_item_id, file_path, online_status}], warnings}",
            "example": (
                'timeline(action="list_items_detailed", params={\n'
                '  "track_types": ["video"],\n'
                '  "enabled_only": True\n'
                '})'
            ),
        },
```

Add this concise line to the timeline tool docstring's read-action list near `get_items_in_track`:

```text
      list_items_detailed(track_types?, enabled_only?) -> {count, tracks, items, warnings}
```

- [ ] **Step 4: Run the action-help test and verify GREEN**

Run:

```powershell
python -m unittest tests.test_action_help.ActionHelpFullActionListTest.test_detailed_item_inventory_has_pull_on_demand_help -v
```

Expected: PASS.

- [ ] **Step 5: Run focused and adjacent test suites**

Run:

```powershell
python -m unittest tests.test_timeline_items_detailed tests.test_get_items_selector tests.test_action_help tests.test_tool_exposure -v
```

Expected: all tests PASS with zero failures and zero errors.

- [ ] **Step 6: Run repository-wide unit verification**

Run:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Expected: exit code 0 with zero failures and zero errors. If environment-only live/optional dependency tests cannot run, record their exact names and errors, then run every non-live unit suite and report the limitation rather than claiming the full suite passed.

- [ ] **Step 7: Check the final diff and whitespace**

Run:

```powershell
git diff --check
git status --short
git diff -- src/server.py tests/test_timeline_items_detailed.py tests/test_action_help.py
```

Expected: `git diff --check` exits 0; only the planned implementation and test files are modified.

- [ ] **Step 8: Commit the documented, verified feature**

```powershell
git add src/server.py tests/test_timeline_items_detailed.py tests/test_action_help.py
git commit -m "docs(timeline): expose detailed item inventory"
```

- [ ] **Step 9: Verify the committed tree before handoff**

Run:

```powershell
git status --short --branch
git log -4 --oneline
python -m unittest tests.test_timeline_items_detailed tests.test_get_items_selector tests.test_action_help -v
```

Expected: branch `justin` is clean, the three implementation commits follow the design commit, and the final focused verification passes with zero failures and zero errors.
