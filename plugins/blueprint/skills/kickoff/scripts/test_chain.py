"""Repository integration fixtures; synthetic reviews/consent, never LLM evidence.

Run with unittest discover in this directory. Standalone kickoff installations
without adjacent specify/audit skills skip these repository integration tests.
"""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, SKILLS / relative)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


AVAILABLE = all((SKILLS / p).is_file() for p in
                ('specify/scripts/specctl.py', 'audit/scripts/audit_support.py'))
if AVAILABLE:
    s = module('chain_specctl', 'specify/scripts/specctl.py')
    a = module('chain_audit', 'audit/scripts/audit_support.py')
    k = module('chain_planctl', 'kickoff/scripts/planctl.py')


@unittest.skipUnless(AVAILABLE, 'Adjacent skills required only for repository integration tests')
class ChainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.store = self.root / 'docs/specification'
        self.counter = 0

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def call(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = s.main(['--root', str(self.store), *args])
        self.assertEqual(code, 0, output.getvalue())
        try:
            return json.loads(output.getvalue())
        except json.JSONDecodeError:
            return output.getvalue()

    def entity(self, key, kind, stage, data, basis):
        return dict(id=key, kind=kind, stage=stage, status='active', statement='Synthetic fixture ' + key,
                    data=data, basis=basis)

    def review_accept(self, folder):
        self.call('prepare-review', '--package', str(folder))
        review = s.load(folder / 'review.json')
        review['reviewer'] = 'Synthetic test fixture, no semantic certification'
        for assessment in [*review['criteria'].values(), *review['edges'].values()]:
            assessment.update(status='PASS', reason='Synthetic fixture only', evidence=['O-1', 'S-1'])
        self.put(folder / 'review.json', review)
        self.call('accept', '--package', str(folder))

    def build(self, external=False, profile='compact'):
        self.exploration = self.root / ('inputs' if external else 'docs') / '00-exploration.md'
        self.exploration.parent.mkdir(parents=True, exist_ok=True)
        self.exploration.write_text('# SYNTHETIC exploration\nMVP: export an empty collection as a valid file.\n'
                                    'CAP-LATER: team sharing is discussed, not promised.\n'
                                    'Approved/READY are fixture assumptions, not actual user decisions.\n', encoding='utf-8')
        self.call('init', '--exploration', str(self.exploration), '--profile', profile)
        self.contract = self.root / 'contract.json'
        self.put(self.contract, dict(mode='stage-review', goal='Export fixture', scope=['O-1'],
                                    constraints=['Preserve result'], freedom=['wording'], outputs=['O-1'],
                                    checks=list(s.CRITERIA), unknowns=[]))
        # Compact designs components optionally in DESIGN; extended traces them in ARCH first.
        kinds = {'ARCH': ['component'], 'DESIGN': ['contract', 'module']}
        for stage in s.PROFILES[profile]:
            folder = self.root / 'packages' / stage
            self.call('begin', '--stage', stage, '--contract', str(self.contract), '--work', str(folder))
            snap = s.load(folder / 'candidate.json')
            if stage == 'REQ':
                snap['entities']['O-1'] = self.entity('O-1', 'obligation', stage,
                    dict(actor='user', trigger='export', precondition='collection exists', action='export',
                         outcome='valid file', exceptions=[], limits={}, phase='MVP', modality='must'), ['SRC-EXPLORATION'])
                for sid, context in [('S-1', 'service'), ('S-2', 'UI')]:
                    snap['entities'][sid] = self.entity(sid, 'scenario', stage,
                        dict(given='empty collection through ' + context, when='export', then='valid file',
                             distinguishes='No output is incorrect'), ['O-1'])
                    eid = 'E-' + sid
                    snap['edges'][eid] = dict(id=eid, type='verifies', due_stage='REQ', rationale='export outcome',
                                             **{'from': sid, 'to': 'O-1'})
                snap['entities']['D-SCOPE'] = self.entity('D-SCOPE', 'decision', stage,
                    dict(selected='Defer team sharing without commitment', exploration_refs=['CAP-LATER']), ['SRC-EXPLORATION'])
                shown = ['O-1', 'S-1', 'S-2', 'D-SCOPE']
            else:
                shown = [kind.upper() + '-1' for kind in kinds[stage]]
                for key, kind in zip(shown, kinds[stage]):
                    snap['entities'][key] = self.entity(key, kind, stage, {'responsibility': 'export'}, ['O-1'])
            snap['documents'][stage] = dict(title=stage, sections=[dict(id='main', title='Fixture',
                                              prose='Synthetic, not project requirements', entities=shown)])
            self.put(folder / 'candidate.json', snap)
            self.review_accept(folder)
            self.call('approve', '--stage', stage, '--decision', 'SYNTHETIC test approval of ' + stage)

    def audit_plan(self):
        self.counter += 1
        revision = s.current(self.store)
        prefix = '.blueprint/outputs/audit/run-' + str(self.counter)
        audit = self.root / prefix
        input_file = self.root / ('audit-input-' + str(self.counter) + '.json')
        self.put(input_file, {'documents': [{'path': self.exploration.relative_to(self.root).as_posix(),
                                            'role': 'exploration', 'authority': 'current'}],
                              'specification': {'store': 'docs/specification', 'revision': revision}})
        a.collect(self.root, input_file, audit)
        self.assertEqual(a.verify(self.root, audit / 'manifest.json')[0], 0)
        self.put(audit / 'gates.json', {'schema_version': 1, 'gates': [
            {'id': 'document', 'required': True, 'status': 'PASS'},
            {'id': 'runtime', 'required': False, 'status': 'UNKNOWN'}]})
        manifest = a.read_json(audit / 'manifest.json')
        files = {d['path']: d['sha256'] for d in manifest['documents']}
        for p in audit.iterdir():
            files[p.relative_to(self.root).as_posix()] = k.digest(p)
        base = 'docs/kickoff/plan-' + str(self.counter)
        self.put(self.root / (base + '/baseline.json'), {'schema': 1, 'files': files})
        plan = dict(schema=2, id='export-mvp', revision=revision, baseline=base + '/baseline.json',
                    exploration=self.exploration.relative_to(self.root).as_posix(), exploration_source='SRC-EXPLORATION',
                    snapshot='docs/specification/revisions/' + revision + '/snapshot.json',
                    audit_gates=prefix + '/gates.json', audit_manifest=prefix + '/manifest.json',
                    scope=dict(goal='Valid export', phase='MVP', basis=['O-1']),
                    requirements={'O-1': dict(disposition='include', reason='Core', basis=['O-1'], owners=['service'],
                                             applies_to=['service', 'ui'], scenarios=['S-1', 'S-2'], coverage=[
                        dict(change='service', scenario='S-1', scope='local', requires=['service']),
                        dict(change='ui', scenario='S-2', scope='integration', requires=['service', 'ui'])])},
                    changes=[], conditions=[], execution=dict(mode='sequential', max_workers=1),
                    review=base + '/review.json', approval=base + '/approval.json')
        for cid, sid, wave, deps in [('service', 'S-1', 0, []), ('ui', 'S-2', 1, ['service'])]:
            plan['changes'].append(dict(id=cid, outcome='Valid file', rationale='Core', basis=['O-1'],
                contracts=['CONTRACT-1'], modules=['MODULE-1'], requirements=['O-1'], scenarios=[sid], depends_on=deps,
                wave=wave, writes=['src/' + cid + '.py'], independence='Sequential',
                checks=[dict(scenario=sid, method='Run export via ' + cid, expected='Valid file')]))
        plan_path = base + '/plan.json'
        self.put(self.root / plan_path, plan)
        identity = dict(plan_hash=k.digest(self.root / plan_path), baseline_hash=k.digest(self.root / plan['baseline']))
        self.put(self.root / plan['review'], dict(schema=1, **identity, criteria={key: dict(status='PASS',
            reason='Synthetic test assessment, not a semantic review', evidence=['fixture']) for key in k.CRITERIA}))
        self.put(self.root / plan['approval'], dict(schema=1, **identity,
            decision='SYNTHETIC user approval', approved_at='2026-09-27'))
        return plan_path, plan, audit

    def test_real_revision_audit_manifest_and_split_plan(self):
        self.build()
        path, plan, audit = self.audit_plan()
        self.assertEqual(k.check(self.root, path, True)[1], 0)
        docs = a.read_json(audit / 'manifest.json')['documents']
        self.assertTrue(any(d['path'] == plan['snapshot'] and d['availability'] == 'readable' for d in docs))
        self.assertTrue(any(d['path'] == 'docs/specification/policy.json' for d in docs))
        (self.store / 'policy.json').write_text('{}', encoding='utf-8')
        self.assertEqual(a.verify(self.root, audit / 'manifest.json')[0], 1)
        self.assertEqual(k.check(self.root, path, True)[1], 1)

    def test_extended_profile_hands_architecture_to_kickoff(self):
        self.build(profile='extended')
        path, plan, audit = self.audit_plan()
        self.assertEqual(k.check(self.root, path, True)[1], 0)
        docs = {d['path'] for d in a.read_json(audit / 'manifest.json')['documents']}
        self.assertTrue({'docs/01-requirements.md', 'docs/02-architecture.md', 'docs/03-design.md'} <= docs)

    def test_external_exploration_survives_entire_handoff(self):
        self.build(external=True)
        path, _, _ = self.audit_plan()
        self.assertFalse((self.root / 'docs/00-exploration.md').exists())
        self.assertTrue(self.call('status')['approved'])
        self.assertEqual(k.check(self.root, path, True)[1], 0)

    def test_repair_through_specify_then_reaudit_invalidates_old_plan(self):
        self.build()
        old_path, _, old_audit = self.audit_plan()
        old_revision = s.current(self.store)
        folder = self.root / 'packages/fix'
        self.call('begin', '--stage', 'DESIGN', '--contract', str(self.contract), '--work', str(folder))
        snap = s.load(folder / 'candidate.json')
        snap['entities']['O-1']['data']['outcome'] = 'valid file with explicit empty marker'
        for sid in ('S-1', 'S-2'):
            snap['entities'][sid]['data']['then'] = 'valid file with explicit empty marker'
        self.put(folder / 'candidate.json', snap)
        self.review_accept(folder)
        self.assertFalse(self.call('status')['approved'])
        self.assertNotEqual(s.current(self.store), old_revision)
        self.assertEqual(a.verify(self.root, old_audit / 'manifest.json')[0], 1)
        self.assertEqual(k.check(self.root, old_path, True)[1], 1)
        self.call('approve', '--stage', 'DESIGN', '--decision', 'SYNTHETIC approval of fixed edition')
        new_path, _, _ = self.audit_plan()
        self.assertEqual(k.check(self.root, new_path, True)[1], 0)
        snapshot, manifest = s.read_revision(self.store)
        self.assertEqual(snapshot['entities']['O-1']['data']['outcome'], 'valid file with explicit empty marker')
        self.assertEqual(set(snapshot['documents']), {'REQ', 'DESIGN'})
        for stage in snapshot['documents']:
            self.assertEqual(k.digest(self.root / 'docs' / s.DOCUMENT_FILES[stage]), manifest['files'][s.DOCUMENT_FILES[stage]])

    def test_future_idea_can_remain_outside_obligations_and_modules(self):
        self.build()
        snapshot, _ = s.read_revision(self.store)
        self.assertEqual({key for key, e in snapshot['entities'].items() if e['kind'] == 'obligation'}, {'O-1'})
        self.assertEqual({key for key, e in snapshot['entities'].items() if e['kind'] == 'module'}, {'MODULE-1'})
        self.assertIn('without commitment', snapshot['entities']['D-SCOPE']['data']['selected'])


if __name__ == '__main__':
    unittest.main()
