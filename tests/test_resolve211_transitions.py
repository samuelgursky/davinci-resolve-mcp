"""Native transition payloads and write gates must remain honest."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from tests import test_resolve211_read_controls as readers
from src.granular import resolve_211 as granular
from src.utils import destructive_hook
from src.utils.execution_lifecycle import classify_operation_risk

OPTIONS = {'type':'Cross Dissolve','category':'simple','position':'end','alignment':'center','duration':24}


class NativeTransitionTests(unittest.TestCase):
    def both(self, options, native):
        harness=readers.ReadControlTests()
        return (harness.run_compound('timeline_item','add_transition',{'options':options},native),
                harness.run_granular('add_timeline_item_transition',{'options':options},native))

    def test_actual_span_returned_not_requested_duration(self):
        transition=SimpleNamespace(GetUniqueId=lambda:'id',GetName=lambda:'Cross Dissolve',GetStart=lambda:59,GetEnd=lambda:71,GetDuration=lambda:12)
        native=readers.NativeStub('AddTransition',transition)
        for result in self.both(OPTIONS,native):
            self.assertTrue(result['success'])
            self.assertEqual(result['transition'],{'id':'id','name':'Cross Dissolve','start':59,'end':71,'duration':12})
        self.assertEqual(native.calls,[('AddTransition',(OPTIONS,))]*2)

    def test_native_failure_and_unavailable_method(self):
        for value in (None,False):
            native=readers.NativeStub('AddTransition',value)
            for result in self.both(OPTIONS,native):
                self.assertFalse(result['success'])
                self.assertNotIn('transition',result)
        native=readers.NativeStub('AddTransition',None,available=False)
        self.assertTrue(all('AddTransition' in str(r['error']) for r in self.both(OPTIONS,native)))
        self.assertEqual(native.calls,[])

    def test_malformed_options_never_call_native(self):
        cases=[None,{},dict(OPTIONS,type=' '),dict(OPTIONS,category='invalid'),dict(OPTIONS,position='middle'),dict(OPTIONS,alignment='centre'),dict(OPTIONS,duration=-1),dict(OPTIONS,duration=True),dict(OPTIONS,duration=1.5),dict(OPTIONS,typo=1)]
        for options in cases:
            with self.subTest(options=options):
                native=readers.NativeStub('AddTransition',None)
                self.assertTrue(all('error' in r for r in self.both(options,native)))
                self.assertEqual(native.calls,[])

    def test_optional_duration_is_forwarded_without_inventing_default(self):
        for options in ({k:v for k,v in OPTIONS.items() if k!='duration'},dict(OPTIONS,duration=None)):
            native=readers.NativeStub('AddTransition',None)
            self.both(options,native)
            self.assertEqual(native.calls,[('AddTransition',(options,))]*2)

    def test_invalid_granular_locator_never_looks_up_item(self):
        with patch.object(granular,'_get_timeline_item') as lookup:
            self.assertIn('error',granular.add_timeline_item_transition(OPTIONS,item_index=-1))
            lookup.assert_not_called()

    def test_registered_as_rated_write(self):
        risk=classify_operation_risk('timeline_item','add_transition',{'options':OPTIONS}).to_dict()
        self.assertTrue(destructive_hook.is_destructive('timeline_item','add_transition'))
        self.assertTrue(risk['recognised'])
        self.assertTrue(risk['destructive'])
        self.assertEqual(destructive_hook.risk_level_for_action('timeline_item','add_transition',{}),'medium')

    def test_dry_run_refuses_before_native_write(self):
        native=readers.NativeStub('AddTransition',None)
        result=readers.ReadControlTests().run_compound('timeline_item','add_transition',{'options':OPTIONS,'dry_run':True},native)
        self.assertIn('error',result)
        self.assertEqual(native.calls,[])
