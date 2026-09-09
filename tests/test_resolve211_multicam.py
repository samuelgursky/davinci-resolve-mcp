import unittest
from unittest.mock import patch
from types import SimpleNamespace
import src.server as s
from src.granular import resolve_211 as g
from src.utils import destructive_hook
from src.utils.execution_lifecycle import classify_operation_risk


class MulticamTests(unittest.TestCase):
    def fixture(self, result=True):
        calls=[]
        clip=SimpleNamespace(GetUniqueId=lambda:'new',GetName=lambda:'Multicam')
        def create(clips,opts):
            calls.append((clips,opts)); return [clip] if result else []
        native=SimpleNamespace(GetRootFolder=lambda:None,CreateMulticamClip=create,MULTICAM_ANGLE_SYNC_TIMECODE=2.0,FLATTEN_MULTICAM_COPY_GRADE=0.0)
        return native,clip,calls

    def create(self, layer, native, clip, ids, options, missing=False, dry_run=False):
        find=lambda root,cid: None if missing and cid=='bad' else clip
        with patch.object(s,'_get_mp',return_value=(None,None,native,None)),patch.object(s,'get_resolve',return_value=native),patch.object(s,'_find_clip',side_effect=find),patch.object(g,'get_resolve',return_value=native),patch.object(g,'get_current_project',return_value=(None,SimpleNamespace(GetMediaPool=lambda:native))),patch.object(g,'_find_clip_by_id',side_effect=find):
            if layer=='compound':
                return s.media_pool('create_multicam_clip',{'clip_ids':ids,'options':options,'dry_run':dry_run})
            return g.create_multicam_clip(ids,options)

    def test_both_layers_resolve_named_constants_and_preserve_false(self):
        for layer in ['compound','granular']:
            n,c,calls=self.fixture()
            result=self.create(layer,n,c,['a','b'],{'angleSyncMode':'MULTICAM_ANGLE_SYNC_TIMECODE','createBinForSourceClips':False})
            self.assertTrue(result['success']);self.assertEqual(result['clips'],[{'id':'new','name':'Multicam'}])
            self.assertEqual(calls,[([c,c],{'angleSyncMode':2.0,'createBinForSourceClips':False})])

    def test_missing_ids_never_create_partial_multicam(self):
        for layer in ['compound','granular']:
            n,c,calls=self.fixture()
            self.assertIn('error',self.create(layer,n,c,['a','bad'],{},missing=True));self.assertEqual(calls,[])

    def test_malformed_ids_and_options_never_write(self):
        for layer in ['compound','granular']:
            for ids,opts in [([],{}),(['a','a'],{}),(['a'],{'frameRate':True}),(['a'],{'frameRate':float('nan')}),(['a'],{'splitAtGaps':1}),(['a'],{'angleSyncMode':'NO_SUCH_CONSTANT'}),(['a'],{'badKey':1})]:
                n,c,calls=self.fixture()
                self.assertIn('error',self.create(layer,n,c,ids,opts));self.assertEqual(calls,[])

    def test_native_failure_and_missing_method(self):
        for layer in ['compound','granular']:
            n,c,calls=self.fixture(False)
            self.assertFalse(self.create(layer,n,c,['a'],{})['success'])
            n.CreateMulticamClip=None
            self.assertIn('error',self.create(layer,n,c,['a'],{}))

    def test_flatten_both_layers_preserve_native_failure(self):
        for value in [False,True]:
            calls=[]
            def flatten(grade): calls.append(grade); return value
            n=SimpleNamespace(FlattenMulticam=flatten,FLATTEN_MULTICAM_COPY_GRADE=0.0)
            with patch.object(s,'_get_item',return_value=(None,n,None)),patch.object(s,'get_resolve',return_value=n),patch.object(g,'_get_timeline_item',return_value=(n,None)),patch.object(g,'get_resolve',return_value=n):
                self.assertIs(s.timeline_item('flatten_multicam',{})['success'],value)
                self.assertIs(g.flatten_timeline_item_multicam()['success'],value)
                self.assertEqual(calls,[0.0,0.0])

    def test_both_actions_are_registered_rated_writes(self):
        for tool,action in [('media_pool','create_multicam_clip'),('timeline_item','flatten_multicam')]:
            self.assertTrue(destructive_hook.is_destructive(tool,action))
            risk=classify_operation_risk(tool,action,{}).to_dict()
            self.assertTrue(risk['recognised']);self.assertTrue(risk['destructive'])

    def test_creation_dry_run_refuses_before_write(self):
        n,c,calls=self.fixture()
        self.assertIn('error',self.create('compound',n,c,['a'],{},dry_run=True));self.assertEqual(calls,[])
