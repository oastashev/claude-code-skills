"""Synthetic fixtures: plans, reviews and OpenSpec changes are test data, not project evidence."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import materializectl

SPEC = '# {cap}\n\n## Purpose\nFixture.\n\n## Requirements\n\n### Requirement: {name}\nThe system SHALL {name}.\n'


class MaterializeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.put('openspec/specs/collections/spec.md', SPEC.format(cap='collections', name='Store collection'))
        self.plan = {'schema': 2, 'changes': [
            {'id': cid, 'wave': wave, 'depends_on': deps, 'writes': ['src/' + cid + '.py']}
            for cid, wave, deps in [('foundation', 0, []), ('export', 1, ['foundation']),
                                    ('search', 2, ['foundation']), ('integration', 3, ['export', 'search'])]],
            'parallelism': {'pairs': [{'a': 'export', 'b': 'search', 'status': 'independent',
                                       'reason': 'Separate modules', 'evidence': ['plan#export-search']}]},
            'conditions': [], 'execution': {'mode': 'sequential', 'max_workers': 1}}
        self.deltas = {
            'foundation': {'collections': '## MODIFIED Requirements\n\n### Requirement: Store collection\nChanged.\n'},
            'export': {'export': '## ADDED Requirements\n\n### Requirement: Export file\nThe system SHALL export.\n'},
            'search': {'search': '## ADDED Requirements\n\n### Requirement: Find item\nThe system SHALL find.\n'},
            'integration': {'export': '## MODIFIED Requirements\n\n### Requirement: Export file\nFrom UI.\n'}}
        self.pairs, self.edges = [], []
        self.build({})

    def parallel(self):
        self.plan['execution'] = {'mode': 'parallel', 'max_workers': 2}
        self.plan['changes'][2]['wave'] = 1
        self.plan['changes'][3]['wave'] = 2

    def put(self, name, value):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value if isinstance(value, str) else json.dumps(value, indent=2), encoding='utf-8')

    def build(self, states, review=True):
        self.put('docs/kickoff/plan.json', self.plan)
        plan_hash = materializectl.digest(self.root / 'docs/kickoff/plan.json')
        self.put('docs/kickoff/adapter.json', {'plan_hash': plan_hash, 'cli': 'synthetic'})
        shutil.rmtree(self.root / 'openspec/changes', ignore_errors=True)
        shutil.rmtree(self.root / 'docs/materialize', ignore_errors=True)
        changes = {}
        for c in self.plan['changes']:
            cid, base, state = c['id'], 'openspec/changes/' + c['id'], states.get(c['id'], 'planned')
            changes[cid] = dict(path=base, state=state, archive=None, writes=c['writes'], files={})
            if state == 'archived':
                changes[cid]['archive'] = 'openspec/changes/archive/x-' + cid
                self.put(changes[cid]['archive'] + '/proposal.md', 'archived')
                for cap, text in self.deltas[cid].items():
                    if 'ADDED' in text:
                        self.put('openspec/specs/' + cap + '/spec.md', SPEC.format(cap=cap, name=text.split(': ')[1].split('\n')[0]))
            elif state == 'active':
                self.put(base + '/proposal.md', '# ' + cid + '\nplan_hash: ' + plan_hash + '\n')
                self.put(base + '/tasks.md', '- [ ] 1.1 Fixture task\n')
                for cap, text in self.deltas[cid].items():
                    self.put(base + '/specs/' + cap + '/spec.md', text)
                changes[cid]['files'] = json.loads(self.cli('bind', '--change', base)[1])['files']
                if review:
                    self.put('docs/materialize/reviews/' + cid + '.json', dict(
                        schema=1, change=cid, plan_hash=plan_hash, files=changes[cid]['files'], criteria={
                            k: dict(status='PASS', reason='Synthetic fixture, not a semantic review', evidence=['fixture'])
                            for k in materializectl.CRITERIA}))
        active = {cid for cid, s in states.items() if s == 'active'}
        self.roadmap = {'schema': 1, 'plan': 'docs/kickoff/plan.json', 'plan_hash': plan_hash,
                        'adapter': 'docs/kickoff/adapter.json',
                        'adapter_hash': materializectl.digest(self.root / 'docs/kickoff/adapter.json'),
                        'specs': 'openspec/specs', 'reviews': 'docs/materialize/reviews', 'changes': changes,
                        'edges': self.edges, 'pairs': [p for p in self.pairs if {p['a'], p['b']} <= active]}
        self.put('docs/materialize/roadmap.json', self.roadmap)

    def cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = materializectl.main([args[0], '--root', str(self.root), *args[1:]])
        return code, output.getvalue()

    def check(self):
        return materializectl.check(self.root, 'docs/materialize/roadmap.json')

    def next(self, states):
        self.build(states)
        result, code = self.check()
        self.assertEqual(code, 0, result['errors'] + result['divergences'])
        return result['next']

    def test_each_run_creates_one_change_waits_or_completes(self):
        self.assertEqual(self.next({}), dict(action='create', change='foundation', wave=0, blocked_by_conditions=[]))
        waiting = self.next({'foundation': 'active'})
        self.assertEqual((waiting['action'], waiting['waiting_for']), ('wait', ['foundation']))
        self.assertEqual(self.next({'foundation': 'archived'})['change'], 'export')
        self.assertEqual(self.next({'foundation': 'archived', 'export': 'archived', 'search': 'archived'})['change'],
                         'integration')
        done = {c['id']: 'archived' for c in self.plan['changes']}
        self.assertEqual(self.next(done)['action'], 'complete')

    def test_released_plan_of_previous_schema_still_runs(self):
        self.plan['schema'] = 1
        self.assertEqual(self.next({})['change'], 'foundation')
        self.plan['schema'] = 3
        self.build({})
        self.assertIn('Unsupported schema', self.check()[0]['errors'])

    def test_creation_ignores_max_workers_and_later_waves(self):
        # Sequential plan, max_workers=1: execution capacity does not gate materialize.
        self.pairs = [{'a': 'export', 'b': 'search', 'status': 'independent', 'reason': 'Separate modules and specs',
                       'evidence': ['src/export.py', 'src/search.py']}]
        self.assertEqual(self.next({'foundation': 'archived', 'export': 'active'})['change'], 'search')
        waiting = self.next({'foundation': 'archived', 'export': 'active', 'search': 'active'})
        self.assertEqual((waiting['action'], waiting['waiting_for'], waiting['pending']),
                         ('wait', ['export', 'search'], {'integration': ['export', 'search']}))
        waiting = self.next({'foundation': 'archived', 'export': 'archived', 'search': 'active'})
        self.assertEqual(waiting['pending'], {'integration': ['search']})

    def test_open_before_start_condition_is_reported_with_created_change(self):
        self.plan['conditions'] = [{'id': 'access', 'status': 'open', 'timing': 'before_start',
                                    'changes': ['foundation'], 'owner': 'Ops'}]
        self.assertEqual(self.next({})['blocked_by_conditions'], ['access'])

    def test_missing_review_blocks_next_decision(self):
        self.build({'foundation': 'active'}, review=False)
        result, code = self.check()
        self.assertEqual((result['readiness'], result['next']['action'], code), ('UNKNOWN', 'blocked', 1))

    def test_change_ahead_of_dependencies_blocks(self):
        self.build({'export': 'active'})
        result, code = self.check()
        self.assertEqual((result['next']['action'], code), ('blocked', 1))
        self.assertTrue(any('before its dependencies' in e for e in result['errors']))

    def test_dependency_inside_approved_wave_requires_revise(self):
        self.parallel()
        self.deltas['search'] = {'export': '## MODIFIED Requirements\n\n### Requirement: Export file\nFound.\n'}
        self.build({'foundation': 'archived', 'export': 'active', 'search': 'active'})
        result, code = self.check()
        self.assertEqual((result['plan_consistency'], code), ('DIVERGED', 1))
        self.assertEqual(result['divergences'][0]['action'], 'kickoff revise')

    def test_shared_capability_breaks_approved_parallel_wave(self):
        self.parallel()
        self.deltas['search'] = {'export': '## ADDED Requirements\n\n### Requirement: Find export\nFind.\n'}
        self.pairs = [{'a': 'export', 'b': 'search', 'status': 'independent', 'reason': 'Claimed',
                       'evidence': ['fixture']}]
        self.build({'foundation': 'archived', 'export': 'active', 'search': 'active'})
        result, code = self.check()
        self.assertEqual(code, 1)
        self.assertTrue(any(d['kind'] == 'wave' for d in result['divergences']))
        self.assertTrue(any('Independence contradicts' in e for e in result['errors']))

    def test_delta_must_match_current_specs(self):
        self.deltas['foundation'] = {'collections': '## ADDED Requirements\n\n### Requirement: Store collection\nX.\n',
                                     'search': '## REMOVED Requirements\n\n### Requirement: Missing\nGone.\n'}
        self.build({'foundation': 'active'})
        errors = self.check()[0]['errors']
        self.assertTrue(any('ADDED duplicates current' in e for e in errors))
        self.assertTrue(any('unknown requirement search/Missing' in e for e in errors))

    def test_bindings_detect_stale_inputs(self):
        self.build({'foundation': 'active'})
        (self.root / 'openspec/changes/foundation/proposal.md').write_text('edited', encoding='utf-8')
        errors = self.check()[0]['errors']
        self.assertTrue(any('STALE or missing' in e for e in errors))
        self.assertIn('foundation: STALE review identity', errors)
        self.build({'foundation': 'active'})
        self.put('openspec/changes/foundation/specs/extra/spec.md', self.deltas['search']['search'])
        self.assertTrue(any('bound files differ' in e for e in self.check()[0]['errors']))
        self.build({})
        self.put('docs/kickoff/adapter.json', {'plan_hash': 'other'})
        errors = self.check()[0]['errors']
        self.assertIn('Adapter bound to another plan', errors)
        self.assertIn('STALE adapter binding', errors)

    def test_declared_edges_need_evidence_and_cycles_fail(self):
        self.edges = [{'change': 'search', 'depends_on': 'export', 'kind': 'migration', 'reason': 'Migration order',
                       'evidence': []}]
        self.build({})
        self.assertTrue(any('Invalid discovered edge' in e for e in self.check()[0]['errors']))
        self.edges = [{'change': 'foundation', 'depends_on': 'integration', 'kind': 'data', 'reason': 'Fixture cycle',
                       'evidence': ['fixture']}]
        self.build({})
        result, code = self.check()
        self.assertEqual((result['analysis_state'], result['next']['action'], code), ('INVALID', 'blocked', 1))

    def test_advisory_scenarios_use_plan_assessment_for_planned_changes(self):
        result = self.check()[0]
        self.assertEqual(result['scenarios'][1]['waves'], [['foundation'], ['export', 'search'], ['integration']])
        self.assertEqual({p['basis'] for p in result['pairs'] if p['status'] == 'independent'}, {'plan'})
        self.assertEqual(result['longest_dependency_chain']['unit'], 'change_count')

    def test_parse_delta_rename_and_malformed_sections(self):
        entries, errors = materializectl.parse_delta(
            '## RENAMED Requirements\n- FROM: `### Requirement: Login`\n- TO: `### Requirement: Sign in`\n')
        self.assertEqual((entries, errors), ([{'op': 'RENAMED', 'name': 'Login', 'to': 'Sign in'}], []))
        self.assertTrue(materializectl.parse_delta('### Requirement: Loose\n')[1])
        self.assertTrue(materializectl.parse_delta('## RENAMED Requirements\n- FROM: `### Requirement: A`\n')[1])
        self.assertEqual(materializectl.parse_delta('# Nothing\n')[1], ['No recognized delta operations'])

    def test_cli_reports_without_writing(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        code, output = self.cli('check', '--roadmap', 'docs/materialize/roadmap.json', '--workers', '1', '3')
        self.assertEqual(code, 0)
        self.assertEqual([s['workers'] for s in json.loads(output)['scenarios']], [1, 3])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(self.cli('check', '--roadmap', '../outside.json')[0], 2)


if __name__ == '__main__':
    unittest.main()
