"""Meaningful engine regression tests; no live project changes or LLM calls."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import specctl as s


class Transactions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.root = self.home / 'store'
        self.exploration = self.home / '00-exploration.md'
        self.exploration.write_text('# Exploration\nThe user can export collections.\n', encoding='utf-8')
        self.call('init')
        text = self.home / 'needs.txt'
        text.write_text('The user can export an empty collection as a valid file.', encoding='utf-8')
        self.source = json.loads(self.call('source', '--id', 'SRC-1', '--file', str(text)))
        self.contract = self.home / 'contract.json'
        self.save(self.contract, {'mode': 'stage-review', 'goal': 'Define export outcome', 'scope': ['BR-1'], 'constraints': ['Preserve empty export'],
                                  'freedom': ['Wording'], 'outputs': ['BRD', 'BR-1', 'SC-1'], 'checks': list(s.CRITERIA), 'unknowns': []})

    def save(self, path, obj):
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

    def call(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = s.main(['--root', str(self.root), *args])
        self.assertEqual(code, 0, output.getvalue())
        return output.getvalue()

    def entity(self, key, kind, data, basis=None, stage='BRD'):
        return {'id': key, 'kind': kind, 'stage': stage, 'status': 'active',
                'statement': 'Export empty collection correctly: ' + key, 'basis': basis or ['SRC-1'], 'data': data}

    def package(self, name='package'):
        folder = self.home / name
        self.call('begin', '--stage', 'BRD', '--contract', str(self.contract), '--work', str(folder))
        snapshot = s.load(folder / 'candidate.json')
        snapshot['entities'].update({'SRC-1': self.source,
            'BR-1': self.entity('BR-1', 'obligation', {'actor': 'user', 'trigger': 'export', 'precondition': 'collection exists',
                'action': 'export', 'outcome': 'valid file', 'exceptions': [], 'limits': {}, 'phase': 'v1', 'modality': 'must'}),
            'SC-1': self.entity('SC-1', 'scenario', {'given': 'empty collection', 'when': 'export', 'then': 'valid empty file',
                'distinguishes': 'Rejects implementation that silently creates no file'}, ['BR-1'])})
        snapshot['edges'] = {'E-1': {'id': 'E-1', 'from': 'SC-1', 'to': 'BR-1', 'type': 'verifies',
                                   'due_stage': 'BRD', 'rationale': 'Empty input still produces the promised output'}}
        snapshot['documents'] = {'BRD': {'title': 'Export requirements', 'sections': [
            {'id': 'scope', 'title': 'Scope and acceptance', 'prose': 'Export includes an empty collection.', 'entities': ['BR-1', 'SC-1']}]}}
        self.save(folder / 'candidate.json', snapshot)
        return folder

    def reviewed(self, folder):
        self.call('prepare-review', '--package', str(folder))
        review = s.load(folder / 'review.json')
        review['reviewer'] = 'Regression fixture; synthetic assessment, not an LLM review'
        for assessment in [*review['criteria'].values(), *review['edges'].values()]:
            assessment.update(status='PASS', reason='Fixture assessment of empty export with distinguishing scenario', evidence=['BR-1', 'SC-1'])
        self.save(folder / 'review.json', review)
        return review

    def test_accept_renders_consistent_documents_and_rtm_without_approval(self):
        folder = self.package()
        self.reviewed(folder)
        result = json.loads(self.call('accept', '--package', str(folder)))
        revision = self.root / 'revisions' / result['revision']
        self.assertIn('valid file', (revision / '01-BRD.md').read_text(encoding='utf-8'))
        self.assertEqual((self.home/'01-BRD.md').read_bytes(), (revision/'01-BRD.md').read_bytes())
        self.assertIn('PASS', (revision / 'RTM.md').read_text(encoding='utf-8'))
        self.assertEqual(result['gates']['runtime'], 'UNKNOWN')
        self.assertFalse(json.loads(self.call('status'))['approved'])
        self.call('approve', '--stage', 'BRD', '--decision', 'Test user explicitly approves BRD')
        self.assertTrue(json.loads(self.call('status'))['approved'])

    def test_init_requires_exploration_and_preserves_its_bytes(self):
        snapshot, _ = s.read_revision(self.root)
        source = snapshot['entities']['SRC-EXPLORATION']
        self.assertEqual(source['data']['role'], 'exploration')
        self.assertEqual((self.root/'sources'/(source['data']['sha256']+'.txt')).read_bytes(), self.exploration.read_bytes())
        missing = self.home/'other'/'store'
        with self.assertRaisesRegex(s.Invalid, 'Missing 00-exploration'):
            s.main(['--root', str(missing), 'init'])
        self.assertFalse(missing.exists())
        with contextlib.redirect_stdout(io.StringIO()):
            s.main(['--root', str(missing), 'init', '--exploration', str(self.exploration)])
        self.assertEqual(s.read_revision(missing)[0]['entities']['SRC-EXPLORATION']['data']['sha256'], source['data']['sha256'])

    def test_no_semantic_review_is_not_success(self):
        folder = self.package()
        self.call('check', '--package', str(folder))
        self.call('prepare-review', '--package', str(folder))
        review = s.load(folder / 'review.json')
        review['reviewer'] = 'reviewer'
        self.save(folder / 'review.json', review)
        self.assertEqual(s.review_gate(self.root, folder)[0]['gate'], 'UNKNOWN')
        old = s.current(self.root)
        with self.assertRaises(s.Invalid):
            self.call('accept', '--package', str(folder))
        self.assertEqual(s.current(self.root), old)

    def test_candidate_contract_and_policy_changes_stale_review(self):
        for field in ('candidate.json', 'contract.json', 'policy'):
            with self.subTest(field=field):
                folder = self.package(field.replace('.', '-'))
                self.reviewed(folder)
                path = self.root / 'policy.json' if field == 'policy' else folder / field
                value = s.load(path)
                if field == 'policy':
                    value['stages']['BRD']['runtime_required'] = True
                elif field == 'contract.json':
                    value['goal'] = 'Changed goal'
                else:
                    value['entities']['BR-1']['data']['outcome'] = 'different output'
                self.save(path, value)
                with self.assertRaisesRegex(s.Invalid, 'STALE'):
                    s.review_gate(self.root, folder)

    def test_competing_package_cannot_overwrite_revision(self):
        a, b = self.package('a'), self.package('b')
        self.reviewed(a); self.reviewed(b)
        self.call('accept', '--package', str(a))
        with self.assertRaisesRegex(s.Invalid, 'STALE BASE'):
            self.call('accept', '--package', str(b))

    def test_stage_transition_requires_approval_and_cannot_skip(self):
        folder = self.package(); self.reviewed(folder)
        self.call('accept', '--package', str(folder))
        for stage in ('TRD', 'SAD'):
            with self.assertRaises(s.Invalid):
                self.call('begin', '--stage', stage, '--contract', str(self.contract), '--work', str(self.home/stage))
        self.call('approve', '--stage', 'BRD', '--decision', 'Explicit test approval')
        self.call('begin', '--stage', 'TRD', '--contract', str(self.contract), '--work', str(self.home/'trd-ok'))

    def test_missing_scenario_dangling_link_and_circular_origin_rejected(self):
        folder = self.package()
        baseline = s.load(folder/'candidate.json')
        for defect in ('scenario', 'dangling', 'cycle', 'empty'):
            snapshot = copy.deepcopy(baseline)
            if defect == 'scenario':
                snapshot['edges'] = {}
            elif defect == 'dangling':
                snapshot['edges']['E-1']['to'] = 'MISSING'
            elif defect == 'cycle':
                snapshot['entities']['BR-1']['basis'] = ['SC-1']
            else:
                snapshot['entities'] = {}; snapshot['edges'] = {}; snapshot['documents']['BRD']['sections'][0]['entities'] = []
            with self.subTest(defect=defect), self.assertRaises(s.Invalid):
                s.validate(self.root, snapshot)

    def test_impact_includes_dependent_scenario_and_document(self):
        folder = self.package()
        old = s.load(folder/'candidate.json'); changed = copy.deepcopy(old)
        changed['entities']['BR-1']['data']['outcome'] = 'new file format'
        report = s.impact(old, changed)
        self.assertIn('SC-1', report['affected_entities'])
        self.assertIn('BRD', report['affected_documents'])

    def test_gate_findings_and_future_edge(self):
        folder = self.package()
        snapshot = s.load(folder/'candidate.json')
        snapshot['edges']['FUTURE'] = {'id': 'FUTURE', 'type': 'refines', 'from': 'SC-1', 'to': 'BR-1', 'due_stage': 'DDD', 'rationale': 'Future elaboration'}
        self.save(folder/'candidate.json', snapshot)
        review = self.reviewed(folder)
        review['edges']['FUTURE'] = {'status': 'NOT_APPLICABLE', 'reason': 'Future phase', 'evidence': []}
        self.save(folder/'review.json', review)
        self.assertEqual(s.review_gate(self.root, folder)[0]['gate'], 'PASS')
        review['findings'] = [{'id': 'F-1', 'kind': 'contract_gap', 'severity': 'Medium', 'state': 'open', 'reason': 'Two possible empty file formats', 'sources': ['BR-1'], 'counterexample': 'Both empty bytes and empty array permitted', 'closure': 'Choose a format'}]
        self.save(folder/'review.json', review)
        self.assertEqual(s.review_gate(self.root, folder)[0]['gate'], 'FAIL')

    def test_runtime_pass_cannot_be_claimed_from_scenario(self):
        folder = self.package(); review = self.reviewed(folder)
        review['runtime'] = {'status': 'PASS', 'reason': 'Scenario exists', 'evidence': ['SC-1']}
        self.save(folder/'review.json', review)
        with self.assertRaisesRegex(s.Invalid, 'executed evidence'):
            s.review_gate(self.root, folder)

    def test_published_manual_edit_detected(self):
        folder = self.package(); self.reviewed(folder)
        result = json.loads(self.call('accept', '--package', str(folder)))
        doc = self.root/'revisions'/result['revision']/'01-BRD.md'
        doc.write_text('Changed manually', encoding='utf-8')
        with self.assertRaisesRegex(s.Invalid, 'edited'):
            self.call('status')

    def test_interrupted_publication_preserves_previous_current(self):
        folder = self.package(); self.reviewed(folder)
        before = s.current(self.root)
        with patch.object(s.os, 'replace', side_effect=OSError('Simulated interruption')):
            with self.assertRaises(OSError):
                self.call('accept', '--package', str(folder))
        self.assertEqual(s.current(self.root), before)
        self.assertFalse((self.root/'WRITE.lock').exists())
        s.read_revision(self.root, check_exports=False)
        with self.assertRaisesRegex(s.Invalid, 'interrupted'):
            self.call('status')
        self.call('sync-docs')
        self.assertNotEqual(s.current(self.root), before)
        s.read_revision(self.root)

    def test_existing_top_level_document_is_not_overwritten(self):
        folder = self.package(); self.reviewed(folder)
        path = self.home/'01-BRD.md'; path.write_text('User document', encoding='utf-8')
        before = s.current(self.root)
        with self.assertRaisesRegex(s.Invalid, 'overwrite'):
            self.call('accept', '--package', str(folder))
        self.assertEqual(path.read_text(encoding='utf-8'), 'User document')
        self.assertEqual(s.current(self.root), before)

    def test_manual_top_level_edit_blocks_status_and_sync(self):
        folder = self.package(); self.reviewed(folder); self.call('accept', '--package', str(folder))
        path = self.home/'01-BRD.md'; path.write_text('Manual edit', encoding='utf-8')
        with self.assertRaisesRegex(s.Invalid, 'edited'):
            self.call('status')
        with self.assertRaisesRegex(s.Invalid, 'unrecognized edits'):
            self.call('sync-docs')
        self.assertEqual(path.read_text(encoding='utf-8'), 'Manual edit')

    def test_missing_top_level_document_is_restored(self):
        folder = self.package(); self.reviewed(folder); self.call('accept', '--package', str(folder))
        path = self.home/'01-BRD.md'; original = path.read_bytes(); path.unlink()
        self.call('sync-docs')
        self.assertEqual(path.read_bytes(), original)
        s.read_revision(self.root)

    def test_interruption_after_documents_before_current_is_recoverable(self):
        folder = self.package(); self.reviewed(folder)
        before = s.current(self.root)
        original = s.atomic_bytes
        def interrupted(path, data):
            if path.name == 'CURRENT':
                raise OSError('Before pointer switch')
            return original(path, data)
        with patch.object(s, 'atomic_bytes', side_effect=interrupted):
            with self.assertRaises(OSError):
                self.call('accept', '--package', str(folder))
        self.assertTrue((self.home/'01-BRD.md').is_file())
        self.assertEqual(s.current(self.root), before)
        self.call('sync-docs')
        s.read_revision(self.root)

    def test_lock_and_work_directory_are_not_overwritten(self):
        folder = self.package(); self.reviewed(folder)
        with s.locked(self.root):
            with self.assertRaisesRegex(s.Invalid, 'lock'):
                self.call('accept', '--package', str(folder))
        with self.assertRaises(FileExistsError):
            self.call('begin', '--stage', 'BRD', '--contract', str(self.contract), '--work', str(folder))

    def test_source_tampering_and_unsafe_identifier_rejected(self):
        folder = self.package()
        source = self.root/'sources'/(self.source['data']['sha256']+'.txt')
        source.write_text('changed', encoding='utf-8')
        with self.assertRaisesRegex(s.Invalid, 'source snapshot'):
            self.call('check', '--package', str(folder))
        with self.assertRaises(s.Invalid):
            s.token('../escape')

    def test_cli_error_has_nonzero_exit_and_json(self):
        p = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(Path(s.__file__)), '--root', str(self.home/'missing'), 'status'], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(p.returncode, 2)
        self.assertEqual(json.loads(p.stderr)['gate'], 'UNKNOWN')

    def test_fragment_cannot_be_user_approved(self):
        contract = s.load(self.contract); contract['mode'] = 'fragment'; self.save(self.contract, contract)
        folder = self.package(); self.reviewed(folder)
        self.call('accept', '--package', str(folder))
        with self.assertRaisesRegex(s.Invalid, 'stage-review'):
            self.call('approve', '--stage', 'BRD', '--decision', 'test')

    def test_required_runtime_unknown_blocks_acceptance(self):
        policy = s.load(self.root/'policy.json'); policy['stages']['BRD']['runtime_required'] = True
        self.save(self.root/'policy.json', policy)
        folder = self.package(); self.reviewed(folder)
        self.assertEqual(s.review_gate(self.root, folder)[0]['gate'], 'UNKNOWN')

    def test_all_five_stages_and_backchannel_revision(self):
        folder = self.package()
        for stage in s.STAGES:
            if stage != 'BRD':
                folder = self.home/stage
                self.call('begin', '--stage', stage, '--contract', str(self.contract), '--work', str(folder))
                snapshot = s.load(folder/'candidate.json')
                kind = {'TRD': 'contract', 'SAD': 'component', 'SDD': 'module', 'DDD': 'task'}[stage]
                key = kind.upper() + '-1'
                snapshot['entities'][key] = self.entity(key, kind, {'responsibility': 'empty export'}, ['BR-1'], stage)
                snapshot['documents'][stage] = {'title': stage, 'sections': [{'id': 'design', 'title': 'Design', 'prose': 'Fixture only', 'entities': [key]}]}
                self.save(folder/'candidate.json', snapshot)
            self.reviewed(folder)
            self.call('accept', '--package', str(folder))
            self.call('approve', '--stage', stage, '--decision', 'Synthetic explicit approval of ' + stage)
        previous = s.current(self.root)
        folder = self.home/'backchannel'
        self.call('begin', '--stage', 'DDD', '--contract', str(self.contract), '--work', str(folder))
        snapshot = s.load(folder/'candidate.json')
        snapshot['entities']['BR-1']['data']['outcome'] = 'valid file with explicit empty marker'
        self.save(folder/'candidate.json', snapshot)
        affected = json.loads(self.call('impact', '--package', str(folder)))
        self.assertEqual(set(affected['affected_documents']), set(s.STAGES))
        self.reviewed(folder)
        self.call('accept', '--package', str(folder))
        self.assertNotEqual(s.current(self.root), previous)
        self.assertFalse(json.loads(self.call('status'))['approved'])
        self.assertTrue((self.root/'revisions'/previous/'05-DDD.md').is_file())

    def test_supersession_and_history_are_explicit(self):
        folder = self.package(); self.reviewed(folder); self.call('accept', '--package', str(folder))
        folder = self.home/'change'
        self.call('begin', '--stage', 'BRD', '--contract', str(self.contract), '--work', str(folder))
        value = s.load(folder/'candidate.json')
        del value['entities']['SC-1']; self.save(folder/'candidate.json', value)
        with self.assertRaisesRegex(s.Invalid, 'delete'):
            s.candidate(self.root, folder)

    def test_unknown_priority_field_cannot_silently_change_semantics(self):
        spec = DecisionTables().spec()
        spec['data']['rules'][0]['overrides'] = ['other']
        with self.assertRaisesRegex(s.Invalid, 'Unsupported rule'):
            s.decision_check(spec)

    def test_runtime_evidence_must_cover_current_entity_hashes(self):
        folder = self.package()
        snapshot = s.load(folder/'candidate.json')
        report = self.home/'execution.txt'; report.write_text('Synthetic fixture: command completed with exit 0', encoding='utf-8')
        imported = json.loads(self.call('source', '--id', 'LOG-1', '--file', str(report)))
        snapshot['entities']['LOG-1'] = imported
        snapshot['entities']['EV-1'] = self.entity('EV-1', 'evidence', {
            'level': 'implementation_test', 'executed': True, 'command': 'synthetic-fixture-command', 'exit_code': 0,
            'targets': {'BR-1': s.digest(snapshot['entities']['BR-1'])}}, ['LOG-1'])
        snapshot['documents']['BRD']['sections'][0]['entities'].append('EV-1')
        self.save(folder/'candidate.json', snapshot)
        review = self.reviewed(folder)
        review['runtime'] = {'status': 'PASS', 'reason': 'Synthetic external execution fixture', 'evidence': ['EV-1']}
        self.save(folder/'review.json', review)
        self.assertEqual(s.review_gate(self.root, folder)[0]['gates']['runtime'], 'PASS')
        new = self.home/'changed-evidence'
        self.call('begin', '--stage', 'BRD', '--contract', str(self.contract), '--work', str(new))
        snapshot['entities']['BR-1']['data']['outcome'] = 'new format'
        self.save(new/'candidate.json', snapshot)
        review = self.reviewed(new); review['runtime'] = {'status': 'PASS', 'reason': 'Old evidence reused', 'evidence': ['EV-1']}
        self.save(new/'review.json', review)
        with self.assertRaisesRegex(s.Invalid, 'targets missing or stale'):
            s.review_gate(self.root, new)

    def test_open_finding_cannot_disappear_between_revisions(self):
        folder = self.package(); review = self.reviewed(folder)
        review['findings'] = [{'id': 'H-1', 'kind': 'hypothesis', 'severity': 'Low', 'state': 'open',
                               'reason': 'Potential future export size risk', 'sources': ['BR-1']}]
        self.save(folder/'review.json', review); self.call('accept', '--package', str(folder))
        new = self.home/'next'
        self.call('begin', '--stage', 'BRD', '--contract', str(self.contract), '--work', str(new))
        review = self.reviewed(new)
        self.assertEqual(review['findings'][0]['id'], 'H-1')
        review['findings'] = []; self.save(new/'review.json', review)
        with self.assertRaisesRegex(s.Invalid, 'Previously open'):
            s.review_gate(self.root, new)


class DecisionTables(unittest.TestCase):
    def spec(self):
        return {'id': 'B-1', 'data': {'representation': 'decision_table', 'factors': {'empty': [True, False]},
                'slots': {'result': 'required'}, 'rules': [{'when': {}, 'effects': {'result': 'file'}}]}}

    def test_valid_conflict_and_gap(self):
        spec = self.spec()
        self.assertEqual(s.decision_check(spec)['status'], 'PASS')
        spec['data']['rules'].append({'when': {'empty': [True]}, 'effects': {'result': 'no file'}})
        self.assertEqual(s.decision_check(spec)['examples'][0]['kind'], 'CONFLICT')
        spec['data']['rules'] = []
        self.assertEqual(s.decision_check(spec)['examples'][0]['kind'], 'UNDEFINED')

    def test_empty_domain_and_invalid_restriction_rejected(self):
        spec = self.spec(); spec['data']['factors']['empty'] = []
        with self.assertRaises(s.Invalid):
            s.decision_check(spec)
        spec = self.spec(); spec['data'].update(allowed_cells=[], exclusion_reason='exclude everything')
        with self.assertRaises(s.Invalid):
            s.decision_check(spec)

    def test_unimplemented_model_is_unknown_not_pass(self):
        spec = self.spec(); spec['data']['representation'] = 'state_machine'
        self.assertEqual(s.decision_check(spec)['status'], 'UNKNOWN')


if __name__ == '__main__':
    unittest.main()
