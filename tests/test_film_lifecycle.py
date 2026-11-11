import unittest
from copy import deepcopy
from src.utils.execution_lifecycle import DriftDetectionHook, ToolCallContext
from src.utils.operation_result import build_operation_envelope, normalize_status


class FilmLifecycleTests(unittest.TestCase):
    def test_preflight_envelope_maps_only_declared_report_statuses(self):
        for status, check_status, expected in (
            ('failed', 'fail', 'failed'), ('incomplete', 'unknown', 'blocked'),
            ('warnings', 'warn', 'partial'), ('passed', 'pass', 'success'),
        ):
            report = {'schema': 'film-preflight/v1', 'status': status,
                      'checks': [{'name': 'picture_version', 'status': check_status}],
                      'picture_fingerprint': 'synthetic', 'timeline_id': 'synthetic',
                      'mutations': 0}
            original = deepcopy(report)
            for mode in ('dual', 'pure'):
                with self.subTest(status=status, mode=mode):
                    result = build_operation_envelope('timeline', 'film_preflight', {}, report,
                                                      mode=mode, execution_id='test')
                    envelope = result['_operation'] if mode == 'dual' else result
                    payload = {k: v for k, v in result.items() if k != '_operation'} if mode == 'dual' else result['result']
                    self.assertEqual(envelope['status'], expected)
                    self.assertEqual(payload, original)
                    self.assertEqual(report, original)

    def test_stem_partial_failure_preserves_error_and_receipts(self):
        report = {'schema': 'film-stem-return/v1', 'status': 'partial_failure',
                  'error': 'Media import incomplete',
                  'created_tracks': [{'index': 2, 'name': 'FILM_synthetic_music'}],
                  'imported_media': ['synthetic.wav'], 'partially_created_unknown': True,
                  'rollback_attempted': False}
        original = deepcopy(report)
        for mode in ('dual', 'pure'):
            with self.subTest(mode=mode):
                result = build_operation_envelope('timeline', 'film_stems_return', {}, report,
                                                  mode=mode, execution_id='test')
                envelope = result['_operation'] if mode == 'dual' else result
                payload = {k: v for k, v in result.items() if k != '_operation'} if mode == 'dual' else result['result']
                self.assertEqual(envelope['status'], 'partial')
                self.assertEqual(payload, original)
                self.assertEqual(report, original)

    def test_unknown_schemas_keep_existing_status_rules(self):
        for schema in (None, 'other/v1', 'film-preflight/v2', 'film-stem-return/v2'):
            for status in ('failed', 'incomplete', 'warnings', 'passed', 'partial_failure'):
                with self.subTest(schema=schema, status=status):
                    report = {'status': status}
                    if schema is not None: report['schema'] = schema
                    self.assertEqual(normalize_status(report), 'success')
                    self.assertEqual(normalize_status({**report, 'error': 'failure'}), 'failed')
        self.assertEqual(normalize_status({'schema': 'film-preflight/v1', 'status': 'future'}), 'success')
        self.assertEqual(normalize_status({'schema': 'film-stem-return/v1', 'status': 'failed'}), 'success')

    def test_import_may_extend_timeline_but_preview_must_not(self):
        for preview in (True,False):
            with self.subTest(preview=preview):
                hook=DriftDetectionHook(lambda:{'duration_frames':48})
                ctx=ToolCallContext('timeline','film_stems_return',{'preview':preview})
                ctx.pre_state={'duration_frames':0}
                result=hook.after_tool_call(ctx,{},1)
                self.assertEqual(result is not None,preview)


class FilmStemsReturnRiskTests(unittest.TestCase):
    """Applying film_stems_return imports media and adds tracks; preview reads."""

    def test_preview_is_a_recognised_read(self):
        from src.utils.destructive_hook import is_destructive
        from src.utils.execution_lifecycle import RiskLevel, classify_operation_risk
        for params in ({}, {'preview': True}, {'preview': 'true'}, {'preview': 'unparseable'}):
            with self.subTest(params=params):
                risk = classify_operation_risk('timeline', 'film_stems_return', params)
                self.assertTrue(risk.recognised)
                self.assertFalse(risk.destructive)
                self.assertEqual(risk.level, RiskLevel.LOW)
                self.assertFalse(is_destructive('timeline', 'film_stems_return', params))

    def test_apply_is_a_recognised_mutation_that_archives(self):
        from src.utils.destructive_hook import is_destructive
        from src.utils.execution_lifecycle import BlastRadius, RiskLevel, classify_operation_risk
        for params in ({'preview': False}, {'preview': 'false'}, {'preview': 0}):
            with self.subTest(params=params):
                risk = classify_operation_risk('timeline', 'film_stems_return', params)
                self.assertTrue(risk.recognised)
                self.assertTrue(risk.destructive)
                self.assertEqual(risk.level, RiskLevel.MEDIUM)
                self.assertEqual(risk.blast_radius, BlastRadius.TIMELINE)
                self.assertTrue(is_destructive('timeline', 'film_stems_return', params))
