import unittest
import tempfile
from pathlib import Path

from src.server import (
    _copy_clip_annotations,
    _copy_metadata,
    _media_pool_ingest_capabilities,
    _media_pool_item_probe,
    _media_pool_probe,
    _media_pool_probe_ingest_items,
    _metadata_field_inventory,
    _metadata_panel_group_for_field,
    _metadata_write_field_for_field,
    _normalize_metadata,
    _probe_clip_properties,
    _safe_import_sequence,
    _set_clip_marks,
)


class MediaPoolItemStub:
    def __init__(self, unique_id="clip-1", name="synthetic_ingest_source.mov"):
        self.unique_id = unique_id
        self.name = name
        self.metadata = {"Camera #": "A"}
        self.third_party_metadata = {"review_status": "approved"}
        self.properties = {
            "File Path": "/tmp/synthetic_ingest_source.mov",
            "Type": "Video + Audio",
            "Duration": "00:00:05:00",
            "FPS": "24",
            "Description": "",
            "Comments": "",
            "Keyword": "",
            "People": "",
            "Scene": "",
            "Camera #": "A",
            "Audio Notes": "",
            "Track 1": "",
        }
        self.markers = {12: {"color": "Blue", "name": "Review", "note": "Check", "duration": 1}}
        self.flags = ["Blue"]

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.unique_id

    def GetMediaId(self):
        return f"media-{self.unique_id}"

    def GetMetadata(self, key=""):
        if key:
            return self.metadata.get(key, "")
        return dict(self.metadata)

    def SetMetadata(self, *args):
        if len(args) == 1 and isinstance(args[0], dict):
            self.metadata.update(args[0])
        elif len(args) == 2:
            self.metadata[args[0]] = args[1]
        return True

    def GetThirdPartyMetadata(self, key=""):
        if key:
            return self.third_party_metadata.get(key, "")
        return dict(self.third_party_metadata)

    def SetThirdPartyMetadata(self, *args):
        if len(args) == 2:
            self.third_party_metadata[args[0]] = args[1]
        return True

    def GetClipProperty(self, key=""):
        if key:
            return self.properties.get(key, "")
        return dict(self.properties)

    def SetClipProperty(self, *args):
        return True

    def GetClipColor(self):
        return "Blue"

    def SetClipColor(self, color):
        return True

    def GetMarkers(self):
        return dict(self.markers)

    def AddMarker(self, frame, color, name, note, duration, custom_data):
        self.markers[frame] = {
            "color": color,
            "name": name,
            "note": note,
            "duration": duration,
            "customData": custom_data,
        }
        return True

    def GetFlagList(self):
        return list(self.flags)

    def AddFlag(self, color):
        self.flags.append(color)
        return True

    def GetAudioMapping(self):
        return {"channels": 2}

    def GetMarkInOut(self):
        return {"video": {"in": 10, "out": 40}}

    def SetMarkInOut(self, mark_in, mark_out, mark_type="all"):
        self.mark = {"in": mark_in, "out": mark_out, "type": mark_type}
        return True


class FolderStub:
    def __init__(self, name="Master", unique_id="folder-1", clips=None, subfolders=None):
        self.name = name
        self.unique_id = unique_id
        self.clips = clips or []
        self.subfolders = subfolders or []

    def GetName(self):
        return self.name

    def GetUniqueId(self):
        return self.unique_id

    def GetClipList(self):
        return list(self.clips)

    def GetSubFolderList(self):
        return list(self.subfolders)

    def GetIsFolderStale(self):
        return False


class MediaPoolStub:
    def __init__(self):
        self.clip = MediaPoolItemStub()
        self.root = FolderStub(clips=[self.clip], subfolders=[FolderStub(name="Ingest")])

    def GetUniqueId(self):
        return "media-pool-1"

    def GetRootFolder(self):
        return self.root

    def GetCurrentFolder(self):
        return self.root

    def GetSelectedClips(self):
        return [self.clip]

    def ImportMedia(self, paths):
        return []

    def RelinkClips(self, clips, folder_path):
        return True

    def UnlinkClips(self, clips):
        return True

    def MoveClips(self, clips, folder):
        return True


class MediaPoolIngestProbeTest(unittest.TestCase):
    def test_ingest_capabilities_names_supported_boundaries(self):
        capabilities = _media_pool_ingest_capabilities()

        self.assertIn("imports", capabilities["supported"])
        self.assertIn("clip_properties", capabilities["partially_supported"])
        self.assertIn("source_media_mutation", capabilities["unsupported"])

    def test_media_pool_item_probe_captures_properties_and_methods(self):
        probe = _media_pool_item_probe(MediaPoolItemStub())

        self.assertEqual(probe["summary"]["id"], "clip-1")
        self.assertEqual(probe["summary"]["file_path"], "/tmp/synthetic_ingest_source.mov")
        self.assertTrue(probe["methods"]["GetMetadata"])
        self.assertEqual(probe["known_clip_properties"]["FPS"]["value"], "24")
        self.assertEqual(probe["clip_color"], "Blue")
        self.assertEqual(probe["flags"], ["Blue"])

    def test_media_pool_probe_summarizes_root_and_selection(self):
        probe = _media_pool_probe(MediaPoolStub(), {"depth": 1})

        self.assertEqual(probe["media_pool_id"], "media-pool-1")
        self.assertEqual(probe["root"]["clip_count"], 1)
        self.assertEqual(probe["root"]["subfolder_count"], 1)
        self.assertEqual(probe["selected_clips"][0]["id"], "clip-1")

    def test_probe_ingest_items_supports_selected_items(self):
        probe = _media_pool_probe_ingest_items(MediaPoolStub(), {"selected": True})

        self.assertEqual(probe["count"], 1)
        self.assertEqual(probe["items"][0]["summary"]["name"], "synthetic_ingest_source.mov")

    def test_probe_ingest_items_requires_source(self):
        result = _media_pool_probe_ingest_items(MediaPoolStub(), {})

        self.assertIn("error", result)

    def test_safe_import_sequence_validates_existing_frames(self):
        mp = MediaPoolStub()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for index in range(1, 4):
                (base / f"frame_{index:03d}.png").write_bytes(b"png")

            result = _safe_import_sequence(
                mp,
                {
                    "pattern": str(base / "frame_%03d.png"),
                    "start_index": 1,
                    "end_index": 3,
                    "dry_run": True,
                },
            )

        self.assertTrue(result["success"])
        self.assertEqual(result["would_import"][0]["StartIndex"], 1)
        self.assertEqual(result["would_import"][0]["EndIndex"], 3)

    def test_safe_import_sequence_reports_missing_frames(self):
        mp = MediaPoolStub()
        with tempfile.TemporaryDirectory() as tmp:
            pattern = str(Path(tmp) / "frame_%03d.png")
            result = _safe_import_sequence(mp, {"pattern": pattern, "start_index": 1, "end_index": 3})

        self.assertIn("error", result)
        self.assertIn("Missing sequence frames", (result["error"].get("message","") if isinstance(result["error"], dict) else result["error"]))

    def test_normalize_metadata_dry_run_reports_target_keys(self):
        result = _normalize_metadata(
            MediaPoolStub().root,
            MediaPoolStub(),
            {"selected": True, "metadata": {"Comments": "Ready"}, "third_party_metadata": {"review": "approved"}, "dry_run": True},
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["metadata_keys"], ["Comments"])
        self.assertEqual(result["results"][0]["third_party_keys"], ["review"])

    def test_copy_metadata_to_targets(self):
        mp = MediaPoolStub()
        target = MediaPoolItemStub(unique_id="clip-2")
        mp.root.clips.append(target)

        result = _copy_metadata(mp.root, {"source_clip_id": "clip-1", "target_clip_ids": ["clip-2"]})

        self.assertTrue(result["success"])
        self.assertEqual(target.metadata["Camera #"], "A")
        self.assertEqual(target.third_party_metadata["review_status"], "approved")

    def test_probe_clip_properties_selected(self):
        mp = MediaPoolStub()
        result = _probe_clip_properties(mp.root, mp, {"selected": True})

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["known_clip_properties"]["FPS"]["value"], "24")

    def test_metadata_field_inventory_separates_metadata_and_panel_fields(self):
        mp = MediaPoolStub()
        result = _metadata_field_inventory(mp.root, mp, {"selected": True})

        self.assertTrue(result["success"])
        item = result["items"][0]
        self.assertEqual(item["metadata"]["fields"], ["Camera #"])
        self.assertIn("Description", item["clip_properties"]["fields"])
        self.assertIn("Shot & Scene", [group["name"] for group in item["metadata_panel_groups"]])
        self.assertEqual(
            item["analysis_writeback_fields"]["default"][0],
            {
                "field": "Description",
                "in_get_metadata": False,
                "in_clip_properties": True,
                "inferred_ui_group": "Shot & Scene",
                "clip_property_key": "Description",
            },
        )
        keywords = item["analysis_writeback_fields"]["default"][2]
        self.assertEqual(keywords["field"], "Keywords")
        self.assertTrue(keywords["in_clip_properties"])
        self.assertEqual(keywords["clip_property_key"], "Keyword")
        roll_card = item["analysis_writeback_fields"]["optional_slate"][4]
        self.assertEqual(roll_card["field"], "Roll/Card")
        self.assertEqual(roll_card["metadata_write_key"], "Roll Card #")

    def test_metadata_write_aliases_match_resolve_writeback_surface(self):
        self.assertEqual(_metadata_write_field_for_field("Keyword"), "Keywords")
        self.assertEqual(_metadata_write_field_for_field("Keywords"), "Keywords")
        self.assertEqual(_metadata_write_field_for_field("Roll/Card"), "Roll Card #")

    def test_metadata_panel_group_hints_cover_audio_tracks(self):
        self.assertEqual(_metadata_panel_group_for_field("Track 12"), "Audio Tracks")
        self.assertEqual(_metadata_panel_group_for_field("Audio Notes"), "Audio")
        self.assertEqual(_metadata_panel_group_for_field("Director Reviewed"), "Reviewed By")

    def test_set_clip_marks_dry_run(self):
        mp = MediaPoolStub()
        result = _set_clip_marks(mp.root, mp, {"selected": True, "mark_in": 2, "mark_out": 8, "dry_run": True})

        self.assertTrue(result["success"])
        self.assertEqual(result["results"][0]["mark_in"], 2)
        self.assertEqual(result["results"][0]["mark_out"], 8)

    def test_copy_clip_annotations_dry_run(self):
        mp = MediaPoolStub()
        target = MediaPoolItemStub(unique_id="clip-2")
        mp.root.clips.append(target)

        result = _copy_clip_annotations(mp.root, {"source_clip_id": "clip-1", "target_clip_ids": ["clip-2"], "dry_run": True})

        self.assertTrue(result["success"])
        self.assertEqual(result["results"][0]["markers"], 1)
        self.assertEqual(result["results"][0]["flags"], 1)


if __name__ == "__main__":
    unittest.main()
