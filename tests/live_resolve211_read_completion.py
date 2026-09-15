"""Compare 21.1 transcription/type reads through both community interfaces.

Run in a disposable LOCAL project whose current timeline's first video item is
the synthetic camera clip, after native transcription reports "Transcribed".
Originally measured in a since-deleted 2026-09-09 project; re-run in "Testbed".
Usage: python tests/live_resolve211_read_completion.py RECEIPT_PATH
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import src.server as s
    from src.granular import resolve_211 as g

    r = s.get_resolve()
    p = r.GetProjectManager().GetCurrentProject()
    assert r.GetProjectManager().GetCurrentDatabase().get("DbName") == "Local Database"
    clip = p.GetCurrentTimeline().GetItemListInTrack("video", 1)[0].GetMediaPoolItem()
    clip_id = clip.GetUniqueId()
    native_transcription = clip.GetTranscription(False)
    assert native_transcription and native_transcription.get("segments")
    compound_transcription = s.media_pool_item("get_transcription", {
        "clip_id": clip_id, "include_words": True,
        "use_nested_clip_transcription": False,
    })
    granular_transcription = g.get_media_pool_item_transcription(clip_id, False)
    assert compound_transcription["source"] == "get_transcription"
    assert compound_transcription["segments"] == native_transcription["segments"]
    assert granular_transcription["transcription"] == native_transcription

    native_type = p.GetCurrentTimeline().GetItemListInTrack("video", 1)[0].GetType()
    compound_type = s.timeline_item("get_type", {})
    granular_type = g.get_timeline_item_type()
    assert native_type == compound_type["type"] == granular_type["type"] == "video"

    receipt = {
        "version": r.GetVersionString(),
        "clip_id": clip_id,
        "transcription_status": clip.GetClipProperty("Transcription Status"),
        "language": native_transcription.get("language"),
        "segment_count": len(native_transcription["segments"]),
        "word_count": sum(len(segment.get("words") or [])
                          for segment in native_transcription["segments"]),
        "transcription_exact_across_native_and_both_interfaces": True,
        "timeline_item_type": native_type,
        "type_exact_across_native_and_both_interfaces": True,
    }
    path = Path(sys.argv[1]).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
