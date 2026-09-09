import errno
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import src.server as s
from src.granular import resolve_211 as g
from src.utils import resolve211_encryption as helper
from src.utils import destructive_hook
from src.utils.execution_lifecycle import classify_operation_risk


class EncryptionTests(unittest.TestCase):
    def test_both_interfaces_export_and_preserve_source(self):
        for layer in ['compound','granular']:
            with tempfile.TemporaryDirectory() as folder:
                source=Path(folder)/'source.dctl';source.write_text('synthetic source',encoding='utf-8')
                target=Path(folder)/'requested.dctle';calls=[]
                def encrypt(path,options):
                    calls.append((path,options.copy()))
                    (Path(options['OutputFolder'])/'encrypted.dctle').write_bytes(b'encrypted bytes')
                    return True
                native=SimpleNamespace(EncryptDCTL=encrypt)
                with patch.object(s,'get_resolve',return_value=native),patch.object(s,'_resolve_safe_dir',side_effect=lambda p:p),patch.object(g,'get_resolve',return_value=native),patch.object(g,'_resolve_safe_dir',side_effect=lambda p:p):
                    result=s.dctl('encrypt_native',{'input_path':str(source),'output_path':str(target),'expiry':''}) if layer=='compound' else g.encrypt_dctl_native(str(source),str(target),'')
                self.assertTrue(result['success'],result);self.assertEqual(result['path'],str(target))
                self.assertEqual(target.read_bytes(),b'encrypted bytes');self.assertEqual(source.read_text(encoding='utf-8'),'synthetic source')
                self.assertIsNone(calls[0][1]['Expiry']);self.assertEqual(calls[0][1]['Name'],'encrypted')
                self.assertFalse(list(Path(folder).glob('resolve-mcp-dctl-*')))

    def test_existing_and_racing_output_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'in.dctl';source.write_bytes(b'source');target=Path(folder)/'out.dctle';calls=[]
            def encrypt(path,options):
                calls.append(path);target.write_bytes(b'other writer')
                (Path(options['OutputFolder'])/'encrypted.dctle').write_bytes(b'new ciphertext');return True
            native=SimpleNamespace(EncryptDCTL=encrypt)
            result=helper.encrypt_dctl(native,str(source),str(target),None,lambda p:p)
            self.assertFalse(result['success']);self.assertEqual(target.read_bytes(),b'other writer')
            result=helper.encrypt_dctl(native,str(source),str(target),None,lambda p:p)
            self.assertFalse(result['success']);self.assertEqual(len(calls),1)

    def test_no_file_or_native_false_is_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'in.dctl';source.write_bytes(b'source');target=Path(folder)/'out.dctle'
            for value in [True,False]:
                result=helper.encrypt_dctl(SimpleNamespace(EncryptDCTL=lambda *_:value),str(source),str(target),None,lambda p:p)
                self.assertFalse(result['success']);self.assertFalse(target.exists())

    def test_cross_volume_fallback_is_exclusive(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'in.dctl';source.write_bytes(b'source');target=Path(folder)/'out.dctle'
            def encrypt(path,options):
                (Path(options['OutputFolder'])/'encrypted.dctle').write_bytes(b'cipher');return True
            with patch.object(helper.os,'link',side_effect=OSError(errno.EXDEV,'cross-volume')):
                result=helper.encrypt_dctl(SimpleNamespace(EncryptDCTL=encrypt),str(source),str(target),None,lambda p:p)
            self.assertTrue(result['success']);self.assertEqual(target.read_bytes(),b'cipher')

    def test_bad_arguments_and_missing_method_refuse(self):
        native=SimpleNamespace(EncryptDCTL=None)
        with patch.object(s,'get_resolve',return_value=native),patch.object(g,'get_resolve',return_value=native):
            self.assertIn('error',s.dctl('encrypt_native',{'input_path':'x','output_path':'y'}))
            self.assertIn('error',g.encrypt_dctl_native('x','y'))
        self.assertIn('error',helper.encrypt_dctl(native,None,'out',None,lambda p:p))

    def test_write_registration_and_dry_run(self):
        self.assertTrue(destructive_hook.is_destructive('dctl','encrypt_native'))
        risk=classify_operation_risk('dctl','encrypt_native',{}).to_dict()
        self.assertTrue(risk['recognised']);self.assertTrue(risk['destructive'])
        with patch.object(s,'get_resolve') as get:
            result=s.dctl('encrypt_native',{'input_path':'in.dctl','output_path':'out.dctle','dry_run':True})
            self.assertIn('error',result)


    def test_failed_fallback_copy_removes_only_new_partial_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'in.dctl';source.write_bytes(b'source');target=Path(folder)/'out.dctle'
            def encrypt(path,options):
                (Path(options['OutputFolder'])/'encrypted.dctle').write_bytes(b'cipher');return True
            with patch.object(helper.os,'link',side_effect=OSError(errno.EXDEV,'cross-volume')),patch.object(helper.shutil,'copyfileobj',side_effect=OSError('copy failed')):
                result=helper.encrypt_dctl(SimpleNamespace(EncryptDCTL=encrypt),str(source),str(target),None,lambda p:p)
            self.assertFalse(result['success']);self.assertFalse(target.exists())
            self.assertEqual(source.read_bytes(),b'source')

    def test_dangling_output_symlink_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'in.dctl';source.write_bytes(b'source');target=Path(folder)/'out.dctle'
            try:
                target.symlink_to(Path(folder)/'absent')
            except OSError:
                self.skipTest('symlink creation is unavailable')
            native=SimpleNamespace(EncryptDCTL=lambda *_:self.fail('native encryption should not run'))
            result=helper.encrypt_dctl(native,str(source),str(target),None,lambda p:p)
            self.assertFalse(result['success']);self.assertTrue(target.is_symlink())
