"""Native multicam options and all-or-nothing input resolution (not transactionality)."""
import math

ENUMS = {
    'angleSyncMode': tuple('MULTICAM_ANGLE_SYNC_'+v for v in ('IN','OUT','TIMECODE','AUDIO','MARKER')),
    'angleNameMode': tuple('MULTICAM_ANGLE_NAME_'+v for v in ('SEQUENTIAL','ANGLE','CAMERA','CLIP','FILE')),
    'multicamAudioMode': tuple('MULTICAM_AUDIO_'+v for v in ('ADAPTIVE','SOURCE','REFERENCE','ALL')),
    'detectSameCameraClipsMode': ('MULTICAM_DETECT_NONE',) + tuple('MULTICAM_DETECT_BY_'+v for v in ('CAMERA_NUMBER','ANGLE','REEL_NUMBER','REEL_NAME','ROLL_CARD')),
    'channelConfig': ('AUDIO_SYNC_CHANNEL_AUTOMATIC','AUDIO_SYNC_CHANNEL_MIX'),
}
BOOLS = {'splitAtGaps','useFullClipExtents','createBinForSourceClips'}
STRINGS = {'name','startTimecode'}
GRADES = ('FLATTEN_MULTICAM_COPY_GRADE','FLATTEN_MULTICAM_RETAIN_GRADE_FROM_ANGLE')


def resolve_constant(r, value, names):
    if isinstance(value,str):
        if value not in names:
            return None, 'Unknown constant: '+value
        native=getattr(r,value,None)
        if type(native) not in (int,float) or not math.isfinite(native):
            return None, 'Constant unavailable: '+value
        return native,None
    if type(value) in (int,float):
        try:
            if math.isfinite(value) and int(value)==value:
                return value,None
        except OverflowError:
            pass
    return None,'Use a documented constant name or integral native constant value'


def create_multicam(r, mp, clip_ids, options, find_clip):
    if not isinstance(clip_ids,list) or not clip_ids or any(not isinstance(i,str) or not i for i in clip_ids):
        return {'error':'clip_ids must be a non-empty list of media-pool unique IDs'}
    if len(set(clip_ids))!=len(clip_ids):
        return {'error':'clip_ids must not contain duplicates'}
    if not isinstance(options,dict):
        return {'error':'options must be a dictionary'}
    if set(options)-(set(ENUMS)|BOOLS|STRINGS|{'frameRate'}):
        return {'error':'Unknown multicam option'}
    normalized=dict(options)
    for key,value in options.items():
        if key in BOOLS:
            if type(value) is not bool:
                return {'error':key+' must be a boolean'}
        elif key in STRINGS:
            if not isinstance(value,str) or not value.strip():
                return {'error':key+' must be a non-empty string'}
        elif key=='frameRate':
            try:
                valid=type(value) in (int,float) and math.isfinite(value) and value>0
            except OverflowError:
                valid=False
            if not valid:
                return {'error':'frameRate must be a positive finite number'}
        elif key in ENUMS:
            normalized[key],error=resolve_constant(r,value,ENUMS[key])
            if error:
                return {'error':key+': '+error}
    root=mp.GetRootFolder()
    clips=[find_clip(root,i) for i in clip_ids]
    if any(c is None for c in clips):
        return {'error':'One or more clip_ids were not found; no multicam was created'}
    created=mp.CreateMulticamClip(clips,normalized)
    if not created:
        return {'success':False,'clips':[]}
    return {'success':True,'clips':[{'id':c.GetUniqueId(),'name':c.GetName()} for c in created]}
