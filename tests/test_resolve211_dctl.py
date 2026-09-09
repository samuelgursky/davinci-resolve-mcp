import unittest
from unittest.mock import patch
from tests import test_resolve211_read_controls as readers
from src.utils.execution_lifecycle import classify_operation_risk
import src.server as s
from src.granular import resolve_211 as g


class NativeDCTLTests(unittest.TestCase):
    def both(self,native,source):
        h=readers.ReadControlTests()
        return h.run_compound('dctl','validate_native',{'source':source},native),h.run_granular('validate_dctl_native',{'source':source},native)

    def test_none_is_success_and_diagnostics_are_verbatim(self):
        source='// café\r\n\t__DEVICE__ float3 transform(...) { return x; }\n'
        for diagnostic in [None,'','DCTL Error: missing return.\n\tline 2\r\n']:
            n=readers.NativeStub('ValidateDCTL',diagnostic)
            for result in self.both(n,source):
                self.assertIs(result['valid'],diagnostic is None)
                self.assertEqual(result['diagnostic'],diagnostic)
                self.assertEqual(result['checker'],'resolve_native')
            self.assertEqual(n.calls,[('ValidateDCTL',(source,))]*2)

    def test_invalid_input_and_absent_method_do_not_validate(self):
        for source in [None,42,{},False]:
            n=readers.NativeStub('ValidateDCTL',None)
            self.assertTrue(all('error' in r for r in self.both(n,source)));self.assertEqual(n.calls,[])
        n=readers.NativeStub('ValidateDCTL',None,available=False)
        self.assertTrue(all('ValidateDCTL' in str(r['error']) for r in self.both(n,'')));self.assertEqual(n.calls,[])

    def test_unexpected_native_type_is_not_claimed_valid(self):
        n=readers.NativeStub('ValidateDCTL',False)
        self.assertTrue(all('error' in r and 'valid' not in r for r in self.both(n,'source')))

    def test_static_validator_route_stays_static(self):
        with patch.object(s,'_validate_dctl_source',return_value={'checker':'static-fixture'}) as static:
            self.assertEqual(s.dctl('validate',{'source':'source'})['checker'],'static-fixture')
            static.assert_called_once_with('source')

    def test_native_validation_is_classified_read_only(self):
        risk=classify_operation_risk('dctl','validate_native',{}).to_dict()
        self.assertTrue(risk['recognised']);self.assertFalse(risk['destructive'])
