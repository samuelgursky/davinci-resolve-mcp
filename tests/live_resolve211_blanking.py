"""Scratch-only pixel-coordinate and inheritance fixture.
Usage: python tests/live_resolve211_blanking.py OUTPUT_DIR
Requires Codex Blanking Validation 20260909 and one synthetic red.mov video clip.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    import src.server as s
    from src.granular import resolve_211 as g
    r=s.get_resolve();p=r.GetProjectManager().GetCurrentProject()
    assert p.GetName()=='Codex Blanking Validation 20260909'
    t=p.GetCurrentTimeline();items=t.GetItemListInTrack('video',1)
    assert len(items)==1 and items[0].GetName()=='red.mov'
    i=items[0];output=Path(sys.argv[1]).resolve();output.mkdir(parents=True,exist_ok=True)
    rows=[]
    full={'Top':0,'Bottom':360,'Left':0,'Right':640}
    timeline_rect={'Top':36,'Bottom':324,'Left':64,'Right':576}
    clip_rect={'Top':72,'Bottom':288,'Left':128,'Right':512}
    for layer in ['compound','granular']:
        timeline_set=lambda options:s.timeline('set_output_blanking',{'options':options}) if layer=='compound' else g.set_timeline_output_blanking(options)
        clip_set=lambda options:s.timeline_item('set_output_blanking',{'options':options}) if layer=='compound' else g.set_timeline_item_output_blanking(options)
        inherit=lambda value:s.timeline_item('set_use_timeline_for_output_blanking',{'use_timeline':value}) if layer=='compound' else g.set_timeline_item_use_timeline_for_output_blanking(value)
        def export(phase):
            assert t.SetCurrentTimecode('00:00:02:00')
            assert p.ExportCurrentFrameAsStill(str(output/(layer+'-'+phase+'.png')))
        assert inherit(True)['success'];assert timeline_set(full)['success'];export('full')
        assert timeline_set(timeline_rect)['success'];export('timeline')
        refused=clip_set(clip_rect);assert refused['success'] is False and i.GetUseTimelineForOutputBlanking() is True
        assert inherit(False)['success'];assert clip_set(clip_rect)['success'];export('clip')
        assert i.GetOutputBlanking()==clip_rect
        assert inherit(True)['success'];export('restored-inheritance')
        rows.append({'layer':layer,'timeline':t.GetOutputBlanking(),'inherited_clip':i.GetOutputBlanking(),'refused_while_inherited':refused['success'] is False})
    assert t.SetOutputBlanking(full);assert i.SetUseTimelineForOutputBlanking(True)
    assert r.GetProjectManager().SaveProject()
    (output/'receipt.json').write_text(json.dumps({'version':r.GetVersionString(),'results':rows},indent=2),encoding='utf-8')
    print(json.dumps(rows,indent=2))


if __name__=='__main__':main()
