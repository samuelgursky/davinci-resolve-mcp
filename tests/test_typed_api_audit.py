"""Small source fixtures expose coverage errors without importing Resolve."""
import unittest

from scripts.audit_typed_api import build_report, inventory_stub


class TypedAuditTests(unittest.TestCase):
    def test_comment_and_docstring_are_not_coverage(self):
        report = build_report('class Pool:\n def CreateMulticamClip(self): ...', {
            'src/server.py': '# pool.CreateMulticamClip(clips)\n"""pool.CreateMulticamClip(clips)"""'})
        self.assertEqual(report['candidate_gaps'], ['Pool.CreateMulticamClip'])

    def test_shared_names_keep_class_identity_and_uncertainty(self):
        report = build_report('class Resolve:\n def GetCurrentProject(self): ...\n'
                              'class ProjectManager:\n def GetCurrentProject(self): ...',
                              {'src/server.py': 'pm.GetCurrentProject()'})
        self.assertEqual(report['method_count'], 2)
        for row in report['methods'].values():
            self.assertEqual(row['status'], 'unresolved_receiver')
            self.assertEqual(row['name_references'][0]['receiver'], 'pm')

    def test_source_layers_and_reference_kinds_are_distinct(self):
        report = build_report('class Clip:\n def GetType(self): ...', {
            'src/server.py': 'clip.GetType()',
            'src/granular/clip.py': 'getter = getattr(clip, "GetType", None)',
            'src/utils/clip.py': 'getter = clip.GetType'})
        refs = report['methods']['Clip.GetType']['name_references']
        self.assertEqual({(r['layer'], r['kind']) for r in refs},
                         {('compound', 'call'), ('granular', 'getattr'), ('helper', 'attribute')})

    def test_options_and_signatures_are_preserved(self):
        result = inventory_stub('class Options(TypedDict, total=False):\n duration: int\n'
                                ' "Frames"\nclass Clip:\n def AddTransition(self, options: Options) -> bool: ...')
        self.assertEqual(result['option_types']['Options']['duration']['description'], 'Frames')
        self.assertIn('options: Options', result['methods']['Clip.AddTransition']['signatures'][0])

    def test_overloads_are_not_silently_overwritten(self):
        result = inventory_stub('class Clip:\n def GetProperty(self, name: str): ...\n'
                                ' def GetProperty(self): ...')
        self.assertEqual(len(result['methods']['Clip.GetProperty']['signatures']), 2)

    def test_empty_or_malformed_stub_fails(self):
        with self.assertRaises(ValueError):
            inventory_stub('# stale documentation with no API')
        with self.assertRaises(SyntaxError):
            inventory_stub('class broken')


if __name__ == '__main__':
    unittest.main()
