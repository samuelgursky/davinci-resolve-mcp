"""Render synthetic native transitions through both wrappers in a named scratch project.

Usage: python tests/live_resolve211_transitions.py OUTPUT_DIR
Requires Codex Native Transition Validation 20260909, 24 fps / 640x360,
and synthetic red.mov and blue.mov (six seconds each) in its root bin.
Creates disposable timelines and renders; never use production media.
"""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    import src.server as s
    from src.granular import resolve_211 as g
    r=s.get_resolve()
    p=r.GetProjectManager().GetCurrentProject()
    assert p.GetName()=='Codex Native Transition Validation 20260909'
    mp=p.GetMediaPool()
    clips={c.GetName():c for c in mp.GetRootFolder().GetClipList() if c.GetClipProperty("Type") != "Timeline"}
    assert set(clips)=={'red.mov','blue.mov'}
    output=Path(sys.argv[1]).resolve()
    output.mkdir(parents=True,exist_ok=True)
    receipt={'version':r.GetVersionString(),'results':[]}
    options={'type':'Cross Dissolve','category':'simple','position':'end','alignment':'center','duration':24}
    for layer,call in [('compound',lambda:s.timeline_item('add_transition',{'options':options})),('granular',lambda:g.add_timeline_item_transition(options))]:
        for handles in (True,False):
            t=mp.CreateEmptyTimeline('Native '+layer+(' handles' if handles else ' no handles'))
            assert t.SetStartTimecode('00:00:00:00')
            items=mp.AppendToTimeline([{'mediaPoolItem':clips[n],'startFrame':24 if handles else 0,'endFrame':95 if handles else 144,'mediaType':1} for n in ('red.mov','blue.mov')])
            before=[(i.GetStart(),i.GetEnd()) for i in items]
            row={'layer':layer,'handles':handles,'before':before,'source_handles':{'outgoing_right':items[0].GetRightOffset(),'incoming_left':items[1].GetLeftOffset()}}
            result=call()
            row['result']={k:v for k,v in result.items() if k not in ('_operation','security')}
            assert result.get('success') is handles, result
            assert [(i.GetStart(),i.GetEnd()) for i in items]==before
            if handles:
                cut=items[1].GetStart()
                assert result['transition']['start']==cut-12
                assert result['transition']['end']==cut+12
                assert result['transition']['duration']==24
                assert p.SetCurrentRenderFormatAndCodec('mov','ProRes422')
                assert p.SetCurrentRenderMode(1)
                assert p.SetRenderSettings({'TargetDir':str(output),'CustomName':layer+'-transition','SelectAllFrames':True,'ExportVideo':True,'ExportAudio':False})
                job=p.AddRenderJob()
                assert job and p.StartRendering([job])
                deadline=time.monotonic()+120
                while p.IsRenderingInProgress() and time.monotonic()<deadline:
                    time.sleep(1)
                status=p.GetRenderJobStatus(job)
                row['render']=status
                assert status['JobStatus']=='Complete',status
            receipt['results'].append(row)
    assert r.GetProjectManager().SaveProject()
    (output/'wrapper-receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':
    main()
