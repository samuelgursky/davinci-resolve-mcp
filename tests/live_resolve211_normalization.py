"""Scratch-only normalization meter fixtures, using synthetic tone.wav and quiet.wav.
Usage: python tests/live_resolve211_normalization.py OUTPUT_DIR
Requires Codex Normalization Validation 20260909. Creates timelines/renders.
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
    assert p.GetName()=='Codex Normalization Validation 20260909'
    mp=p.GetMediaPool();clips={c.GetName():c for c in mp.GetRootFolder().GetClipList()}
    output=Path(sys.argv[1]).resolve();output.mkdir(parents=True,exist_ok=True)
    rows=[]
    cases=[('relative',['tone.wav','quiet.wav'],{'normalizationMode':'Sample Peak Program','targetLevel':-6.0,'setLevelMode':'NORMALIZE_AUDIO_SET_LEVEL_RELATIVE'}),('independent',['tone.wav','quiet.wav'],{'normalizationMode':'Sample Peak Program','targetLevel':-6.0,'setLevelMode':'NORMALIZE_AUDIO_SET_LEVEL_INDEPENDENT'}),('loudness',['tone.wav'],{'normalizationMode':'EBU R128','targetLoudness':-23.0,'targetLevel':-1.0})]
    for case,names,options in cases:
        for layer in ['compound','granular']:
            t=mp.CreateEmptyTimeline(case+' '+layer);assert t.SetStartTimecode('00:00:00:00')
            assert mp.AppendToTimeline([clips[name] for name in names])
            items=t.GetItemListInTrack('audio',1);ids=[x.GetUniqueId() for x in items]
            result=s.timeline('normalize_audio_level',{'item_ids':ids,'options':options}) if layer=='compound' else g.normalize_timeline_audio_level(ids,options)
            assert result.get('success'),result
            row={'case':case,'layer':layer,'volume_db':[x.GetProperties().get('AudioVolume') for x in items]}
            assert p.SetCurrentRenderMode(1)
            assert p.SetRenderSettings({'TargetDir':str(output),'CustomName':case+'-'+layer,'SelectAllFrames':True,'ExportVideo':False,'ExportAudio':True,'AudioFormat':'wav','AudioCodec':'lpcm','AudioBitDepth':24,'AudioSampleRate':48000})
            job=p.AddRenderJob();assert job and p.StartRendering([job]);deadline=time.monotonic()+120
            while p.IsRenderingInProgress() and time.monotonic()<deadline:time.sleep(1)
            status=p.GetRenderJobStatus(job);assert status['JobStatus']=='Complete',status
            row['render']=status;rows.append(row)
    assert r.GetProjectManager().SaveProject()
    (output/'receipt.json').write_text(json.dumps({'version':r.GetVersionString(),'results':rows},indent=2),encoding='utf-8')
    print(json.dumps(rows,indent=2))


if __name__=='__main__':main()
