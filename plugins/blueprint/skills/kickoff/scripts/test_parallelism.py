import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import planctl


class ParallelAnalysisTests(unittest.TestCase):
    def plan(self, reviewed=True):
        return {'changes': [
            {'id': cid, 'depends_on': deps, 'writes': ['src/' + cid + '.py']}
            for cid, deps in [('foundation', []), ('export', ['foundation']),
                              ('search', ['foundation']), ('integration', ['export', 'search'])]],
            'parallelism': {'pairs': ([{'a': 'export', 'b': 'search', 'status': 'independent',
                                       'reason': 'Frozen contracts and separate state', 'evidence': ['contract#isolation']}] if reviewed else [])},
            'conditions': []}

    def test_diamond_allows_two_middle_changes(self):
        report = planctl.parallel_analysis(self.plan())
        self.assertEqual(report['analysis_state'], 'COMPLETE')
        self.assertEqual(report['scenarios'][0]['wave_count'], 4)
        self.assertEqual(report['scenarios'][1]['waves'], [['foundation'], ['export', 'search'], ['integration']])
        self.assertEqual(report['scenarios'][2]['observed_width'], 2)
        self.assertEqual(report['timing'], 'UNKNOWN')
        self.assertNotIn('conditional_reduction_percent', report['scenarios'][1])

    def test_unknown_pair_is_serialized(self):
        report = planctl.parallel_analysis(self.plan(False))
        self.assertEqual(report['analysis_state'], 'PARTIAL')
        self.assertEqual(report['scenarios'][2]['wave_count'], 4)

    def test_semantic_conflict_without_shared_files_is_serialized(self):
        plan = self.plan()
        plan['parallelism']['pairs'][0].update(status='conflict', reason='Shared external test account')
        report = planctl.parallel_analysis(plan)
        self.assertEqual(report['scenarios'][2]['observed_width'], 1)

    def test_shared_write_cannot_be_overridden_by_claim(self):
        plan = self.plan()
        plan['changes'][1]['writes'].append('schema.sql')
        plan['changes'][2]['writes'].append('schema.sql')
        report = planctl.parallel_analysis(plan)
        self.assertTrue(report['errors'])
        self.assertEqual(report['scenarios'][1]['observed_width'], 1)

    def test_transitive_dependency_cannot_be_independent(self):
        plan = self.plan()
        plan['parallelism']['pairs'].append({'a': 'foundation', 'b': 'integration', 'status': 'independent',
                                             'reason': 'Incorrect fixture', 'evidence': ['fixture']})
        report = planctl.parallel_analysis(plan)
        self.assertTrue(any('foundation/integration' in e for e in report['errors']))

    def test_estimates_compute_conditional_span_not_real_speedup(self):
        plan = self.plan()
        plan['parallelism']['estimates'] = {'unit': 'work-units', 'basis': 'Synthetic comparable effort',
            'values': {'foundation': 1, 'export': 3, 'search': 2, 'integration': 1}}
        report = planctl.parallel_analysis(plan)
        self.assertEqual(report['longest_dependency_chain']['weight'], 5)
        self.assertEqual(report['scenarios'][1]['estimated_work_span'], 5)
        self.assertEqual(report['scenarios'][1]['sequential_work_span'], 7)
        self.assertEqual(report['scenarios'][1]['conditional_reduction_percent'], 28.57)
        del plan['parallelism']['estimates']['values']['search']
        with self.assertRaisesRegex(ValueError, 'Estimates'):
            planctl.parallel_analysis(plan)

    def test_cycle_duplicate_pair_and_bad_limit_rejected(self):
        plan = self.plan()
        plan['changes'][0]['depends_on'] = ['integration']
        with self.assertRaisesRegex(ValueError, 'cycle'):
            planctl.parallel_analysis(plan)
        plan = self.plan()
        row = dict(plan['parallelism']['pairs'][0])
        row['a'], row['b'] = row['b'], row['a']
        plan['parallelism']['pairs'].append(row)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            planctl.parallel_analysis(plan)
        with self.assertRaises(ValueError):
            planctl.parallel_analysis(self.plan(), [0])

    def test_open_conditions_remain_visible(self):
        plan = self.plan()
        plan['conditions'] = [{'id': 'access', 'status': 'open', 'timing': 'before_start',
                               'changes': ['search'], 'owner': 'User'}]
        report = planctl.parallel_analysis(plan)
        self.assertEqual(report['open_conditions'][0]['id'], 'access')

    def test_cli_does_not_change_plan_or_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = self.plan()
            plan['execution'] = {'mode': 'sequential', 'max_workers': 1}
            p = root / 'plan.json'
            p.write_text(json.dumps(plan), encoding='utf-8')
            before = p.read_bytes()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = planctl.main(['parallel', '--root', str(root), '--plan', 'plan.json', '--workers', '1', '2'])
            self.assertEqual(code, 0)
            self.assertEqual(p.read_bytes(), before)
            self.assertEqual(json.loads(output.getvalue())['plan_hash'], planctl.digest(p))


if __name__ == '__main__':
    unittest.main()
