import copy
import unittest
from unittest.mock import patch

import src.server as server
from tests._envelope_helpers import domain_payload


class FilmServerTests(unittest.TestCase):
    def test_missing_comparison_parameters_are_refused_offline(self):
        sheet={'schema':'film-cues/v1','frame_rate':{'numerator':24,'denominator':1},
            'timeline':{'name':'Film','start_frame':86400,'start_timecode':'01:00:00:00'},
            'cues':[]}
        for missing, params in (
            ('before', {'after':sheet}),
            ('after', {'before':sheet}),
            ('after_snapshot', {'before':sheet,'after':sheet,'before_snapshot':{}}),
            ('before_snapshot', {'before':sheet,'after':sheet,'after_snapshot':{}}),
        ):
            with self.subTest(missing=missing):
                original=copy.deepcopy(params)
                with patch.object(server,'_get_tl',side_effect=AssertionError('Offline comparison called Live')):
                    result=server.timeline_markers.__wrapped__('compare_cue_sheets',params)
                self.assertIn('error',result)
                self.assertIn(missing,result['error']['message'])
                self.assertNotIn('picture_impact',result)
                self.assertEqual(params,original)

    def test_unreadable_snapshot_keeps_unknown_picture_impact_offline(self):
        sheet={'schema':'film-cues/v1','frame_rate':{'numerator':24,'denominator':1},
            'timeline':{'name':'Film','start_frame':86400,'start_timecode':'01:00:00:00'},
            'cues':[{'id':'music-1','name':'Music','start_frame':24,'duration_frames':12}]}
        valid={'id':'tl','name':'Film','start_frame':86400,'end_frame':86448,'tracks':{'video':{
            'track_count':1,'tracks':[{'track_index':1,'item_count':1,'items':[{
                'start':86400,'end':86448,'source_start':0,'source_end':48,'source_fps':24,
                'file_path':'synthetic.mov','name':'Shot'}]}]}}}
        for side in ('before', 'after'):
            for items in ([None], None):
                with self.subTest(side=side, items=items):
                    params={'before':sheet,'after':sheet,
                            'before_snapshot':copy.deepcopy(valid),'after_snapshot':copy.deepcopy(valid)}
                    params[side+'_snapshot']['tracks']['video']['tracks'][0]['items']=items
                    original=copy.deepcopy(params)
                    with patch.object(server,'_get_tl',side_effect=AssertionError('Offline comparison called Live')):
                        # Bypass lifecycle telemetry to keep the probe entirely offline.
                        result=server.timeline_markers.__wrapped__('compare_cue_sheets',params)
                    self.assertNotIn('error',result)
                    self.assertEqual(result['changes'],[])
                    impact=result['picture_impact']
                    self.assertEqual(impact['status'],'unknown')
                    self.assertEqual(impact[side+'_affected_cue_ids'],['music-1'])
                    self.assertTrue(impact['unknowns'])
                    self.assertTrue(result['requires_human_review'])
                    self.assertEqual(impact['editorial_comparison']['status'],'unknown')
                    self.assertNotIn('match',impact['editorial_comparison'])
                    self.assertEqual(params,original)

    def test_offline_picture_edit_affects_a_cue_even_when_markers_do_not_move(self):
        sheet={'schema':'film-cues/v1','frame_rate':{'numerator':24,'denominator':1},
            'timeline':{'name':'Film','start_frame':86400,'start_timecode':'01:00:00:00'},
            'cues':[{'id':'music-1','name':'Music','start_frame':24,'duration_frames':12}]}
        old={'id':'tl','name':'Film','start_frame':86400,'end_frame':86448,'tracks':{'video':{
            'track_count':1,'tracks':[{'track_index':1,'item_count':1,'items':[{
                'start':86400,'end':86448,'source_start':0,'source_end':48,'source_fps':24,
                'file_path':__file__,'name':'Shot'}]}]}}}
        new=copy.deepcopy(old); new['tracks']['video']['tracks'][0]['items'][0]['source_start']=12
        with patch.object(server,'_get_tl',side_effect=AssertionError('Offline comparison called Live')):
            result=domain_payload(server.timeline_markers('compare_cue_sheets',{
                'before':sheet,'after':sheet,'before_snapshot':old,'after_snapshot':new}))
        self.assertEqual(result['changes'],[])
        self.assertEqual(result['picture_impact']['after_affected_cue_ids'],['music-1'])
        self.assertTrue(result['requires_human_review'])

    def test_snapshot_is_a_consistent_read_only_baseline(self):
        from tests.test_film_preflight import FilmPreflightTests
        fixture=FilmPreflightTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        class Project:
            def GetCurrentTimeline(self): return object()
        with patch.object(server,'_check',return_value=(None,Project(),None)), \
             patch.object(server,'_timeline_conform_snapshot',return_value=fixture.snapshot), \
             patch.object(server,'_export_film_cue_sheet',return_value=fixture.sheet):
            result=domain_payload(server.timeline('film_snapshot'))
        self.assertEqual(result['schema'],'film-snapshot/v1')
        self.assertEqual(result['cue_sheet'],fixture.sheet)
        self.assertEqual(result['snapshot'],fixture.snapshot)
        self.assertEqual(result['picture_fingerprint'],fixture.run_check()['picture_fingerprint'])
        self.assertEqual(result['mutations'],0)
