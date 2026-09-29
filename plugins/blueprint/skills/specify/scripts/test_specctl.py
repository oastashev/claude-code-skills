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
        return self.fill(folder)

    def fill(self, folder):
        review = s.load(folder / 'review.json')
        review['reviewer'] = 'Regression fixture; synthetic assessment, not an LLM review'
        for assessment in [*review['criteria'].values(), *review['edges'].values()]:
            if assessment['status'] == 'UNKNOWN':
                assessment.update(status='PASS', reason='Fixture assessment of empty export with distinguishing scenario', evidence=['BR-1', 'SC-1'])
        self.save(folder / 'review.json', review)
        return review

    def fragment(self):
        contract = s.load(self.contract); contract['mode'] = 'fragment'; self.save(self.contract, contract)

    def with_second_scenario(self, folder):
        snapshot = s.load(folder / 'candidate.json')
        snapshot['entities']['SC-2'] = self.entity('SC-2', 'scenario', {'given': 'one item', 'when': 'export', 'then': 'file with one item',
            'distinguishes': 'Rejects implementation that drops the last item'}, ['BR-1'])
        snapshot['edges']['E-2'] = {'id': 'E-2', 'from': 'SC-2', 'to': 'BR-1', 'type': 'verifies', 'due_stage': 'BRD', 'rationale': 'Boundary of one item'}
        snapshot['documents']['BRD']['sections'][0]['entities'].append('SC-2')
        self.save(folder / 'candidate.json', snapshot)
        return snapshot

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

    def test_state_machine_defect_blocks_review_and_pass_supports_formal(self):
        folder = self.package()
        snapshot = s.load(folder / 'candidate.json')
        machine = StateMachines().spec()
        snapshot['entities']['BH-RUN'] = self.entity('BH-RUN', 'behavior', machine['data'], ['BR-1'])
        snapshot['documents']['BRD']['sections'][0]['entities'].append('BH-RUN')
        broken = copy.deepcopy(snapshot); del broken['entities']['BH-RUN']['data']['ignored'][0]
        self.save(folder / 'candidate.json', broken)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(s.main(['--root', str(self.root), 'check', '--package', str(folder)]), 1)
        self.assertEqual(json.loads(output.getvalue())['models'][0]['examples'][0]['kind'], 'UNDEFINED')
        self.save(folder / 'candidate.json', snapshot)
        review = self.reviewed(folder)
        review['formal'] = {'status': 'PASS', 'reason': 'Built-in state-machine check passed', 'evidence': ['mechanical-report']}
        self.save(folder / 'review.json', review)
        self.assertEqual(s.review_gate(self.root, folder)[0]['gates']['formal'], 'PASS')

    def test_fragment_inherits_pass_only_for_unchanged_edges(self):
        self.fragment()
        folder = self.package(); self.reviewed(folder); accepted = json.loads(self.call('accept', '--package', str(folder)))['revision']
        added = self.home / 'added'
        self.call('begin', '--stage', 'BRD', '--contract', str(self.contract), '--work', str(added))
        self.with_second_scenario(added)
        self.call('prepare-review', '--package', str(added))
        edges = s.load(added / 'review.json')['edges']
        self.assertEqual((edges['E-1']['status'], edges['E-1']['inherited']), ('PASS', 'revision:' + accepted))
        self.assertEqual(edges['E-2']['status'], 'UNKNOWN')
        brief = (added / 'review-brief.md').read_text(encoding='utf-8')
        self.assertIn('- E-2: verifies SC-2 → BR-1', brief)
        self.assertNotIn('- E-1:', brief)
        self.fill(added)
        self.assertEqual(s.review_gate(self.root, added)[0]['gate'], 'PASS')
        changed = self.home / 'changed'
        self.call('begin', '--stage', 'BRD', '--contract', str(self.contract), '--work', str(changed))
        snapshot = s.load(changed / 'candidate.json'); snapshot['entities']['BR-1']['data']['outcome'] = 'file with header'
        self.save(changed / 'candidate.json', snapshot)
        self.call('prepare-review', '--package', str(changed))
        self.assertNotIn('inherited', s.load(changed / 'review.json')['edges']['E-1'])

    def test_inherited_assessment_cannot_be_forged_or_used_in_stage_review(self):
        self.fragment()
        folder = self.package(); self.reviewed(folder); self.call('accept', '--package', str(folder))
        added = self.home / 'added'
        self.call('begin', '--stage', 'BRD', '--contract', str(self.contract), '--work', str(added))
        self.with_second_scenario(added)
        review = self.reviewed(added)
        for forged in ('altered', 'minted'):
            attempt = copy.deepcopy(review)
            if forged == 'altered':
                attempt['edges']['E-1']['reason'] = 'Silently rewritten while claiming inheritance'
            else:
                attempt['edges']['E-2']['inherited'] = attempt['edges']['E-1']['inherited']
            self.save(added / 'review.json', attempt)
            with self.subTest(forged=forged), self.assertRaisesRegex(s.Invalid, 'Inherited assessment'):
                s.review_gate(self.root, added)
        contract = s.load(self.contract); contract['mode'] = 'stage-review'; self.save(self.contract, contract)
        final = self.home / 'final'
        self.call('begin', '--stage', 'BRD', '--contract', str(self.contract), '--work', str(final))
        self.call('prepare-review', '--package', str(final))
        self.assertEqual(s.load(final / 'review.json')['edges']['E-1']['status'], 'UNKNOWN')

    def test_begin_from_unaccepted_package_carries_work_and_review(self):
        self.fragment()
        first = self.package(); review = self.reviewed(first)
        review['findings'] = [{'id': 'F-1', 'kind': 'contract_gap', 'severity': 'Medium', 'state': 'open', 'reason': 'Two empty formats',
                               'sources': ['BR-1'], 'counterexample': 'Empty bytes and empty array both pass', 'closure': 'Choose one format'}]
        self.save(first / 'review.json', review)
        self.assertEqual(s.review_gate(self.root, first)[0]['gate'], 'FAIL')
        fixed = self.home / 'fixed'
        self.call('begin', '--stage', 'BRD', '--from', str(first), '--work', str(fixed))
        self.assertEqual(s.load(fixed / 'contract.json'), s.load(first / 'contract.json'))
        self.with_second_scenario(fixed)
        self.assertEqual(json.loads(self.call('diff', '--package', str(fixed)))['previous']['new_entities'], ['SC-2'])
        self.call('prepare-review', '--package', str(fixed))
        carried = s.load(fixed / 'review.json')
        self.assertEqual(carried['edges']['E-1']['inherited'], 'package:' + s.load(first / 'package.json')['id'])
        self.assertEqual([f['id'] for f in carried['findings']], ['F-1'])
        self.fill(fixed)
        carried = s.load(fixed / 'review.json'); carried['findings'] = []; self.save(fixed / 'review.json', carried)
        with self.assertRaisesRegex(s.Invalid, 'Previously open'):
            s.review_gate(self.root, fixed)
        other = self.package('other'); self.reviewed(other); self.call('accept', '--package', str(other))
        with self.assertRaisesRegex(s.Invalid, 'STALE BASE'):
            self.call('begin', '--stage', 'BRD', '--from', str(first), '--work', str(self.home / 'late'))


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
        spec = self.spec(); spec['data']['representation'] = 'sequence'
        self.assertEqual(s.model_check(spec)['status'], 'UNKNOWN')


class StateMachines(unittest.TestCase):
    def spec(self):
        return {'id': 'BH-RUN', 'data': {'representation': 'state_machine', 'states': ['created', 'running', 'exited'],
                'initial': 'created', 'terminal': ['exited'], 'events': ['start', 'fail', 'abort'],
                'guards': {'attempts': ['below-limit', 'at-limit']},
                'transitions': [
                    {'from': 'created', 'on': 'start', 'to': 'running'},
                    {'from': 'running', 'on': 'fail', 'when': {'attempts': ['below-limit']}, 'to': 'running', 'effects': {'attempts': '+1'}},
                    {'from': 'running', 'on': 'fail', 'when': {'attempts': ['at-limit']}, 'to': 'exited'},
                    {'from': ['created', 'running'], 'on': 'abort', 'to': 'exited'}],
                'ignored': [{'states': 'created', 'events': 'fail', 'reason': 'Nothing runs before start'},
                            {'states': 'running', 'events': 'start', 'reason': 'Start is idempotent while running'}]}}

    def problems(self, spec):
        result = s.model_check(spec)
        return result['status'], {(p['kind'], p['state'], p.get('event'), canonical_cell(p.get('cell'))) for p in result['examples']}

    def test_complete_deterministic_machine_passes(self):
        self.assertEqual(s.model_check(self.spec())['status'], 'PASS')

    def test_unhandled_guard_cell_is_undefined(self):
        spec = self.spec(); del spec['data']['transitions'][2]
        self.assertEqual(self.problems(spec), ('FAIL', {('UNDEFINED', 'running', 'fail', '{"attempts":"at-limit"}')}))

    def test_overlapping_outcomes_and_ignored_handled_event_conflict(self):
        spec = self.spec(); spec['data']['transitions'].append({'from': 'running', 'on': 'abort', 'to': 'created'})
        self.assertIn(('CONFLICT', 'running', 'abort', '{"attempts":"at-limit"}'), self.problems(spec)[1])
        spec = self.spec(); spec['data']['transitions'][1]['effects'] = {'attempts': 'unchanged'}
        spec['data']['transitions'].append({'from': 'running', 'on': 'fail', 'when': {'attempts': ['below-limit']}, 'to': 'running', 'effects': {'attempts': '+1'}})
        self.assertIn(('CONFLICT', 'running', 'fail', '{"attempts":"below-limit"}'), self.problems(spec)[1])
        spec = self.spec(); spec['data']['ignored'].append({'states': 'running', 'events': 'abort', 'reason': 'Contradicts the abort rule'})
        self.assertEqual(self.problems(spec)[0], 'FAIL')

    def test_state_without_exit_is_trap_and_orphan_is_unreachable(self):
        spec = self.spec(); data = spec['data']
        data['states'] += ['stopping', 'orphan']
        data['transitions'][3]['from'] = 'created'
        data['transitions'].append({'from': 'running', 'on': 'abort', 'to': 'stopping'})
        data['ignored'].append({'states': ['stopping', 'orphan'], 'events': ['start', 'fail', 'abort'], 'reason': 'Waiting'})
        kinds = {(k, st) for k, st, _, _ in self.problems(spec)[1]}
        self.assertEqual(kinds, {('TRAP', 'stopping'), ('UNREACHABLE', 'orphan')})

    def test_cyclic_machine_must_return_to_initial(self):
        spec = {'id': 'BH-ENV', 'data': {'representation': 'state_machine', 'states': ['ok', 'failing'], 'initial': 'ok', 'terminal': [],
                'events': ['failure', 'recovered'], 'transitions': [
                    {'from': ['ok', 'failing'], 'on': 'failure', 'to': 'failing'}, {'from': 'failing', 'on': 'recovered', 'to': 'ok'}],
                'ignored': [{'states': 'ok', 'events': 'recovered', 'reason': 'Nothing to recover'}]}}
        self.assertEqual(s.model_check(spec)['status'], 'PASS')
        spec['data']['transitions'][1]['to'] = 'failing'
        self.assertIn(('TRAP', 'failing', None, 'null'), self.problems(spec)[1])

    def test_free_form_machine_stays_unknown_with_hints(self):
        spec = {'id': 'BH-OLD', 'data': {'representation': 'state_machine', 'initial': 'start', 'terminal': ['done'], 'transitions': [
            {'from': 'start', 'on': 'push accepted', 'to': 'apply'}, {'from': 'apply', 'on': 'attempts = N', 'to': 'stopping'},
            {'from': 'apply', 'on': 'finished', 'to': 'done'}]}}
        result = s.model_check(spec)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertIn('No outgoing transition and not terminal: stopping', result['hints'])

    def test_malformed_machine_rejected(self):
        for defect in ('event', 'composite', 'terminal', 'guard', 'field'):
            spec = self.spec(); data = spec['data']
            if defect == 'event':
                data['transitions'][0]['on'] = 'launch'
            elif defect == 'composite':
                data['transitions'][0]['to'] = 'parked→queued'
            elif defect == 'terminal':
                data['transitions'].append({'from': 'exited', 'on': 'start', 'to': 'running'})
            elif defect == 'guard':
                data['transitions'][1]['when'] = {'attempts': ['attempts < N']}
            else:
                data['transitions'][0]['priority'] = 1
            with self.subTest(defect=defect), self.assertRaises(s.Invalid):
                s.model_check(spec)


def canonical_cell(cell):
    return s.canonical(cell)


if __name__ == '__main__':
    unittest.main()
