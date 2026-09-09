"""Read-only validation of the 21.1 discovery actions in both server layers.

Run from the repo root with a project/timeline containing a video clip open:
    python tests/live_resolve211_read_controls.py

No projects, preferences, render jobs or clip properties are changed. The
receipt excludes user project, clip and preset names. Compound operation-log
metadata is checked separately from the domain payload shared by both layers.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import src.server as s
    from src.granular import resolve_211 as g

    r = s.get_resolve()
    project = r.GetProjectManager().GetCurrentProject()
    if project is None or project.GetCurrentTimeline() is None:
        raise SystemExit('Open a project and timeline first.')
    timeline = project.GetCurrentTimeline()
    items = timeline.GetItemListInTrack('video', 1) or []
    index = next((k for k, item in enumerate(items) if item.GetMediaPoolItem() is not None), None)
    if index is None:
        raise SystemExit('An ordinary video clip on video track 1 is required.')
    location = {'track_type': 'video', 'track_index': 1, 'item_index': index}
    cases = [
        ('resolve_control', 'is_studio', g.is_resolve_studio, {}, bool),
        ('resolve_control', 'get_keyboard_presets', g.get_keyboard_presets, {}, list),
        ('resolve_control', 'get_current_keyboard_preset', g.get_current_keyboard_preset, {}, str),
        ('project_settings', 'get_project_settings_presets', g.get_project_settings_presets, {}, list),
        ('render', 'get_audio_formats', g.get_audio_render_formats, {}, dict),
        ('render', 'get_audio_codecs', g.get_audio_render_codecs, {'format': 'wav'}, dict),
        ('timeline', 'get_normalize_audio_modes', g.get_normalize_audio_modes, {}, list),
        ('timeline', 'get_output_blanking', g.get_timeline_output_blanking, {}, dict),
        ('timeline_item', 'get_speed', g.get_timeline_item_speed, location, dict),
        ('timeline_item', 'get_fades', g.get_timeline_item_fades, location, dict),
        ('timeline_item', 'get_output_blanking', g.get_timeline_item_output_blanking, location, dict),
        ('timeline_item', 'get_use_timeline_for_output_blanking', g.get_timeline_item_use_timeline_for_output_blanking, location, bool),
    ]
    rows = []
    for tool, action, reader, params, expected in cases:
        compound = getattr(s, tool)(action, params)
        granular = reader(**params)
        payload = {k: v for k, v in compound.items() if k != '_operation'}
        row = {
            'action': tool + '.' + action,
            'same_payload': payload == granular,
            'shape_valid': len(granular) == 1 and isinstance(next(iter(granular.values())), expected),
            'error': compound.get('error') or granular.get('error'),
        }
        rows.append(row)
    print(json.dumps({'version': r.GetVersionString(), 'results': rows, 'mutators_invoked': False}, indent=2))
    assert all(row['same_payload'] and row['shape_valid'] and not row['error'] for row in rows), rows


if __name__ == '__main__':
    main()
