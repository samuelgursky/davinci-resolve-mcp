"""Read-only evidence-based film handoff preflight."""
from fractions import Fraction
import math
from pathlib import Path
import wave

from .film_stem_return import audit_package, digest, file_hash, integer


def _bound_file(path, expected):
    if not isinstance(path,str) or not Path(path).is_absolute(): raise ValueError('Evidence path must be absolute')
    if not isinstance(expected,str) or len(expected)!=64 or file_hash(path)!=expected:
        raise ValueError('Evidence file hash changed or is invalid')


def _tail_peak(path, sample_rate):
    with wave.open(path,'rb') as wav:
        count=min(wav.getnframes(),max(1,sample_rate//100))
        wav.setpos(wav.getnframes()-count)
        raw=wav.readframes(count)
    return max((abs(int.from_bytes(raw[i:i+3],'little',signed=True))/8388608
                for i in range(0,len(raw),3)),default=0.0)


def _tempo(evidence):
    if not isinstance(evidence,dict) or evidence.get('schema')!='film-tempo/v1' or evidence.get('status')!='ok':
        raise ValueError('Expected successful film-tempo/v1 receipt')
    _bound_file(evidence.get('source_set_path'),evidence.get('source_sha256'))
    maps=evidence.get('tempo_map_beats')
    if not isinstance(maps,list) or not 1<=len(maps)<=1000: raise ValueError('Invalid tempo map')
    last=-1
    for i,row in enumerate(maps):
        beat,bpm=row['start_beats'],row['bpm']
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (beat,bpm)):
            raise ValueError('Invalid tempo values')
        if (i==0 and beat!=0) or beat<=last or not 20<=bpm<=999: raise ValueError('Invalid tempo steps')
        last=beat
    return {'source_set_path':evidence['source_set_path'],'source_sha256':evidence['source_sha256'],
            'segments':len(maps),'mode':evidence.get('mode'),'saved_only':True}


def _calibration(evidence,configuration):
    if not isinstance(evidence,dict) or evidence.get('schema')!='film-calibration/v1' or evidence.get('status')!='measured':
        raise ValueError('Expected measured film-calibration/v1 receipt')
    if not isinstance(configuration,dict): raise ValueError('Current capture_profile is required with calibration evidence')
    if digest(configuration)!=evidence.get('configuration_sha256'): raise ValueError('Capture configuration changed')
    if digest({k:v for k,v in evidence.items() if k!='profile_sha256'})!=evidence.get('profile_sha256'):
        raise ValueError('Calibration receipt hash mismatch')
    probe=evidence['probe']; _bound_file(probe['path'],probe['sha256'])
    captures=evidence.get('captures')
    if not isinstance(captures,list) or not 2<=len(captures)<=5: raise ValueError('Expected 2-5 calibration captures')
    for capture in captures: _bound_file(capture['path'],capture['sha256'])
    offset=evidence.get('offset_samples')
    if type(offset) is not int or evidence.get('correction_samples')!=-offset: raise ValueError('Invalid offset evidence')
    return {'profile_sha256':evidence['profile_sha256'],'offset_samples':offset,
            'configuration_matches':True,'files_match':True,'dsp_remeasured_here':False,
            'absolute_picture_alignment_verified':False}


def preflight(cue_sheet, snapshot, missing_media, *, delivery_dir=None,
              expected_picture_fingerprint=None, tempo_evidence=None,
              calibration_evidence=None, capture_profile=None, loudness_path=None,
              target_lufs=None, true_peak_max=None):
    """Evidence integrity is not proof of current hardware settings or creative approval."""
    if not isinstance(cue_sheet,dict) or cue_sheet.get('schema')!='film-cues/v1':
        raise ValueError('Expected film-cues/v1')
    rate=cue_sheet['frame_rate']
    fps=Fraction(integer(rate['numerator'],'numerator',1),integer(rate['denominator'],'denominator',1))
    if not 1<=fps<=240: raise ValueError('Invalid frame rate')
    start=integer(snapshot['start_frame'],'timeline start')
    end=integer(snapshot['end_frame'],'timeline end')
    if end<start or not snapshot.get('id'): raise ValueError('Invalid picture snapshot')
    if cue_sheet['timeline']['start_frame']!=start: raise ValueError('Cue/snapshot origin mismatch')
    cues=cue_sheet.get('cues')
    if not isinstance(cues,list) or len(cues)>10000: raise ValueError('Invalid cue collection')
    ranges=[]; ids=set()
    for cue in cues:
        if not isinstance(cue,dict) or not isinstance(cue.get('id'),str) or not cue['id'] or cue['id'] in ids:
            raise ValueError('Cue IDs must be unique nonempty strings')
        ids.add(cue['id'])
        a=integer(cue.get('start_frame'),'cue frame'); b=a+integer(cue.get('duration_frames'),'cue duration',1)
        ranges.append((cue['id'],a,b))
    # Audio changes do not invalidate the picture baseline. This is structural
    # identity, not a rendered-image/grade/effects/content hash.
    picture={'id':snapshot['id'],'name':snapshot.get('name'),'start_frame':start,
             'frame_rate':rate,'video':snapshot.get('tracks',{}).get('video'),
             'cues':cue_sheet}
    fingerprint=digest(picture); checks=[]
    def add(name,status,detail=None,**evidence):
        checks.append({'name':name,'status':status,'detail':detail,**evidence})
    add('picture_version','unknown' if expected_picture_fingerprint is None else
        ('pass' if fingerprint==expected_picture_fingerprint else 'fail'),
        'Structural picture/cue fingerprint; not rendered-image, grade or source-content verification.',
        fingerprint=fingerprint)
    video_items=[item for track in snapshot.get('tracks',{}).get('video',{}).get('tracks',[])
                 for item in track.get('items',[])]
    video_ends=[item.get('end') for item in video_items]
    picture_end=max(video_ends) if video_ends and all(type(v) is int and v>=start for v in video_ends) else None
    out=[identity for identity,a,b in ranges if picture_end is not None and b>picture_end-start]
    add('cue_range','unknown' if picture_end is None else 'fail' if out else ('pass' if ranges else 'warn'),
        'Cues checked against video extent, not the potentially longer audio timeline.',
        out_of_range=out,picture_end_frame=picture_end)
    if not isinstance(missing_media,dict): add('missing_media','unknown','Media inspection unavailable')
    else:
        missing=integer(missing_media.get('missing_count'),'missing_count')
        unlinked=integer(missing_media.get('unlinked_count'),'unlinked_count')
        present=integer(missing_media.get('present_count'),'present_count')
        unknown=sum(1 for kind in snapshot.get('tracks',{}).values()
                    for track in kind.get('tracks',[]) for item in track.get('items',[])
                    if not item.get('file_path'))
        add('missing_media','fail' if missing else 'unknown' if unknown else ('warn' if unlinked or not present else 'pass'),
            'Source presence from the existing conform inspection; no relink performed.',
            missing_count=missing,unlinked_count=unlinked,present_count=present,unknown_count=unknown)
    audit=None
    if delivery_dir is None: add('delivery','unknown','No film-stems/v1 package supplied')
    else:
        try:
            audit=audit_package(delivery_dir); m=audit['manifest']
            delivered_fps=Fraction(m['frame_rate']['numerator'],m['frame_rate']['denominator'])
            if delivered_fps!=fps: raise ValueError('Delivery/picture frame rates differ')
            uncovered=[identity for identity,a,b in ranges if a<m['start_frame'] or b>m['end_frame']]
            peaks=[{'name':s['name'],'last_10ms_peak':_tail_peak(s['path'],m['sample_rate'])} for s in audit['stems']]
            for stem in audit['stems']: _bound_file(stem['path'],stem['sha256'])
            add('delivery','pass','PCM24 headers, counts and hashes verified',package_id=audit['package_id'])
            add('stem_cue_coverage','warn' if uncovered else 'pass',
                'Cue coverage against package body; cue markers may include non-music notes.',uncovered_cues=uncovered)
            add('tails','warn' if any(p['last_10ms_peak']>.001 for p in peaks) else 'pass',
                'Measured endpoint quietness, not proof that the chosen reverb tail is artistically complete.',
                tail_frames=m['tail_frames'],measurements=peaks)
        except (ValueError,OSError,KeyError,TypeError,EOFError,wave.Error) as exc:
            add('delivery','fail',str(exc))
    if tempo_evidence is None: add('tempo','unknown','No saved-set tempo evidence supplied')
    else:
        try: add('tempo','warn','Saved receipt/file checked; live state, map origin and unsaved tempo remain unverified.',**_tempo(tempo_evidence))
        except (ValueError,OSError,KeyError,TypeError) as exc: add('tempo','fail',str(exc))
    if calibration_evidence is None: add('capture_alignment','unknown','No calibration evidence supplied')
    else:
        try: add('capture_alignment','warn','Receipt/config/file integrity checked. Use Ableton validate_capture_calibration for fresh DSP; actual settings and absolute picture origin remain caller-verified.',**_calibration(calibration_evidence,capture_profile))
        except (ValueError,OSError,KeyError,TypeError) as exc: add('capture_alignment','fail',str(exc))
    if loudness_path is None: add('loudness','unknown','No final mix or stem selected for measurement')
    else:
        try:
            from .mix_plan import measure
            path=str(Path(loudness_path).resolve(strict=True)); sha=file_hash(path)
            measured=measure(path); _bound_file(path,sha)
            values=[measured.get('integrated_lufs'),measured.get('true_peak_dbtp')]
            if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
                raise ValueError('No finite loudness/true-peak reading')
            if target_lufs is None or true_peak_max is None:
                status='unknown'; detail='Measured; explicit delivery targets required for pass/fail'
            else:
                if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (target_lufs,true_peak_max)):
                    raise ValueError('Loudness targets must be finite numbers')
                status='pass' if abs(values[0]-target_lufs)<=.5 and values[1]<=true_peak_max else 'fail'
                detail='Whole-file integrated LUFS ±0.5 and true peak; not dialogue-gated measurement'
            add('loudness',status,detail,measurement=measured,sha256=sha)
        except Exception as exc: add('loudness','unknown','Measurement unavailable: '+str(exc))
    states={c['status'] for c in checks}
    status='failed' if 'fail' in states else 'incomplete' if 'unknown' in states else 'warnings' if 'warn' in states else 'passed'
    return {'schema':'film-preflight/v1','status':status,'picture_fingerprint':fingerprint,
            'timeline_id':snapshot['id'],'checks':checks,'mutations':0,
            'creative_approval_verified':False}
