"""Native alignment with strict ID resolution before any timeline mutation."""
from src.utils.resolve211_multicam import resolve_constant

OPTIONS = {
    'SyncUsing': ('AUTO_ALIGN_CLIPS_USING_TIMECODE','AUTO_ALIGN_CLIPS_USING_WAVEFORM'),
    'UseTrack': ('AUTO_ALIGN_CLIPS_WAVEFORM_TRACK_MIX','AUTO_ALIGN_CLIPS_WAVEFORM_TRACK_AUTOMATIC'),
}


def auto_align(r, timeline, item_ids, options):
    if not isinstance(item_ids,list) or not item_ids or any(not isinstance(i,str) or not i for i in item_ids):
        return {'error':'item_ids must be a non-empty list of timeline item unique IDs'}
    if len(set(item_ids))!=len(item_ids):
        return {'error':'item_ids must not contain duplicates'}
    if not isinstance(options,dict) or set(options)-set(OPTIONS):
        return {'error':'options must contain only SyncUsing and/or UseTrack'}
    normalized={}
    for key,value in options.items():
        normalized[key],error=resolve_constant(r,value,OPTIONS[key])
        if error:
            return {'error':key+': '+error}
    wanted=set(item_ids)
    found={}
    for track_type in ('video','audio'):
        for index in range(1,timeline.GetTrackCount(track_type)+1):
            for item in timeline.GetItemListInTrack(track_type,index) or []:
                uid=item.GetUniqueId()
                if uid in wanted:
                    found[uid]=item
    if any(uid not in found for uid in item_ids):
        return {'error':'One or more item_ids were not found in current video/audio tracks; no alignment performed'}
    return {'success':bool(timeline.AutoAlignClips([found[uid] for uid in item_ids],normalized))}
