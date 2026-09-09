"""Run only in Codex Multicam Validation 20260909 with synthetic red.mov/blue.mov.
Usage: python tests/live_resolve211_multicam.py OUTPUT_DIR
Creates native multicams, renders before/after flattening through both wrappers.
"""
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    import src.server as s
    from src.granular import resolve_211 as g
    r=s.get_resolve();p=r.GetProjectManager().GetCurrentProject()
    assert p.GetName()=='Codex Multicam Validation 20260909'
    mp=p.GetMediaPool()
    clips={c.GetName():c for c in mp.GetRootFolder().GetClipList()}
    ids=[clips[n].GetUniqueId() for n in ['red.mov','blue.mov']]
    output=Path(sys.argv[1]).resolve();output.mkdir(parents=True,exist_ok=True)
    receipt={'version':r.GetVersionString(),'results':[]}
    for layer in ['compound','granular']:
        opts={'name':'Wrapper '+layer,'startTimecode':'00:00:00:00','frameRate':24.0,'angleSyncMode':'MULTICAM_ANGLE_SYNC_TIMECODE','createBinForSourceClips':False}
        created=s.media_pool('create_multicam_clip',{'clip_ids':ids,'options':opts}) if layer=='compound' else g.create_multicam_clip(ids,opts)
        assert created.get('success') and len(created['clips'])==1,created
        mc=s._find_clip(mp.GetRootFolder(),created['clips'][0]['id'])
        assert mc.GetClipProperty('Type')=='Multicam'
        t=mp.CreateEmptyTimeline('Wrapper '+layer+' render');assert t.SetStartTimecode('00:00:00:00')
        assert mp.AppendToTimeline([mc])
        row={'layer':layer,'created_type':'Multicam','renders':[]}
        for phase in ['before','flattened']:
            if phase=='flattened':
                result=s.timeline_item('flatten_multicam',{}) if layer=='compound' else g.flatten_timeline_item_multicam()
                assert result.get('success'),result
                item=t.GetItemListInTrack('video',1)[0]
                assert item.GetMediaPoolItem().GetClipProperty('Type')=='Video'
                assert item.GetStart()==0 and item.GetDuration()==144
            assert p.SetCurrentRenderFormatAndCodec('mov','ProRes422')
            assert p.SetCurrentRenderMode(1)
            assert p.SetRenderSettings({'TargetDir':str(output),'CustomName':layer+'-'+phase,'SelectAllFrames':True,'ExportVideo':True,'ExportAudio':False})
            job=p.AddRenderJob();assert job and p.StartRendering([job])
            deadline=time.monotonic()+120
            while p.IsRenderingInProgress() and time.monotonic()<deadline:
                time.sleep(1)
            status=p.GetRenderJobStatus(job);assert status['JobStatus']=='Complete',status
            row['renders'].append({'phase':phase,'status':status})
        receipt['results'].append(row)
    assert r.GetProjectManager().SaveProject()
    (output/'wrapper-receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':
    main()
