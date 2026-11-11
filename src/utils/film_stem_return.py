"""Verified film-stems/v1 return into new Resolve audio tracks."""
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import wave

from .film_cues import _rate


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): result.update(block)
    return result.hexdigest()


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum or value > 2**53:
        raise ValueError(f'{name} must be an integer in [{minimum}, 2**53]')
    return value


def _round(value):
    return (2*value.numerator + value.denominator)//(2*value.denominator)


def audit_package(delivery_dir):
    """Read-only independent manifest, PCM WAV and SHA verification."""
    root = Path(delivery_dir).resolve(strict=True)
    path = root/'manifest.json'
    with path.open('rb') as stream: raw = stream.read(8*1024*1024+1)
    if len(raw) > 8*1024*1024: raise ValueError('Manifest too large')
    m = json.loads(raw)
    if not isinstance(m, dict) or m.get('schema') != 'film-stems/v1' or m.get('subtype') != 'PCM_24':
        raise ValueError('Expected film-stems/v1 PCM_24 manifest')
    rate = m.get('frame_rate')
    if not isinstance(rate, dict): raise ValueError('Invalid frame_rate')
    fps = Fraction(integer(rate.get('numerator'), 'numerator', 1),
                   integer(rate.get('denominator'), 'denominator', 1))
    if not 1 <= fps <= 240: raise ValueError('Unsupported frame rate')
    start, end, tail = (integer(m.get(k), k) for k in ('start_frame','end_frame','tail_frames'))
    sr = integer(m.get('sample_rate'), 'sample_rate', 8000)
    if end <= start or sr > 384000: raise ValueError('Invalid range/sample rate')
    a, b, c = (_round(Fraction(frame*sr, 1)/fps) for frame in (start,end,end+tail))
    expected = dict(start_sample=a, end_sample=c, sample_count=c-a,
                    body_sample_count=b-a, tail_sample_count=c-b)
    for key, value in expected.items():
        if integer(m.get(key), key) != value: raise ValueError(f'Clock mismatch: {key}')
    stems = m.get('stems')
    if not isinstance(stems, list) or not 1 <= len(stems) <= 64: raise ValueError('Expected 1-64 stems')
    seen, rows = set(), []
    for stem in stems:
        if not isinstance(stem, dict): raise ValueError('Stem must be an object')
        name = stem.get('name')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', name):
            raise ValueError('Invalid stem name')
        if name.casefold() in seen or stem.get('file') != name+'.wav': raise ValueError('Duplicate or unsafe filename')
        seen.add(name.casefold())
        target = root/stem['file']
        if target.is_symlink() or target.resolve(strict=True).parent != root or target.is_reserved():
            raise ValueError('Stem path escapes delivery directory')
        sha = file_hash(target)
        if sha != stem.get('sha256'): raise ValueError(f'{name}: SHA-256 mismatch')
        with wave.open(str(target), 'rb') as wav:
            channels = integer(stem.get('channels'), 'channels', 1)
            if (channels not in (1,2) or wav.getnchannels() != channels or wav.getsampwidth()!=3
                or wav.getframerate()!=sr or wav.getnframes()!=c-a or wav.getcomptype()!='NONE'):
                raise ValueError(f'{name}: WAV format/count mismatch')
            left = c-a
            while left:
                count = min(left,65536)
                if len(wav.readframes(count)) != count*channels*3: raise ValueError('Truncated WAV')
                left -= count
        if file_hash(target) != sha: raise ValueError('Stem changed during audit')
        rows.append({'name':name,'path':str(target),'channels':channels,'sha256':sha,
                     'tail_not_quiet':stem.get('tail_not_quiet')})
    return {'schema':'film-stem-audit/v1','status':'passed','package_id':digest(m),
            'manifest':m,'stems':rows,'delivery_dir':str(root),
            'capture_alignment_verified':False}


def _path(value):
    # realpath, not abspath: audit_package resolves the delivery root, so stem
    # paths come back with symlinks resolved (/private/var/... on macOS), while
    # Resolve reports the path it was handed (/var/...). Comparing unresolved
    # forms never matched, so a previous import went undetected.
    return os.path.normcase(os.path.realpath(value)) if value else ''


def _number(value):
    if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value):
        raise ValueError('Unreadable timeline coordinate')
    return value


def _snapshot(tl):
    identity = tl.GetUniqueId()
    if not isinstance(identity,str) or not identity: raise ValueError('Timeline identity unavailable')
    tracks = []
    count = integer(tl.GetTrackCount('audio'),'audio tracks')
    for index in range(1,count+1):
        items = tl.GetItemListInTrack('audio',index)
        if not isinstance(items,list): raise ValueError('Audio track enumeration unavailable')
        rows = []
        for item in items:
            media = item.GetMediaPoolItem()
            rows.append({'id':item.GetUniqueId(),'path':_path(media.GetClipProperty('File Path')) if media else '',
                         'start':_number(item.GetStart(True)), 'duration':_number(item.GetDuration(True))})
        tracks.append({'index':index,'name':tl.GetTrackName('audio',index),'items':rows})
    return {'id':identity,'name':tl.GetName(),'start_frame':integer(tl.GetStartFrame(),'timeline start'),
            'fps':str(_rate(tl.GetSetting('timelineFrameRate'))),'tracks':tracks}


def prepare_return(project, delivery_dir, preview=True, expected_timeline_id=None,
                   expected_fingerprint=None):
    if type(preview) is not bool: raise ValueError('preview must be boolean')
    if not preview and (not expected_timeline_id or not expected_fingerprint):
        raise ValueError('Apply requires expected_timeline_id and preview fingerprint')
    audit = audit_package(delivery_dir)
    m = audit['manifest']; tl = project.GetCurrentTimeline()
    if not tl: raise ValueError('No current timeline')
    snapshot = _snapshot(tl)
    fps = Fraction(m['frame_rate']['numerator'],m['frame_rate']['denominator'])
    if Fraction(snapshot['fps']) != fps: raise ValueError('Delivery/timeline frame rate mismatch')
    record = snapshot['start_frame']+m['start_frame']
    duration = m['end_frame']+m['tail_frames']-m['start_frame']
    tolerance = float(fps/m['sample_rate']) + 1e-8
    names = [f"FILM_{audit['package_id'][:12]}_{s['name']}" for s in audit['stems']]
    present = []
    for stem,name in zip(audit['stems'],names):
        matches = [(track,item) for track in snapshot['tracks'] for item in track['items']
                   if item['path']==_path(stem['path'])]
        if matches:
            if len(matches)!=1: raise ValueError('Duplicate stem instances; manual review required')
            track,item = matches[0]
            if (track['name']!=name or abs(item['start']-record)>tolerance
                or abs(item['duration']-duration)>tolerance):
                raise ValueError('Existing stem has conflicting placement or track')
            present.append(name)
        elif any(t['name']==name for t in snapshot['tracks']):
            raise ValueError('Target track name already exists without matching stem')
    if present and len(present)!=len(names): raise ValueError('Partial previous import; manual review required')
    result = {'status':'already_present' if present else 'preview',
        'schema':'film-stem-return/v1','timeline_id':snapshot['id'],
        'package_id':audit['package_id'],'record_frame':record,'duration_frames':duration,
        'track_names':names,'fingerprint':digest({'audit':audit,'timeline':snapshot}),
        'sample_boundary_rounding':'nearest sample; timeline placement at the requested picture frame',
        'capture_alignment_verified':False}
    if not preview and (snapshot['id']!=expected_timeline_id or result['fingerprint']!=expected_fingerprint):
        raise ValueError('Preview is stale or target timeline changed; preview again')
    if preview or present: return result
    created, imported = [], []
    partially_created_unknown = False
    def same_target():
        current = project.GetCurrentTimeline()
        if not current or current.GetUniqueId()!=snapshot['id']: raise ValueError('Active timeline changed')
    try:
        same_target()
        pool = project.GetMediaPool()
        # ImportMedia may mutate the pool before raising or returning partial handles.
        # Keep every readable receipt; an empty receipt list does not prove no import.
        partially_created_unknown = True
        media = pool.ImportMedia([s['path'] for s in audit['stems']])
        by_path = {}
        if isinstance(media, list):
            for item in media:
                try:
                    path = item.GetClipProperty('File Path')
                    if not isinstance(path, str) or not path:
                        continue
                    imported.append(path)
                    by_path[_path(path)] = item
                except Exception:
                    # One unusable handle must not hide receipts for other imports.
                    continue
        if not isinstance(media,list) or len(media)!=len(names): raise ValueError('Media import incomplete')
        if len(by_path)!=len(media): raise ValueError('Media import receipts incomplete')
        partially_created_unknown = False
        source_rates = {}
        for stem in audit['stems']:
            item = by_path.get(_path(stem['path']))
            if not item: raise ValueError('Imported media paths differ from package')
            source_rates[stem['path']] = _rate(item.GetClipProperty('FPS'))
        if _snapshot(tl)!=snapshot: raise ValueError('Timeline changed during media import')
        for stem,name in zip(audit['stems'],names):
            same_target()
            if file_hash(stem['path'])!=stem['sha256']: raise ValueError('Stem changed after preview')
            index = tl.GetTrackCount('audio')+1
            if not tl.AddTrack('audio',{'audioType':'mono' if stem['channels']==1 else 'stereo'}):
                raise ValueError('AddTrack failed')
            created.append({'index':index,'name':name})
            if tl.GetTrackCount('audio')!=index or tl.GetItemListInTrack('audio',index):
                raise ValueError('New track was not empty or track list changed')
            if not tl.SetTrackName('audio',index,name): raise ValueError('SetTrackName failed')
            same_target()
            # WAV source coordinates use the media item's imported FPS, not the timeline FPS.
            source_duration = Fraction(duration,1)/fps * source_rates[stem['path']]
            # Audio endFrame is an exclusive endpoint on the verified Resolve build.
            # Video's common inclusive-end convention would lose one source frame.
            returned = pool.AppendToTimeline([{'mediaPoolItem':by_path[_path(stem['path'])],
                'startFrame':0,'endFrame':float(source_duration),'recordFrame':record,
                'trackIndex':index,'mediaType':2}])
            if not returned: raise ValueError('AppendToTimeline returned no items')
            readback = _snapshot(tl)['tracks'][index-1]
            if readback['name']!=name or len(readback['items'])!=1: raise ValueError('Track readback mismatch')
            row = readback['items'][0]
            if (row['path']!=_path(stem['path']) or abs(row['start']-record)>tolerance
                or abs(row['duration']-duration)>tolerance): raise ValueError('Placement readback mismatch')
        same_target()
        return {**result,'status':'imported','created_tracks':created,'verified':True}
    except Exception as exc:
        return {**result,'status':'partial_failure','error':str(exc),'created_tracks':created,
                'imported_media':imported,'rollback_attempted':False,
                'partially_created_unknown':partially_created_unknown,
                'warning':'Inspect created tracks/media before retrying; nothing automatically deleted.'}
