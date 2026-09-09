"""Scratch-only alignment/render fixture; synthetic speech-red/blue.mov required.
Usage: python tests/live_resolve211_alignment.py OUTPUT_DIR
Creates timelines and renders in Codex Alignment Validation 20260909.
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
    assert p.GetName()=='Codex Alignment Validation 20260909'
    mp=p.GetMediaPool();clips={c.GetName():c for c in mp.GetRootFolder().GetClipList()}
    output=Path(sys.argv[1]).resolve();output.mkdir(parents=True,exist_ok=True)
    rows=[]
    for mode,target,initial in [('timecode',24,48),('waveform',0,24)]:
        for layer in ['manual','compound','granular']:
            t=mp.CreateEmptyTimeline(mode+' '+layer);t.SetStartTimecode('00:00:00:00');t.AddTrack('video');t.AddTrack('audio','mono')
            items=mp.AppendToTimeline([{'mediaPoolItem':clips[name],'trackIndex':i+1,'recordFrame':0 if i==0 else target if layer=='manual' else initial} for i,name in enumerate(['speech-red.mov','speech-blue.mov'])])
            all_items=[x for kind in ['video','audio'] for index in range(1,t.GetTrackCount(kind)+1) for x in t.GetItemListInTrack(kind,index)]
            before=[x.GetStart() for x in all_items]
            if layer!='manual':
                options={'SyncUsing':'AUTO_ALIGN_CLIPS_USING_'+mode.upper()}
                if mode=='waveform':options['UseTrack']='AUTO_ALIGN_CLIPS_WAVEFORM_TRACK_MIX'
                ids=[x.GetUniqueId() for x in all_items]
                result=s.timeline('auto_align_clips',{'item_ids':ids,'options':options}) if layer=='compound' else g.auto_align_timeline_clips(ids,options)
                assert result.get('success'),result
            after=[x.GetStart() for x in all_items]
            assert after==[0,target,0,target],after
            assert p.SetCurrentRenderFormatAndCodec('mov','ProRes422');assert p.SetCurrentRenderMode(1)
            assert p.SetRenderSettings({'TargetDir':str(output),'CustomName':mode+'-'+layer,'SelectAllFrames':True,'ExportVideo':True,'ExportAudio':True,'AudioCodec':'lpcm','AudioBitDepth':24,'AudioSampleRate':48000})
            job=p.AddRenderJob();assert job and p.StartRendering([job]);deadline=time.monotonic()+120
            while p.IsRenderingInProgress() and time.monotonic()<deadline:time.sleep(1)
            status=p.GetRenderJobStatus(job);assert status['JobStatus']=='Complete',status
            rows.append({'mode':mode,'layer':layer,'before':before,'after':after,'render':status})
    assert r.GetProjectManager().SaveProject()
    (output/'receipt.json').write_text(json.dumps({'version':r.GetVersionString(),'results':rows},indent=2),encoding='utf-8')
    print(json.dumps(rows,indent=2))


if __name__=='__main__':main()
