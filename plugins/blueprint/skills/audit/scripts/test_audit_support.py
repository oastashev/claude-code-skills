"""Run: python -m unittest discover -s SKILL_DIR/scripts -p test_*.py"""
import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from audit_support import collect, compare, index_lines, verify


class AuditSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def config(self, documents):
        path = self.root / 'input.json'
        path.write_text(json.dumps({'documents': documents}), encoding='utf-8')
        return path

    def test_ranges_and_fenced_examples(self):
        rows, warnings = index_lines(['FR-001…003', '```text', '| FR-999 | example |', '```',
                                      '| FR-002 | requirement |', 'FR-003–001'], ['FR'])
        self.assertEqual(rows[0]['ids'], ['FR-001', 'FR-002', 'FR-003'])
        self.assertEqual(rows[1]['context'], 'example')
        self.assertIsNone(rows[1]['definition_candidate'])
        self.assertEqual(rows[2]['definition_candidate'], 'FR-002')
        self.assertTrue(warnings)

    def test_snapshot_detects_mutation_deletion_and_new_evidence(self):
        file = self.root / 'trd.md'
        file.write_text('| FR-001 | shall act |', encoding='utf-8')
        config = self.config([{'path': 'trd.md', 'role': 'TRD'}])
        collect(self.root, config, self.root / 'one')
        self.assertEqual(verify(self.root, self.root / 'one/manifest.json')[0], 0)
        file.write_text('| FR-001 | shall wait |', encoding='utf-8')
        self.assertEqual(verify(self.root, self.root / 'one/manifest.json')[0], 1)
        collect(self.root, config, self.root / 'two')
        delta = compare(self.root / 'one/manifest.json', self.root / 'two/manifest.json')
        self.assertEqual(delta['changed'], ['trd.md'])
        file.unlink()
        self.assertEqual(verify(self.root, self.root / 'two/manifest.json')[0], 1)

    def test_literal_replacement_character_is_valid_utf8(self):
        (self.root / 'valid.md').write_bytes(b'\xef\xbf\xbd')
        (self.root / 'invalid.md').write_bytes(b'\xff')
        c = self.config([{'path': 'valid.md', 'role': 'TRD'}, {'path': 'invalid.md', 'role': 'SAD'},
                         {'path': 'missing.md', 'role': 'model'}])
        collect(self.root, c, self.root / 'run')
        docs = json.loads((self.root / 'run/manifest.json').read_text(encoding='utf-8'))['documents']
        self.assertEqual([d['availability'] for d in docs], ['readable', 'invalid_utf8', 'missing'])
        self.assertEqual(verify(self.root, self.root / 'run/manifest.json')[0], 2)
        (self.root / 'missing.md').write_text('provided now', encoding='utf-8')
        self.assertEqual(verify(self.root, self.root / 'run/manifest.json')[0], 1)

    def test_namespaces_and_candidate_duplicates_not_semantic_failures(self):
        for name in ('a.md', 'b.md'):
            (self.root / name).write_text('| FR-001 | definition |\n| FR-001 | matrix |', encoding='utf-8')
        c = self.config([{'path': 'a.md', 'role': 'TRD', 'namespace': 'a'},
                         {'path': 'b.md', 'role': 'TRD', 'namespace': 'b'}])
        result = collect(self.root, c, self.root / 'run')
        self.assertEqual(result['semantic_gate'], 'NOT_EVALUATED')
        checks = json.loads((self.root / 'run/structural-checks.json').read_text(encoding='utf-8'))
        duplicates = checks['duplicate_definition_candidates']
        self.assertEqual(len(duplicates), 2)
        self.assertEqual({d['namespace'] for d in duplicates}, {'a', 'b'})

    def test_output_reuse_and_path_escape_are_rejected_without_overwrite(self):
        p = self.root / 'trd.md'
        p.write_text('original', encoding='utf-8')
        c = self.config([{'path': 'trd.md', 'role': 'TRD'}])
        collect(self.root, c, self.root / 'run')
        with self.assertRaises(ValueError):
            collect(self.root, c, self.root / 'run')
        with self.assertRaises(ValueError):
            collect(self.root, c, p)
        c = self.config([{'path': '../outside.md', 'role': 'TRD'}])
        with self.assertRaises(ValueError):
            collect(self.root, c, self.root / 'escape')
        self.assertEqual(p.read_text(encoding='utf-8'), 'original')
        self.assertFalse((self.root / 'escape').exists())

    def test_metadata_change_is_distinct_from_byte_change(self):
        p = self.root / 'source.md'
        p.write_text('unchanged decision', encoding='utf-8')
        c = self.config([{'path': 'source.md', 'role': 'design', 'authority': 'historical'}])
        collect(self.root, c, self.root / 'old')
        c = self.config([{'path': 'source.md', 'role': 'design', 'authority': 'current'}])
        collect(self.root, c, self.root / 'new')
        delta = compare(self.root / 'old/manifest.json', self.root / 'new/manifest.json')
        self.assertEqual(delta['unchanged'], ['source.md'])
        self.assertEqual(delta['metadata_changed'], ['source.md'])

    def test_json_and_binary_integrity_are_separate_from_indexing(self):
        (self.root / 'snapshot.json').write_text('{"entities": {}}', encoding='utf-8')
        (self.root / 'evidence.bin').write_bytes(b'\xff\x00')
        config = self.config([{'path': 'snapshot.json', 'role': 'model'},
                              {'path': 'evidence.bin', 'role': 'evidence'}])
        collect(self.root, config, self.root / 'run')
        docs = json.loads((self.root / 'run/manifest.json').read_text(encoding='utf-8'))['documents']
        self.assertEqual([d['availability'] for d in docs], ['readable', 'available'])
        self.assertEqual(verify(self.root, self.root / 'run/manifest.json')[0], 0)
        (self.root / 'snapshot.json').write_text('{"entities": {"new": {}}}', encoding='utf-8')
        self.assertEqual(verify(self.root, self.root / 'run/manifest.json')[0], 1)

    def test_invalid_and_duplicate_key_json_are_incomplete(self):
        for name, body in [('syntax.json', '{'), ('duplicate.json', '{"x":1,"x":2}'), ('nan.json', '{"x":NaN}')]:
            (self.root / name).write_text(body, encoding='utf-8')
        config = self.config([{'path': name, 'role': 'model'} for name in ('syntax.json', 'duplicate.json', 'nan.json')])
        collect(self.root, config, self.root / 'run')
        result = verify(self.root, self.root / 'run/manifest.json')
        self.assertEqual(result[0], 2)
        self.assertEqual({i['availability'] for i in result[1]['incomplete']}, {'invalid_json'})

    def test_specification_binding_detects_policy_pointer_and_pending_changes(self):
        store = self.root / 'docs/specification'
        folder = store / 'revisions/r1'
        folder.mkdir(parents=True)
        (store / 'CURRENT').write_text('r1', encoding='utf-8')
        (store / 'policy.json').write_text('{}', encoding='utf-8')
        for name, body in [('snapshot.json', '{"entities":{},"documents":{"BRD":{}}}'),
                           ('review.json', '{}'), ('RTM.md', '# RTM'), ('01-BRD.md', '# BRD')]:
            (folder / name).write_text(body, encoding='utf-8')
        (store.parent / '01-BRD.md').write_text('# BRD', encoding='utf-8')
        hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
        (folder / 'manifest.json').write_text(json.dumps({'revision': 'r1', 'files': hashes}), encoding='utf-8')
        config = self.config([{'path': 'docs/01-BRD.md', 'role': 'BRD'}])
        config.write_text(json.dumps({'documents': [{'path': 'docs/01-BRD.md', 'role': 'BRD'}],
                                     'specification': {'store': 'docs/specification', 'revision': 'r1'}}), encoding='utf-8')
        collect(self.root, config, self.root / 'run')
        manifest = self.root / 'run/manifest.json'
        self.assertEqual(verify(self.root, manifest)[0], 0)
        (store / 'DOCS-PENDING.json').write_text('{}', encoding='utf-8')
        self.assertEqual(verify(self.root, manifest)[0], 2)
        (store / 'DOCS-PENDING.json').unlink()
        (store / 'policy.json').write_text('{"changed":true}', encoding='utf-8')
        self.assertEqual(verify(self.root, manifest)[0], 1)
        (store / 'CURRENT').write_text('r2', encoding='utf-8')
        self.assertEqual(verify(self.root, manifest)[0], 1)


if __name__ == '__main__':
    unittest.main()
