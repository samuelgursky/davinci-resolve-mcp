import unittest
from unittest.mock import patch
from types import SimpleNamespace
import src.server as s
from src.granular import resolve_211 as g
from src.utils import destructive_hook
from src.utils.execution_lifecycle import classify_operation_risk


class AlignmentTests(unittest.TestCase):
    def fixture(self,value=True):
        calls=[]
        a=SimpleNamespace(GetUniqueId=lambda:'a');b=SimpleNamespace(GetUniqueId=lambda:'b')
        def align(items,options): calls.append((items,options)); return value
        t=SimpleNamespace(GetTrackCount=lambda kind:1,GetItemListInTrack=lambda kind,index:[a] if kind=='video' else [b],AutoAlignClips=align)
        r=SimpleNamespace(AUTO_ALIGN_CLIPS_USING_WAVEFORM=0.0,AUTO_ALIGN_CLIPS_WAVEFORM_TRACK_MIX=-2.0)
        return r,t,a,b,calls

    def invoke(self,layer,r,t,ids,options,dry=False):
        p=SimpleNamespace(GetCurrentTimeline=lambda:t)
        with patch.object(s,'_check',return_value=(None,p,None)),patch.object(s,'get_resolve',return_value=r),patch.object(g,'_get_timeline',return_value=(p,t,None)),patch.object(g,'get_resolve',return_value=r):
            if layer=='compound':
                return s.timeline('auto_align_clips',{'item_ids':ids,'options':options,'dry_run':dry})
            return g.auto_align_timeline_clips(ids,options)

    def test_order_and_explicit_scope_preserved(self):
        for layer in ['compound','granular']:
            r,t,a,b,calls=self.fixture()
            result=self.invoke(layer,r,t,['b','a'],{'SyncUsing':'AUTO_ALIGN_CLIPS_USING_WAVEFORM','UseTrack':'AUTO_ALIGN_CLIPS_WAVEFORM_TRACK_MIX'})
            self.assertTrue(result['success']);self.assertEqual(calls,[([b,a],{'SyncUsing':0.0,'UseTrack':-2.0})])

    def test_invalid_or_missing_inputs_never_write(self):
        for layer in ['compound','granular']:
            for ids,options in [([],{}),(['a','a'],{}),(['a','missing'],{}),(['a'],{'SyncUsing':True}),(['a'],{'UseTrack':1.5}),(['a'],{'bad':1}),(['a'],{'SyncUsing':'bogus'})]:
                r,t,a,b,calls=self.fixture()
                self.assertIn('error',self.invoke(layer,r,t,ids,options));self.assertEqual(calls,[])

    def test_native_false_and_absent_method(self):
        for layer in ['compound','granular']:
            r,t,a,b,calls=self.fixture(False)
            self.assertIs(self.invoke(layer,r,t,['a','b'],{})['success'],False)
            t.AutoAlignClips=None
            self.assertIn('error',self.invoke(layer,r,t,['a','b'],{}))

    def test_rated_write_and_dry_run_refusal(self):
        self.assertTrue(destructive_hook.is_destructive('timeline','auto_align_clips'))
        risk=classify_operation_risk('timeline','auto_align_clips',{}).to_dict()
        self.assertTrue(risk['recognised']);self.assertTrue(risk['destructive'])
        r,t,a,b,calls=self.fixture()
        self.assertIn('error',self.invoke('compound',r,t,['a','b'],{},dry=True));self.assertEqual(calls,[])
