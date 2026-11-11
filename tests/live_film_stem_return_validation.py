"""Real MCP stem placement in an owned temporary timeline; never saves the project."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid
import wave

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import src.server as server
from test_film_stem_return import package


async def run(ntsc=False):
    resolve=server.get_resolve()
    project=resolve.GetProjectManager().GetCurrentProject()
    if not project: raise RuntimeError('No current project')
    previous=project.GetCurrentTimeline()
    if not previous: raise RuntimeError('No current timeline to restore')
    previous_id=previous.GetUniqueId()
    pool=project.GetMediaPool()
    scratch=Path(tempfile.mkdtemp(prefix='film-stem-return-'))
    manifest=package(scratch)
    if ntsc:
        with wave.open(str(scratch/'music.wav'),'wb') as wav:
            wav.setnchannels(2); wav.setsampwidth(3); wav.setframerate(48000)
            wav.writeframes(b'\0'*48048*6)
        manifest.update(frame_rate={'numerator':30000,'denominator':1001},
            start_frame=30,end_frame=54,tail_frames=6,start_sample=48048,end_sample=96096,
            sample_count=48048,body_sample_count=38438,tail_sample_count=9610)
        manifest['stems'][0]['sha256']=hashlib.sha256((scratch/'music.wav').read_bytes()).hexdigest()
        (scratch/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    name='_val_film_return_'+uuid.uuid4().hex[:10]
    tl=pool.CreateEmptyTimeline(name)
    if not tl: raise RuntimeError('Could not create disposable timeline')
    owned_id=tl.GetUniqueId()
    completed=False
    try:
        assert project.SetCurrentTimeline(tl)
        assert tl.SetSetting('useCustomSettings','1')
        assert tl.SetSetting('timelineFrameRate','29.97' if ntsc else '24')
        assert tl.SetStartTimecode('01:00:00:00')
        root=Path(__file__).resolve().parents[1]
        params=StdioServerParameters(command=sys.executable,args=[str(root/'src/server.py')],
            cwd=str(root),env=dict(os.environ,DAVINCI_RESOLVE_MCP_UPDATE_CHECK='0'))
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()
                async def call(arguments):
                    result=await client.call_tool('timeline',{'action':'film_stems_return','params':arguments})
                    assert not result.isError,result
                    data=result.structuredContent or json.loads(next(c.text for c in result.content if c.type=='text'))
                    return data.get('result',data)
                preview=await call({'delivery_dir':str(scratch)})
                assert preview['status']=='preview',preview
                result=await call({'delivery_dir':str(scratch),'preview':False,
                    'expected_timeline_id':owned_id,'expected_fingerprint':preview['fingerprint']})
                assert result['status']=='imported',result
                again=await call({'delivery_dir':str(scratch)})
                assert again['status']=='already_present',again
                expected_frame=tl.GetStartFrame()+manifest['start_frame']
                assert result['record_frame']==expected_frame
                completed=True
                print(json.dumps({'status':'passed','transport':'real MCP stdio',
                    'record_frame':expected_frame,'duration_frames':result['duration_frames'],
                    'frame_rate':manifest['frame_rate'],'repeat':'already_present',
                    'source_media':'synthetic PCM24 only','scratch':str(scratch),'project_saved':False}))
    finally:
        restored=project.SetCurrentTimeline(previous)
        assert restored and project.GetCurrentTimeline().GetUniqueId()==previous_id,'Original timeline restore failed'
        if completed and tl.GetUniqueId()==owned_id and tl.GetName()==name:
            # Only this invocation's verified disposable timeline. Media fixtures remain in scratch.
            assert pool.DeleteTimelines([tl]),'Disposable timeline cleanup failed'
        elif not completed:
            print(json.dumps({'retained_probe_timeline':name,'scratch':str(scratch)}))


if __name__=='__main__': asyncio.run(run('--ntsc' in sys.argv))
