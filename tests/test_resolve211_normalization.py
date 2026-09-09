import unittest
from types import SimpleNamespace
from unittest.mock import patch
import src.server as s
from src.granular import resolve_211 as g
from src.utils import destructive_hook
from src.utils.execution_lifecycle import classify_operation_risk


class NormalizeTests(unittest.TestCase):
    def fixture(self,value=True):
        calls=[];a=SimpleNamespace(GetUniqueId=lambda:'a');b=SimpleNamespace(GetUniqueId=lambda:'b')
        def normalize(items,options):calls.append((items,options));return value
        t=SimpleNamespace(GetTrackCount=lambda kind:1,GetItemListInTrack=lambda kind,index:[a,b],NormalizeAudioLevel=normalize)
        r=SimpleNamespace(NORMALIZE_AUDIO_SET_LEVEL_RELATIVE=0.0)
        return r,t,a,b,calls

    def invoke(self,layer,r,t,ids,options,dry=False):
        p=SimpleNamespace(GetCurrentTimeline=lambda:t)
        with patch.object(s,'_check',return_value=(None,p,None)),patch.object(s,'get_resolve',return_value=r),patch.object(g,'_get_timeline',return_value=(p,t,None)),patch.object(g,'get_resolve',return_value=r):
            if layer=='compound':return s.timeline('normalize_audio_level',{'item_ids':ids,'options':options,'dry_run':dry})
            return g.normalize_timeline_audio_level(ids,options)

    def test_values_and_order_preserved(self):
        for layer in ['compound','granular']:
            r,t,a,b,calls=self.fixture()
            result=self.invoke(layer,r,t,['b','a'],{'normalizationMode':'EBU R128','targetLoudness':-23.0,'targetLevel':-1.0,'setLevelMode':'NORMALIZE_AUDIO_SET_LEVEL_RELATIVE'})
            self.assertTrue(result['success']);self.assertEqual(calls,[([b,a],{'normalizationMode':'EBU R128','targetLoudness':-23.0,'targetLevel':-1.0,'setLevelMode':0.0})])

    def test_bad_inputs_refuse_before_write(self):
        for layer in ['compound','granular']:
            for ids,options in [([],{}),(['a','a'],{}),(['a','missing'],{}),(['a'],{'targetLevel':True}),(['a'],{'targetLoudness':float('nan')}),(['a'],{'setLevelMode':'invalid'}),(['a'],{'normalizationMode':''}),(['a'],{'bad':1})]:
                r,t,a,b,calls=self.fixture()
                self.assertIn('error',self.invoke(layer,r,t,ids,options));self.assertEqual(calls,[])

    def test_native_false_and_missing_method(self):
        for layer in ['compound','granular']:
            r,t,a,b,calls=self.fixture(False)
            self.assertIs(self.invoke(layer,r,t,['a'],{})['success'],False)
            t.NormalizeAudioLevel=None
            self.assertIn('error',self.invoke(layer,r,t,['a'],{}))

    def test_rated_write_and_dry_run_refusal(self):
        self.assertTrue(destructive_hook.is_destructive('timeline','normalize_audio_level'))
        risk=classify_operation_risk('timeline','normalize_audio_level',{}).to_dict()
        self.assertTrue(risk['recognised']);self.assertTrue(risk['destructive'])
        r,t,a,b,calls=self.fixture()
        self.assertIn('error',self.invoke('compound',r,t,['a'],{},dry=True));self.assertEqual(calls,[])
