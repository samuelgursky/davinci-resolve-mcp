import unittest
from tests import test_resolve211_read_controls as readers
from src.utils import destructive_hook
from src.utils.execution_lifecycle import classify_operation_risk

CASES=[('timeline','set_output_blanking','SetOutputBlanking','set_timeline_output_blanking',{'options':{'Top':36,'Bottom':324,'Left':64,'Right':576}}),('timeline_item','set_output_blanking','SetOutputBlanking','set_timeline_item_output_blanking',{'options':{'Top':72.0}}),('timeline_item','set_use_timeline_for_output_blanking','SetUseTimelineForOutputBlanking','set_timeline_item_use_timeline_for_output_blanking',{'use_timeline':False})]


class BlankingTests(unittest.TestCase):
    def both(self,case,params,native):
        tool,action,method,name,_=case;h=readers.ReadControlTests()
        return h.run_compound(tool,action,params,native),h.run_granular(name,params,native)

    def test_exact_values_forwarded_and_native_failure_preserved(self):
        for case in CASES:
            for value in [True,False]:
                n=readers.NativeStub(case[2],value)
                self.assertTrue(all(r['success'] is value for r in self.both(case,case[4],n)))
                self.assertEqual(n.calls,[(case[2],(next(iter(case[4].values())),))]*2)

    def test_missing_native_methods_refuse(self):
        for case in CASES:
            n=readers.NativeStub(case[2],True,available=False)
            self.assertTrue(all(case[2] in str(r['error']) for r in self.both(case,case[4],n)))
            self.assertEqual(n.calls,[])

    def test_invalid_options_never_write(self):
        for case in CASES:
            key=next(iter(case[4]))
            values=[None,{},[],{'Top':1.5},{'Top':True},{'top':1}] if key=='options' else [None,0,1,'false']
            for value in values:
                n=readers.NativeStub(case[2],True)
                self.assertTrue(all('error' in r for r in self.both(case,{key:value},n)))
                self.assertEqual(n.calls,[])

    def test_all_actions_are_rated_writes_and_dry_run_refuses(self):
        for case in CASES:
            tool,action,method,_,params=case
            self.assertTrue(destructive_hook.is_destructive(tool,action))
            risk=classify_operation_risk(tool,action,params).to_dict()
            self.assertTrue(risk['recognised']);self.assertTrue(risk['destructive'])
            n=readers.NativeStub(method,True)
            result=readers.ReadControlTests().run_compound(tool,action,dict(params,dry_run=True),n)
            self.assertIn('error',result);self.assertEqual(n.calls,[])
