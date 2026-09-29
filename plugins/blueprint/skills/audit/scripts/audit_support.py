#!/usr/bin/env python3
"""Evidence inventory for audit; never a semantic audit or gate proof.

Python 3.10+, standard library only. Inputs are explicit; source bytes are read only.
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

DEFAULT_PREFIXES = ['CAP', 'US', 'BR', 'FR', 'NFR', 'C', 'M', 'CH', 'T']
TEXT_EXTENSIONS = {'.md', '.markdown', '.txt'}
# Document names published by specify next to its store.
SPECIFICATION_DOCUMENTS = {'BRD': '01-BRD.md', 'TRD': '02-TRD.md', 'SAD': '03-SAD.md',
                           'SDD': '04-SDD.md', 'DDD': '05-DDD.md'}


def read_json(path):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=unique,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def input_path(root, value):
    path = Path(value)
    if path.is_absolute():
        raise ValueError('Input paths must be relative to root: ' + str(value))
    full = (root / path).resolve()
    if not full.is_relative_to(root):
        raise ValueError('Input escapes root: ' + str(value))
    return full


def inspect_document(root, spec):
    path = input_path(root, spec['path'])
    result = dict(spec)
    result['path'] = path.relative_to(root).as_posix()
    result.setdefault('namespace', 'project')
    result.setdefault('authority', 'unclassified')
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return dict(result, availability='missing'), None
    except OSError as error:
        return dict(result, availability='unreadable', error=type(error).__name__), None
    result.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
    if path.suffix.lower() == '.json':
        try:
            read_json(path)
        except (ValueError, UnicodeError):
            return dict(result, availability='invalid_json', indexing='not_indexed'), None
        return dict(result, availability='readable', indexing='json_not_lexically_indexed'), None
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return dict(result, availability='available', indexing='not_supported'), None
    try:
        text = raw.decode('utf-8-sig', errors='strict')
    except UnicodeDecodeError:
        return dict(result, availability='invalid_utf8'), None
    lines = text.splitlines()
    result.update(availability='readable', indexing='text', lines=len(lines))
    result['version_declaration'] = next((line for line in lines[:30]
                                         if re.search(r'(?i)\bversion\s*:|версия\s*:', line)), None)
    return result, lines


def index_lines(lines, prefixes):
    prefix = '(?:' + '|'.join(re.escape(p) for p in sorted(prefixes, key=len, reverse=True)) + ')'
    token = re.compile(r'\b(' + prefix + r')-(\d+)\b')
    span = re.compile(r'\b(' + prefix + r')-(\d+)\s*(?:…|\.\.\.|–|—|-)\s*(?:(' + prefix + r')-)?(\d+)\b')
    candidate = re.compile(r'^\s*(?:\|\s*|#{1,6}\s+|[-*]\s+)?`?(' + prefix + r'-\d+)`?(?=\s|[.|:)])')
    occurrences, warnings = [], []
    fence = None
    for number, line in enumerate(lines, 1):
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})(.*)$', line)
        if marker:
            if fence is None:
                fence = (marker[1][0], len(marker[1]))
            elif marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
            continue
        values = {m[0] for m in token.finditer(line)}
        for match in span.finditer(line):
            left, start, right, end = match.groups()
            first, last = int(start), int(end)
            if (right is not None and right != left) or last < first or last - first > 10000:
                warnings.append({'line': number, 'range': match[0], 'reason': 'ambiguous_or_out_of_bounds'})
                continue
            width = max(len(start), len(end))
            values.update(f'{left}-{value:0{width}d}' for value in range(first, last + 1))
        definition = candidate.match(line) if fence is None else None
        if values:
            occurrences.append({'line': number, 'ids': sorted(values),
                                'definition_candidate': definition[1] if definition else None,
                                'context': 'example' if fence is not None else 'prose'})
    if fence:
        warnings.append({'line': len(lines), 'reason': 'unclosed_fence'})
    return occurrences, warnings


def specification_inputs(root, binding):
    """Bind a current specify revision without importing its executable code."""
    store = input_path(root, binding['store'])
    revision = binding['revision']
    if not isinstance(revision, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,79}', revision):
        raise ValueError('Invalid specification revision')
    if (store / 'DOCS-PENDING.json').exists():
        raise ValueError('Specification publication pending')
    if (store / 'CURRENT').read_text(encoding='utf-8').strip() != revision:
        raise ValueError('Specification CURRENT does not match selected revision')
    folder = input_path(root, (store / 'revisions' / revision).relative_to(root))
    snapshot = read_json(folder / 'snapshot.json')
    manifest = read_json(folder / 'manifest.json')
    if manifest['revision'] != revision:
        raise ValueError('Specification manifest revision mismatch')
    paths = {store / 'CURRENT', store / 'policy.json', folder / 'manifest.json',
             folder / 'snapshot.json', folder / 'review.json', folder / 'RTM.md'}
    for name, expected in manifest['files'].items():
        if name not in {'snapshot.json', 'review.json', 'RTM.md', *SPECIFICATION_DOCUMENTS.values()}:
            raise ValueError('Unexpected specification artifact: ' + name)
        item = input_path(root, (folder / name).relative_to(root))
        if hashlib.sha256(item.read_bytes()).hexdigest() != expected:
            raise ValueError('Edited specification artifact: ' + name)
        paths.add(item)
    for stage in snapshot['documents']:
        if stage not in SPECIFICATION_DOCUMENTS:
            raise ValueError('Unexpected document stage')
        paths.add(store.parent / SPECIFICATION_DOCUMENTS[stage])
    for entity in snapshot['entities'].values():
        if entity['kind'] == 'source':
            sha = entity['data']['sha256']
            if not re.fullmatch(r'[0-9a-f]{64}', sha):
                raise ValueError('Invalid source hash')
            paths.add(store / 'sources' / (sha + '.txt'))
    for approval in (store / 'approvals').glob('*.json'):
        approval = input_path(root, approval.relative_to(root))
        if read_json(approval).get('revision') == revision:
            paths.add(approval)
    return [dict(path=input_path(root, p.relative_to(root)).relative_to(root).as_posix(),
                 role='specification', authority='current') for p in sorted(paths)]


def collect(root, config, out):
    root = Path(root).resolve()
    config = read_json(config)
    specs = config.get('documents')
    if not isinstance(specs, list) or not specs:
        raise ValueError('documents must be a non-empty list')
    specs = list(specs)
    binding = config.get('specification')
    if binding is not None:
        expanded = specification_inputs(root, binding)
        explicit = {input_path(root, s['path']) for s in specs}
        specs += [s for s in expanded if input_path(root, s['path']) not in explicit]
    prefixes = config.get('prefixes', DEFAULT_PREFIXES)
    if not isinstance(prefixes, list) or not prefixes or not all(isinstance(p, str) and re.fullmatch(r'[A-Z][A-Z0-9_]*', p) for p in prefixes):
        raise ValueError('prefixes must be non-empty uppercase ID prefixes')
    documents, occurrences, issues, seen = [], [], [], set()
    for spec in specs:
        if not isinstance(spec, dict) or not all(isinstance(spec.get(k), str) and spec[k] for k in ('path', 'role')):
            raise ValueError('Each document needs non-empty path and role')
        if any(k in spec and (not isinstance(spec[k], str) or not spec[k]) for k in ('namespace', 'authority')):
            raise ValueError('namespace and authority must be non-empty strings')
        path = input_path(root, spec['path'])
        if path in seen:
            raise ValueError('Duplicate input path: ' + spec['path'])
        seen.add(path)
        doc, lines = inspect_document(root, spec)
        documents.append(doc)
        if lines is None:
            continue
        indexed, warnings = index_lines(lines, prefixes)
        occurrences.extend(dict(item, file=doc['path'], namespace=doc['namespace']) for item in indexed)
        issues.extend(dict(item, file=doc['path']) for item in warnings)
    definitions = collections.defaultdict(list)
    referenced = collections.defaultdict(set)
    for item in occurrences:
        if item['context'] == 'example':
            continue
        for identity in item['ids']:
            referenced[(item['namespace'], identity)].add((item['file'], item['line']))
        if item['definition_candidate']:
            definitions[(item['namespace'], item['definition_candidate'])].append({'file': item['file'], 'line': item['line']})
    manifest = {'schema_version': 1, 'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                'root': str(root), 'scope': 'Explicit input inventory, not a semantic audit', 'documents': documents}
    if binding is not None:
        manifest['specification'] = {'store': input_path(root, binding['store']).relative_to(root).as_posix(),
                                     'revision': binding['revision']}
    checks = {
        'schema_version': 1,
        'scope': 'Lexical index only; candidate definitions/references require contextual classification',
        'prefixes': prefixes, 'occurrences': occurrences, 'warnings': issues,
        'duplicate_definition_candidates': [{'namespace': ns, 'id': rid, 'locations': locations}
                                            for (ns, rid), locations in sorted(definitions.items()) if len(locations) > 1],
        'references_without_definition_candidate': [
            {'namespace': ns, 'id': rid, 'locations': [{'file': f, 'line': n} for f, n in sorted(locations)]}
            for (ns, rid), locations in sorted(referenced.items()) if (ns, rid) not in definitions],
        'limitations': ['No semantic coverage or gate score is computed.',
                       'Byte availability is not content understanding; non-text inputs need separate semantic reading.',
                       'Leading IDs may be matrix rows or examples; definitions require review.',
                       'Unnumbered obligations and acceptance prose require full document reading.',
                       'Custom ID grammars and non-fenced examples require manual indexing.']}
    out = Path(out).resolve()
    # Fail before writing if it could overwrite an input or reuse another audit.
    if out in seen or out.exists():
        raise ValueError('Output directory must not exist: ' + str(out))
    out.mkdir(parents=True)
    write_json(out / 'manifest.json', manifest)
    write_json(out / 'structural-checks.json', checks)
    return {'output': str(out), 'documents': len(documents),
            'readable': sum(d['availability'] == 'readable' for d in documents), 'semantic_gate': 'NOT_EVALUATED'}


def verify(root, manifest):
    root = Path(root).resolve()
    data = read_json(manifest)
    changed, incomplete = [], []
    for previous in data['documents']:
        current, _ = inspect_document(root, previous)
        # Missing inputs must not inherit the previous SHA from the copied spec.
        if current['availability'] in {'missing', 'unreadable'}:
            current.pop('sha256', None)
        if current['availability'] != previous['availability'] or current.get('sha256') != previous.get('sha256'):
            changed.append(previous['path'])
        if current['availability'] not in ('readable', 'available'):
            incomplete.append({'path': previous['path'], 'availability': current['availability']})
    if data.get('specification'):
        binding = data['specification']
        store = input_path(root, binding['store'])
        if (store / 'DOCS-PENDING.json').exists():
            incomplete.append({'path': str(store / 'DOCS-PENDING.json'), 'availability': 'publication_pending'})
        if not (store / 'CURRENT').is_file() or (store / 'CURRENT').read_text(encoding='utf-8').strip() != binding['revision']:
            pointer = (store / 'CURRENT').relative_to(root).as_posix()
            if pointer not in changed:
                changed.append(pointer)
    code = 1 if changed else 2 if incomplete else 0
    return code, {'input_state': 'CHANGED' if changed else 'INCOMPLETE' if incomplete else 'UNCHANGED',
                  'changed': changed, 'incomplete': incomplete, 'semantic_gate': 'NOT_EVALUATED'}


def compare(previous, current):
    old = {d['path']: d for d in read_json(previous)['documents']}
    new = {d['path']: d for d in read_json(current)['documents']}
    result = {key: [] for key in ('added', 'removed', 'changed', 'unchanged', 'metadata_changed')}
    for path in sorted(old.keys() | new.keys()):
        if path not in old:
            result['added'].append(path)
        elif path not in new:
            result['removed'].append(path)
        else:
            fields = ('sha256', 'availability')
            key = 'changed' if any(old[path].get(k) != new[path].get(k) for k in fields) else 'unchanged'
            result[key].append(path)
            if any(old[path].get(k) != new[path].get(k) for k in ('role', 'namespace', 'authority')):
                result['metadata_changed'].append(path)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    c = commands.add_parser('collect')
    for field in ('root', 'config', 'out'):
        c.add_argument('--' + field, required=True)
    v = commands.add_parser('verify')
    v.add_argument('--root', required=True)
    v.add_argument('--manifest', required=True)
    delta = commands.add_parser('compare')
    delta.add_argument('--previous', required=True)
    delta.add_argument('--current', required=True)
    args = parser.parse_args()
    try:
        code = 0
        if args.command == 'collect':
            result = collect(args.root, args.config, args.out)
        elif args.command == 'verify':
            code, result = verify(args.root, args.manifest)
        else:
            result = compare(args.previous, args.current)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return code
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
