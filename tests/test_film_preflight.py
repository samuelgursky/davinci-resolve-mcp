import copy
import json
from pathlib import Path
import tempfile
import unittest

from src.utils.film_preflight import preflight
from tests.test_film_stem_return import package


class FilmPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); package(self.root)
        self.sheet={'schema':'film-cues/v1','frame_rate':{'numerator':24,'denominator':1},
            'timeline':{'name':'Film','start_frame':86400,'start_timecode':'01:00:00:00'},
            'cues':[{'id':'cue1','start_frame':24,'duration_frames':12}]}
        self.snapshot={'id':'tl','name':'Film','start_frame':86400,'end_frame':86500,
            'tracks':{'video':{'tracks':[{'track_index':1,'items':[{'timeline_item_id':'v1',
                'start':86400,'end':86500,'source_start':0,'file_path':'video.mov'}]}]}}}
        self.missing={'missing_count':0,'unlinked_count':0,'present_count':1}
    def run_check(self,**kwargs): return preflight(self.sheet,self.snapshot,self.missing,**kwargs)
    def check(self,result,name): return next(c for c in result['checks'] if c['name']==name)
    def test_absent_evidence_stays_unknown(self):
        result=self.run_check()
        self.assertEqual(result['status'],'incomplete')
        for name in ('picture_version','delivery','tempo','capture_alignment','loudness'):
            self.assertEqual(self.check(result,name)['status'],'unknown')
    def test_bound_picture_and_delivery(self):
        first=self.run_check()
        result=self.run_check(delivery_dir=str(self.root),expected_picture_fingerprint=first['picture_fingerprint'])
        self.assertEqual(self.check(result,'picture_version')['status'],'pass')
        self.assertEqual(self.check(result,'delivery')['status'],'pass')
        self.assertEqual(self.check(result,'stem_cue_coverage')['status'],'pass')
    def test_picture_edit_without_marker_edit_invalidates_fingerprint(self):
        first=self.run_check()['picture_fingerprint']
        self.snapshot['tracks']['video']['tracks'][0]['items'][0]['source_start']=24
        result=self.run_check(expected_picture_fingerprint=first)
        self.assertEqual(self.check(result,'picture_version')['status'],'fail')
    def test_audio_return_does_not_change_picture_fingerprint(self):
        first=self.run_check()['picture_fingerprint']
        self.snapshot['tracks']['audio']={'tracks':[{'items':[{'id':'stem'}]}]}
        self.assertEqual(self.run_check()['picture_fingerprint'],first)
    def test_corrupt_package_does_not_hide_other_checks(self):
        (self.root/'music.wav').write_bytes(b'bad')
        result=self.run_check(delivery_dir=str(self.root))
        self.assertEqual(result['status'],'failed')
        self.assertEqual(self.check(result,'delivery')['status'],'fail')
        self.assertEqual(self.check(result,'missing_media')['status'],'pass')
    def test_missing_media_fails(self):
        self.missing['missing_count']=1
        self.assertEqual(self.check(self.run_check(),'missing_media')['status'],'fail')
    def test_out_of_range_cue_fails(self):
        self.sheet['cues'][0]['start_frame']=120
        self.assertEqual(self.check(self.run_check(),'cue_range')['status'],'fail')
    def test_uncovered_cue_warns(self):
        self.sheet['cues'][0]['start_frame']=2
        self.assertEqual(self.check(self.run_check(delivery_dir=str(self.root)),'stem_cue_coverage')['status'],'warn')
    def test_changed_tempo_file_fails(self):
        path=self.root/'saved.als'; path.write_bytes(b'current')
        evidence={'schema':'film-tempo/v1','status':'ok','source_set_path':str(path),'source_sha256':'0'*64}
        self.assertEqual(self.check(self.run_check(tempo_evidence=evidence),'tempo')['status'],'fail')
    def test_loudness_is_measured_not_taken_from_input(self):
        from unittest.mock import patch
        with patch('src.utils.mix_plan.measure',return_value={'integrated_lufs':-23,'true_peak_dbtp':-2}):
            result=self.run_check(loudness_path=str(self.root/'music.wav'),target_lufs=-23,true_peak_max=-1)
        self.assertEqual(self.check(result,'loudness')['status'],'pass')
    def test_bad_calibration_schema_fails(self):
        result=self.run_check(calibration_evidence={'status':'valid'})
        self.assertEqual(self.check(result,'capture_alignment')['status'],'fail')

    def test_media_pool_identity_without_path_is_not_presence_evidence(self):
        item=self.snapshot['tracks']['video']['tracks'][0]['items'][0]
        item.update(file_path=None,media_pool_item_id='pool-id',media_status=None)
        result=self.run_check()
        self.assertEqual(self.check(result,'missing_media')['status'],'unknown')

    def test_audio_extension_cannot_make_out_of_picture_cues_valid(self):
        self.snapshot['end_frame']=86700
        self.sheet['cues'][0]['start_frame']=120
        self.assertEqual(self.check(self.run_check(),'cue_range')['status'],'fail')

    def test_late_audio_failure_cannot_leave_an_earlier_delivery_pass(self):
        from unittest.mock import patch
        with patch('src.utils.film_preflight._tail_peak',side_effect=ValueError('late WAV failure')):
            result=self.run_check(delivery_dir=str(self.root))
        self.assertEqual([c['status'] for c in result['checks'] if c['name']=='delivery'],['fail'])


if __name__=='__main__': unittest.main()
