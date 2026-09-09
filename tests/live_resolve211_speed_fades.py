"""Explicit scratch-only write test; exports frames for independent comparison.

Usage: python tests/live_resolve211_speed_fades.py OUTPUT_DIR
Requires the named disposable project, one six-second synthetic pattern clip,
24 fps, and a timeline beginning at 00:00:00:00. Never run against user media.
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
    assert p.GetName() == 'Codex Speed Fades Validation 20260909'
    t = p.GetCurrentTimeline()
    items = t.GetItemListInTrack('video', 1)
    assert len(items) == 1 and t.GetStartTimecode() == '00:00:00:00'
    item = items[0]
    assert item.GetMediaPoolItem().GetName() == 'test-pattern.mov'
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    original_speed, original_fades = item.GetSpeed(), item.GetFades()
    original_tc = t.GetCurrentTimecode()
    receipt = {'version': r.GetVersionString(), 'writes': [], 'exports': []}

    def export(name, timecode):
        assert t.SetCurrentTimecode(timecode)
        path = output / (name + '.png')
        assert p.ExportCurrentFrameAsStill(str(path))
        receipt['exports'].append(path.name)

    try:
        assert g.set_timeline_item_speed({'Percentage': 100})['success']
        assert g.set_timeline_item_fades({'FadeIn': 0, 'FadeOut': 0})['success']
        export('baseline_1s', '00:00:01:00')
        export('baseline_2s', '00:00:02:00')
        export('baseline_0s', '00:00:00:00')
        export('baseline_end', '00:00:05:23')
        for layer, write in [('compound', lambda o:s.timeline_item('set_speed', {'options':o})), ('granular', g.set_timeline_item_speed)]:
            assert write({'Percentage':50, 'RippleTimeline':False})['success']
            assert item.GetSpeed()['Percentage']==50
            export(layer+'_speed50_2s', '00:00:02:00')
            receipt['writes'].append({'layer':layer,'speed':item.GetSpeed()})
            assert write({'Percentage':100, 'RippleTimeline':False})['success']
        for layer, write in [('compound', lambda o:s.timeline_item('set_fades', {'options':o})), ('granular', g.set_timeline_item_fades)]:
            assert write({'FadeIn':24,'FadeOut':24})['success']
            assert item.GetFades()=={'FadeIn':24.0,'FadeOut':24.0}
            export(layer+'_fade_0s','00:00:00:00')
            export(layer+'_fade_2s','00:00:02:00')
            export(layer+'_fade_end','00:00:05:23')
            receipt['writes'].append({'layer':layer,'fades':item.GetFades()})
            assert write({'FadeIn':0,'FadeOut':0})['success']
    finally:
        assert item.SetSpeed(original_speed)
        assert item.SetFades(original_fades)
        assert t.SetCurrentTimecode(original_tc)
    (output/'receipt.json').write_text(json.dumps(receipt,indent=2), encoding="utf-8")
    print(json.dumps(receipt,indent=2))


if __name__ == '__main__':
    main()
