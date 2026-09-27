import copy
import json
import tempfile
import unittest
from pathlib import Path

import planctl


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.snapshot_path = 'docs/specification/revisions/r1/snapshot.json'
        self.snapshot = {'schema': 1, 'stage': 'DDD', 'entities': {
            'O': {'kind': 'obligation', 'status': 'active'},
            'S': {'kind': 'scenario', 'status': 'active'},
        }}
        self.put(self.snapshot_path, self.snapshot)
        self.put('audit/gates.json', {'schema_version': 1, 'gates': [
            {'id': 'document', 'required': True, 'status': 'PASS'},
            {'id': 'runtime', 'required': False, 'status': 'UNKNOWN'}]})
        self.put('docs/specification/CURRENT', 'r1', raw=True)
        for name in ['docs/specification/policy.json', 'docs/specification/revisions/r1/manifest.json',
                     'docs/specification/revisions/r1/review.json', 'docs/specification/approvals/a.json']:
            self.put(name, {})
        for name in ('00-exploration', 'BRD', 'TRD', 'SAD', 'SDD', 'DDD'):
            self.put('docs/' + name + '.md', name, raw=True)
        sha = planctl.digest(self.root / 'docs/00-exploration.md')
        self.put('docs/specification/sources/' + sha + '.txt', '00-exploration', raw=True)
        self.snapshot['entities']['SRC-EXPLORATION'] = {
            'kind': 'source', 'status': 'active', 'data': {'sha256': sha, 'role': 'exploration'}}
        self.put(self.snapshot_path, self.snapshot)
        paths = [p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file()]
        self.baseline = {'schema': 1, 'files': {p: planctl.digest(self.root / p) for p in paths}}
        self.refresh_audit()
        self.plan = {'schema': 1, 'id': 'mvp', 'revision': 'r1',
                     'baseline': 'docs/kickoff/baseline.json', 'snapshot': self.snapshot_path,
                     'audit_gates': 'audit/gates.json', 'audit_manifest': 'audit/manifest.json',
                     'scope': {'goal': 'Useful result', 'phase': 'MVP', 'basis': ['O']},
                     'requirements': {'O': {'disposition': 'include', 'reason': 'Core', 'basis': ['O'],
                                           'owners': ['first'], 'applies_to': ['first'], 'scenarios': ['S']}},
                     'changes': [{'id': 'first', 'outcome': 'Result', 'rationale': 'Core', 'basis': ['O'],
                                  'contracts': [], 'tasks': [], 'requirements': ['O'], 'scenarios': ['S'],
                                  'depends_on': [], 'wave': 0, 'writes': ['src/a.py'], 'independence': 'Sequential',
                                  'checks': [{'scenario': 'S', 'method': 'Test', 'expected': 'Result'}]}],
                     'conditions': [], 'execution': {'mode': 'sequential', 'max_workers': 1},
                     'review': 'docs/kickoff/review.json', 'approval': 'docs/kickoff/approval.json'}
        self.save()

    def put(self, name, value, raw=False):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value if raw else json.dumps(value), encoding='utf-8')

    def save(self):
        self.put('docs/kickoff/plan.json', self.plan)

    def refresh_audit(self):
        self.put('audit/manifest.json', {'schema_version': 1,
            'specification': {'store': 'docs/specification', 'revision': 'r1'},
            'documents': [{'path': name, 'sha256': sha, 'availability': 'readable'}
                          for name, sha in self.baseline['files'].items() if name != 'audit/manifest.json']})
        self.baseline['files']['audit/manifest.json'] = planctl.digest(self.root / 'audit/manifest.json')
        self.put('docs/kickoff/baseline.json', self.baseline)

    def run_check(self, execution=False):
        return planctl.check(self.root, 'docs/kickoff/plan.json', execution)

    def approve(self):
        result, _ = self.run_check()
        identity = {k: result[k] for k in ('plan_hash', 'baseline_hash')}
        self.put(self.plan['review'], dict(schema=1, **identity, criteria={
            key: {'status': 'PASS', 'reason': 'Fixture reviewed', 'evidence': ['fixture#' + key]}
            for key in planctl.CRITERIA}))
        self.put(self.plan['approval'], dict(schema=1, **identity, decision='User approved this edition', approved_at='2026-09-27'))

    def test_no_review_unknown(self):
        result, code = self.run_check()
        self.assertEqual((result['mechanical'], result['readiness'], code), ('PASS', 'UNKNOWN', 1))

    def test_ready_and_approved(self):
        self.approve()
        result, code = self.run_check(True)
        self.assertEqual((result['readiness'], result['approval'], code), ('READY', True, 0))

    def test_execution_requires_approval(self):
        self.approve()
        (self.root / self.plan['approval']).unlink()
        self.assertEqual(self.run_check(True)[1], 1)
        self.assertEqual(self.run_check()[1], 0)

    def test_missing_requirement(self):
        self.plan['requirements'] = {}
        self.save()
        self.assertEqual(self.run_check()[0]['mechanical'], 'FAIL')

    def test_cycle_or_future_dependency(self):
        self.plan['changes'][0]['depends_on'] = ['first']
        self.save()
        self.assertEqual(self.run_check()[0]['mechanical'], 'FAIL')

    def test_stale_review_and_approval(self):
        self.approve()
        self.plan['scope']['goal'] = 'Changed'
        self.save()
        result, code = self.run_check(True)
        self.assertEqual((result['readiness'], result['approval'], code), ('FAIL', False, 1))

    def test_baseline_drift(self):
        self.approve()
        self.put('docs/TRD.md', 'Changed', raw=True)
        self.assertEqual(self.run_check()[0]['readiness'], 'FAIL')

    def test_pending_publication(self):
        self.approve()
        self.put('docs/specification/DOCS-PENDING.json', {})
        self.assertEqual(self.run_check()[0]['readiness'], 'FAIL')

    def test_mandatory_audit_unknown(self):
        gates = {'schema_version': 1, 'gates': [{'id': 'document', 'required': True, 'status': 'UNKNOWN'}]}
        self.put('audit/gates.json', gates)
        self.baseline['files']['audit/gates.json'] = planctl.digest(self.root / 'audit/gates.json')
        self.put(self.plan['baseline'], self.baseline)
        self.assertIn('Mandatory audit gate: document', self.run_check()[0]['errors'])

    def test_deferred_must_not_be_assigned(self):
        self.plan['requirements']['O']['disposition'] = 'deferred'
        self.save()
        self.assertEqual(self.run_check()[0]['mechanical'], 'FAIL')

    def test_missing_scenario_check(self):
        self.plan['changes'][0]['checks'] = []
        self.save()
        self.assertEqual(self.run_check()[0]['mechanical'], 'FAIL')

    def test_parallel_shared_write(self):
        second = copy.deepcopy(self.plan['changes'][0])
        second['id'] = 'second'
        self.plan['changes'].append(second)
        self.plan['requirements']['O']['applies_to'].append('second')
        self.plan['execution'] = {'mode': 'parallel', 'max_workers': 2}
        self.save()
        self.assertIn('Shared write in wave: first/second', self.run_check()[0]['errors'])

    def test_crosscutting_requirement_multiple_carriers(self):
        second = copy.deepcopy(self.plan['changes'][0])
        second.update(id='second', wave=1, depends_on=['first'])
        self.plan['changes'].append(second)
        self.plan['requirements']['O']['applies_to'].append('second')
        self.save()
        self.approve()
        self.assertEqual(self.run_check(True)[1], 0)

    def test_closed_condition_needs_evidence(self):
        self.plan['conditions'] = [{'id': 'access', 'description': 'Account', 'owner': 'User',
                                   'timing': 'before_start', 'changes': ['first'], 'status': 'closed', 'evidence': []}]
        self.save()
        self.assertIn('Closed condition needs evidence', self.run_check()[0]['errors'])

    def test_duplicate_json_and_escape_rejected(self):
        self.put('bad.json', '{"x":1,"x":2}', raw=True)
        with self.assertRaises(ValueError):
            planctl.read(self.root / 'bad.json')
        for value in ('../escape', 'C:/escape', '/absolute', 'a/../b', 'a\\b'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                planctl.path(self.root, value)

    def test_lock_refuses_overwrite(self):
        self.put('inputs.json', ['docs/TRD.md'])
        args = ['lock', '--root', str(self.root), '--files', 'inputs.json', '--out', 'locked.json']
        self.assertEqual(planctl.main(args), 0)
        original = (self.root / 'locked.json').read_bytes()
        self.assertEqual(planctl.main(args), 2)
        self.assertEqual((self.root / 'locked.json').read_bytes(), original)

    def test_explicit_exploration_path_and_source_binding(self):
        original = self.root / 'docs/00-exploration.md'
        self.put('inputs/00-exploration.md', original.read_text(encoding='utf-8'), raw=True)
        original.unlink()
        self.baseline['files']['inputs/00-exploration.md'] = self.baseline['files'].pop('docs/00-exploration.md')
        self.refresh_audit()
        self.plan['exploration'] = 'inputs/00-exploration.md'
        self.save()
        self.approve()
        self.assertEqual(self.run_check(True)[1], 0)
        # Rehashing changed original must not legitimize a stale source snapshot.
        self.put('inputs/00-exploration.md', 'different idea', raw=True)
        self.baseline['files']['inputs/00-exploration.md'] = planctl.digest(self.root / 'inputs/00-exploration.md')
        self.put(self.plan['baseline'], self.baseline)
        self.approve()
        self.assertIn('Exploration differs from selected source snapshot', self.run_check()[0]['errors'])

    def split_scenarios(self):
        self.snapshot['entities']['S2'] = {'kind': 'scenario', 'status': 'active'}
        self.put(self.snapshot_path, self.snapshot)
        self.baseline['files'][self.snapshot_path] = planctl.digest(self.root / self.snapshot_path)
        self.refresh_audit()
        second = copy.deepcopy(self.plan['changes'][0])
        second.update(id='ui', wave=1, depends_on=['first'], scenarios=['S2'], writes=['src/ui.py'],
                      checks=[{'scenario': 'S2', 'method': 'UI test', 'expected': 'Result'}])
        self.plan['changes'].append(second)
        self.plan['requirements']['O'].update(applies_to=['first', 'ui'], scenarios=['S', 'S2'], coverage=[
            {'change': 'first', 'scenario': 'S', 'scope': 'local', 'requires': ['first']},
            {'change': 'ui', 'scenario': 'S2', 'scope': 'integration', 'requires': ['first', 'ui']}])
        self.save()

    def test_local_then_integration_scenario_allocation(self):
        self.split_scenarios()
        self.approve()
        self.assertEqual(self.run_check(True)[1], 0)

    def test_missing_integration_coverage_is_rejected(self):
        self.split_scenarios()
        self.plan['requirements']['O']['coverage'].pop()
        self.save()
        self.assertIn('O: incomplete scenario coverage', self.run_check()[0]['errors'])

    def test_scenario_cannot_depend_on_future_or_unrelated_change(self):
        self.split_scenarios()
        self.plan['requirements']['O']['coverage'][0]['requires'].append('ui')
        self.save()
        self.assertIn('O: scenario depends on unavailable changes', self.run_check()[0]['errors'])

    def test_split_allocation_requires_explicit_mapping(self):
        self.split_scenarios()
        del self.plan['requirements']['O']['coverage']
        self.save()
        self.assertIn('O: split scenario allocation needs explicit coverage', self.run_check()[0]['errors'])

    def test_audit_for_other_revision_cannot_authorize_plan(self):
        manifest = planctl.read(self.root / 'audit/manifest.json')
        manifest['specification']['revision'] = 'other'
        self.put('audit/manifest.json', manifest)
        self.baseline['files']['audit/manifest.json'] = planctl.digest(self.root / 'audit/manifest.json')
        self.put(self.plan['baseline'], self.baseline)
        self.assertIn('Audit revision binding missing or stale', self.run_check()[0]['errors'])

    def test_selected_parallel_wave_needs_pair_evidence(self):
        second = copy.deepcopy(self.plan['changes'][0])
        second.update(id='second', writes=['src/b.py'])
        self.plan['changes'].append(second)
        self.plan['requirements']['O']['applies_to'].append('second')
        self.plan['execution'] = {'mode': 'parallel', 'max_workers': 2}
        self.save()
        self.assertIn('Selected parallel wave lacks independence: first/second', self.run_check()[0]['errors'])
        self.plan['parallelism'] = {'pairs': [{'a': 'first', 'b': 'second', 'status': 'independent',
            'reason': 'Synthetic fixture: stable contracts, isolated data and files', 'evidence': ['fixture']}]}
        self.save()
        self.approve()
        self.assertEqual(self.run_check(True)[1], 0)


if __name__ == '__main__':
    unittest.main()
