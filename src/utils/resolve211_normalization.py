"""Native normalization: validate explicit audio-item selection before writes."""
import math


def finite_number(value):
    try:
        return type(value) in (int,float) and math.isfinite(value)
    except OverflowError:
        return False


def normalize_audio(r, timeline, item_ids, options):
    if not isinstance(item_ids,list) or not item_ids or any(not isinstance(i,str) or not i for i in item_ids):
        return {'error':'item_ids must be a non-empty list of audio timeline item unique IDs'}
    if len(set(item_ids))!=len(item_ids):
        return {'error':'item_ids must not contain duplicates'}
    if not isinstance(options,dict) or set(options)-{'normalizationMode','targetLevel','targetLoudness','setLevelMode'}:
        return {'error':'Unknown normalization options or non-dictionary options'}
    normalized=dict(options)
    for key,value in options.items():
        if key=='normalizationMode':
            if not isinstance(value,str) or not value.strip():
                return {'error':'normalizationMode must be a non-empty native mode name'}
        elif key=='setLevelMode':
            if isinstance(value,str):
                if value not in ('NORMALIZE_AUDIO_SET_LEVEL_RELATIVE','NORMALIZE_AUDIO_SET_LEVEL_INDEPENDENT'):
                    return {'error':'Unknown setLevelMode constant'}
                value=getattr(r,value,None)
            if not finite_number(value) or int(value)!=value:
                return {'error':'setLevelMode must be a documented constant name or integral native value'}
            normalized[key]=value
        elif not finite_number(value):
            return {'error':key+' must be a finite number'}
    wanted=set(item_ids);found={}
    for index in range(1,timeline.GetTrackCount('audio')+1):
        for item in timeline.GetItemListInTrack('audio',index) or []:
            uid=item.GetUniqueId()
            if uid in wanted:
                found[uid]=item
    if any(uid not in found for uid in item_ids):
        return {'error':'One or more IDs were not found on audio tracks; no normalization performed'}
    return {'success':bool(timeline.NormalizeAudioLevel([found[uid] for uid in item_ids],normalized))}
