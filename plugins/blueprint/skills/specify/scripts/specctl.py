#!/usr/bin/env python3
"""Standalone specification transactions. Python 3.10+, standard library only.

Run --help for commands. This engine validates structure, bounded decision
tables and closed-vocabulary state machines. Semantic review is recorded evidence supplied by a reviewer, not inferred
from exit 0. Immutable revisions back the documents in the store's parent
directory. A journal detects interrupted document publication. No project imports.
"""
import argparse
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import sys
import uuid

STAGES = ('REQ', 'ARCH', 'DESIGN')
# A profile is the stage sequence of one store, fixed in policy.json. ARCH separates
# components from modules for multi-service systems; compact designs both in DESIGN.
PROFILES = {'compact': ('REQ', 'DESIGN'), 'extended': STAGES}
# Index prefixes order documents after 00-exploration.md; a compact store has no 02.
DOCUMENT_FILES = {'REQ': '01-requirements.md', 'ARCH': '02-architecture.md', 'DESIGN': '03-design.md'}
# From its stage on, every due obligation needs a structural trace path from this kind.
TRACE_KINDS = {'ARCH': 'component', 'DESIGN': 'module'}
CRITERIA = ('structure', 'baseline', 'atomicity', 'completeness', 'consistency',
            'verifiability', 'feasibility', 'contracts', 'traceability', 'external_assumptions')
KINDS = ('source', 'user_decision', 'obligation', 'term', 'contract', 'decision',
         'behavior', 'scenario', 'component', 'module', 'question', 'assumption', 'evidence')
RELATIONS = ('derives', 'refines', 'implements', 'verifies', 'depends_on', 'supersedes', 'conflicts')
ID = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{0,79}\Z')
# Stage-review re-reads this share (percent, bounded) of inherited current-stage edges chosen by the script.
SPOT_CHECK = (10, 5, 30)
NOT_REVIEWED = {'changed': 'Not reviewed: the edge or an end changed, or the reviewed state has no PASS for it',
                'context': 'Not reviewed: relations of an end changed since the last fresh assessment',
                'spot-check': 'Not reviewed: spot check of inherited assessments'}
# Edges per review shard: one reviewer pass reads a shard whole.
SHARD_EDGES = 30
FIELD_PATH = re.compile(r'([^#]+)#(.+)\Z')
PATH_SEGMENT = re.compile(r'([^.\[\]]+)((?:\[\d+\])*)\Z')
QUALITY = Path(__file__).resolve().parent.parent / 'references' / 'quality.md'


class Invalid(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise Invalid(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return 'r-' + uuid.uuid4().hex


def load(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(Invalid('Non-finite number: ' + value)))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def token(value):
    need(isinstance(value, str) and bool(ID.fullmatch(value)), 'Unsafe identifier: ' + str(value))
    return value


@contextmanager
def locked(root):
    path = root / 'WRITE.lock'
    try:
        stream = path.open('x', encoding='utf-8')
    except FileExistsError:
        raise Invalid('Write lock exists; inspect interrupted operation before recovery')
    try:
        stream.write(canonical({'pid': os.getpid(), 'created': now()}))
        stream.close()
        yield
    finally:
        path.unlink()


def current(root):
    revision = (root / 'CURRENT').read_text(encoding='utf-8').strip()
    token(revision)
    return revision


def read_revision(root, revision=None, check_exports=True):
    revision = token(revision or current(root))
    folder = root / 'revisions' / revision
    manifest = load(folder / 'manifest.json')
    for name, expected in manifest['files'].items():
        need(name in ('snapshot.json', 'review.json', 'RTM.md') or name in DOCUMENT_FILES.values(),
             'Unexpected revision artifact')
        need(hashlib.sha256((folder / name).read_bytes()).hexdigest() == expected,
             'Published revision was edited: ' + name)
    snapshot = load(folder / 'snapshot.json')
    need(digest(snapshot) == manifest['snapshot_hash'], 'Snapshot identity mismatch')
    need(set(manifest['files']) == {'snapshot.json', 'review.json', 'RTM.md'} | {DOCUMENT_FILES[s] for s in snapshot['documents']}, 'Incomplete revision manifest')
    need(manifest['revision'] == revision, 'Revision identifier mismatch')
    for entity in snapshot['entities'].values():
        if entity['kind'] == 'source':
            source_check(root, entity)
    if check_exports and revision == current(root):
        need(not (root / 'DOCS-PENDING.json').exists(), 'Document publication interrupted; run sync-docs before continuing')
        for stage in snapshot['documents']:
            path = root.parent / DOCUMENT_FILES[stage]
            need(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == manifest['files'][path.name],
                 'Published document missing or edited: ' + str(path) + '; preserve edits before recovery')
    return snapshot, manifest


def policy(root):
    value = load(root / 'policy.json')
    need(value.get('version') == 2 and value.get('profile') in PROFILES, 'Invalid policy version or profile')
    need(set(value.get('stages', {})) == set(PROFILES[value['profile']]), 'Policy stages must match the profile')
    for stage, rule in value['stages'].items():
        need(set(rule) == {'formal_required', 'runtime_required', 'na_allowed'}, 'Invalid stage policy: ' + stage)
        need(type(rule['formal_required']) is bool and type(rule['runtime_required']) is bool, 'Invalid gate policy')
        need(isinstance(rule['na_allowed'], list) and set(rule['na_allowed']) <= set(CRITERIA), 'Invalid NA policy')
    return value


def profile_stages(root):
    return PROFILES[policy(root)['profile']]


def source_check(root, entity):
    sha = entity['data'].get('sha256', '')
    need(bool(re.fullmatch(r'[0-9a-f]{64}', sha)), 'Invalid source hash')
    path = root / 'sources' / (sha + '.txt')
    need(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha,
         'Missing or changed source snapshot: ' + entity['id'])


def import_source(root, path, key):
    token(key)
    data = path.read_bytes()
    need(data.decode('utf-8-sig', errors='strict').strip(), 'Source must not be empty')
    sha = hashlib.sha256(data).hexdigest()
    target = root / 'sources' / (sha + '.txt')
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        with target.open('xb') as stream:
            stream.write(data)
    need(target.read_bytes() == data, 'Existing source snapshot has changed')
    return {'id': key, 'kind': 'source', 'stage': STAGES[0], 'status': 'active',
            'statement': 'Imported source: ' + path.name, 'basis': [],
            'data': {'sha256': sha, 'original': str(path.resolve())}}


def domains(factors, label):
    """Validate finite scalar domains; return the number of cells in their product."""
    need(isinstance(factors, dict), label + ' must be an object')
    size = 1
    for name, values in factors.items():
        token(name)
        need(isinstance(values, list) and values and all(type(v) in (str, int, bool, type(None)) for v in values), 'Invalid factor domain')
        need(len({canonical(v) for v in values}) == len(values), 'Duplicate domain values')
        size *= len(values)
    return size


def matches(when, cell):
    return all(canonical(cell[n]) in {canonical(v) for v in vs} for n, vs in when.items())


def names(value, vocabulary, label):
    """A state/event reference: one name or a nonempty list, all from the closed vocabulary."""
    value = [value] if isinstance(value, str) else value
    need(isinstance(value, list) and value and all(isinstance(v, str) and v in vocabulary for v in value), 'Unknown ' + label + ': ' + str(value))
    return value


def loose_hints(data):
    """Obvious defects of a free-form machine; advisory only, the result stays UNKNOWN."""
    transitions = data.get('transitions')
    if not (isinstance(transitions, list) and all(isinstance(t, dict) and isinstance(t.get('from'), str) and isinstance(t.get('to'), str) for t in transitions)):
        return []
    sources, targets = {t['from'] for t in transitions}, {t['to'] for t in transitions}
    terminal = set(data.get('terminal') or [])
    hints = []
    if isinstance(data.get('states'), list):
        extra = sorted((sources | targets | {data.get('initial')}) - set(data['states']) - {None})
        if extra:
            hints.append('Names outside states: ' + ', '.join(extra))
    sinks = sorted(targets - sources - terminal)
    if sinks:
        hints.append('No outgoing transition and not terminal: ' + ', '.join(sinks))
    reached, pending = set(), [data.get('initial')]
    while pending:
        state = pending.pop()
        if state not in reached:
            reached.add(state)
            pending.extend(t['to'] for t in transitions if t['from'] == state)
    unreachable = sorted((sources | targets) - reached)
    if unreachable:
        hints.append('Unreachable from initial: ' + ', '.join(unreachable))
    return hints


def state_machine_check(entity):
    """Closed vocabularies and finite guards: determinism, completeness, reachability, exit.

    Every non-terminal state must handle or explicitly ignore every event in every guard
    cell. The graph checks are necessary conditions only: no fairness or timing.
    """
    data = entity['data']
    if 'events' not in data:
        return {'id': entity['id'], 'status': 'UNKNOWN', 'hints': loose_hints(data),
                'reason': 'state_machine without closed states/events vocabularies is not checkable; see schema.md'}
    need(set(data) <= {'representation', 'states', 'initial', 'terminal', 'events', 'guards', 'transitions', 'ignored', 'note'}, 'Unsupported state-machine fields')
    states, events, terminal = data.get('states'), data.get('events'), data.get('terminal')
    for label, vocabulary in (('states', states), ('events', events)):
        need(isinstance(vocabulary, list) and vocabulary and all(isinstance(v, str) and v.strip() for v in vocabulary), 'State machine needs nonempty ' + label)
        need(len(set(vocabulary)) == len(vocabulary), 'Duplicate ' + label)
    need(data.get('initial') in states, 'Initial state outside states')
    need(isinstance(terminal, list) and len(set(terminal)) == len(terminal) and set(terminal) <= set(states), 'terminal must list distinct states (empty for a cyclic machine)')
    need(data['initial'] not in terminal, 'Initial state cannot be terminal')
    guards = data.get('guards', {})
    size = len(states) * len(events) * domains(guards, 'guards')
    need(size <= 100000, 'State machine exceeds 100000 state/event/guard cells; partition its scope')
    def condition(item):
        when = item.get('when', {})
        need(isinstance(when, dict) and set(when) <= set(guards), 'Unknown guard factor')
        for name, values in when.items():
            need(isinstance(values, list) and values and all(canonical(v) in {canonical(x) for x in guards[name]} for v in values), 'Guard condition outside domain')
        return when
    transitions = data.get('transitions')
    need(isinstance(transitions, list) and transitions, 'State machine needs transitions')
    rules = []
    for item in transitions:
        need(isinstance(item, dict) and set(item) <= {'from', 'on', 'when', 'to', 'effects', 'note'}, 'Unsupported transition fields; encode priority in disjoint guards')
        sources, on = names(item.get('from'), states, 'state'), names(item.get('on'), events, 'event')
        need(isinstance(item.get('to'), str) and item['to'] in states, 'Unknown target state: ' + str(item.get('to')))
        need(not set(sources) & set(terminal), 'Terminal state has an outgoing transition')
        effects = item.get('effects', {})
        need(isinstance(effects, dict) and all(type(v) in (str, int, bool, type(None)) for v in effects.values()), 'Transition effects must be scalar')
        rules.append((set(sources), set(on), condition(item), canonical([item['to'], effects]), item['to']))
    ignored = data.get('ignored', [])
    need(isinstance(ignored, list), 'ignored must be a list')
    skips = []
    for item in ignored:
        need(isinstance(item, dict) and set(item) <= {'states', 'events', 'when', 'reason'}, 'Unsupported ignored fields')
        need(isinstance(item.get('reason'), str) and item['reason'].strip(), 'Ignored event needs a reason')
        skips.append((set(names(item.get('states'), states, 'state')), set(names(item.get('events'), events, 'event')), condition(item)))
    cells = [dict(zip(guards, values)) for values in itertools.product(*guards.values())]
    problems, graph = [], {s: set() for s in states}
    for state in states:
        if state in terminal:
            continue
        for event in events:
            for cell in cells:
                hits = [r for r in rules if state in r[0] and event in r[1] and matches(r[2], cell)]
                skipped = any(state in k[0] and event in k[1] and matches(k[2], cell) for k in skips)
                outcomes = {r[3] for r in hits}
                if len(outcomes) > 1 or (outcomes and skipped):
                    problems.append({'kind': 'CONFLICT', 'state': state, 'event': event, 'cell': cell})
                elif not outcomes and not skipped:
                    problems.append({'kind': 'UNDEFINED', 'state': state, 'event': event, 'cell': cell})
                graph[state].update(r[4] for r in hits)
    reached, pending = set(), [data['initial']]
    while pending:
        state = pending.pop()
        if state not in reached:
            reached.add(state)
            pending.extend(graph[state] - reached)
    problems += [{'kind': 'UNREACHABLE', 'state': s} for s in states if s not in reached]
    # Exit: a terminal state, or back to initial for a cyclic machine.
    exits, pending = set(), list(terminal or [data['initial']])
    while pending:
        state = pending.pop()
        if state not in exits:
            exits.add(state)
            pending.extend(s for s in states if state in graph[s] and s not in exits)
    problems += [{'kind': 'TRAP', 'state': s} for s in states if s in reached and s not in exits]
    return {'id': entity['id'], 'status': 'FAIL' if problems else 'PASS', 'states': len(states),
            'cells': len(states) * len(events) * len(cells), 'problem_count': len(problems), 'examples': problems[:10]}


def model_check(entity):
    if entity['data'].get('representation') == 'state_machine':
        return state_machine_check(entity)
    return decision_check(entity)


def decision_check(entity):
    """Exact scalar matches; explicit allowed cells, no expressions or eval."""
    data = entity['data']
    if data.get('representation') != 'decision_table':
        return {'id': entity['id'], 'status': 'UNKNOWN', 'reason': 'No built-in checker for this representation'}
    need(set(data) <= {'representation', 'factors', 'slots', 'rules', 'allowed_cells', 'exclusion_reason'}, 'Unsupported decision-table fields')
    factors, slots, rules = data.get('factors'), data.get('slots'), data.get('rules')
    need(isinstance(factors, dict) and factors, 'Decision table needs factors')
    need(isinstance(slots, dict) and slots and all(v in ('required', 'optional') for v in slots.values()), 'Invalid slots')
    need(domains(factors, 'factors') <= 100000, 'Decision table exceeds 100000 cells; partition its scope')
    need(isinstance(rules, list), 'Rules must be a list')
    names = list(factors)
    all_cells = [dict(zip(names, values)) for values in itertools.product(*(factors[n] for n in names))]
    allowed = data.get('allowed_cells')
    cells = all_cells
    if allowed is not None:
        need(isinstance(allowed, list) and allowed and data.get('exclusion_reason'), 'Excluded cells need a nonempty domain and reason')
        legal = {canonical(c) for c in all_cells}
        need(len({canonical(c) for c in allowed}) == len(allowed) and all(canonical(c) in legal for c in allowed), 'Invalid allowed cells')
        cells = allowed
    for rule in rules:
        need(isinstance(rule, dict) and isinstance(rule.get('when'), dict) and isinstance(rule.get('effects'), dict), 'Malformed rule')
        need(set(rule) == {'when', 'effects'}, 'Unsupported rule fields; encode priorities in disjoint conditions')
        need(set(rule['when']) <= set(factors) and set(rule['effects']) <= set(slots), 'Unknown factor or slot')
        for name, values in rule['when'].items():
            need(isinstance(values, list) and values and all(canonical(v) in {canonical(x) for x in factors[name]} for v in values), 'Condition outside domain')
    problems = []
    for cell in cells:
        hits = [r for r in rules if matches(r['when'], cell)]
        for slot, obligation in slots.items():
            values = {canonical(r['effects'][slot]) for r in hits if slot in r['effects']}
            if len(values) > 1 or (not values and obligation == 'required'):
                problems.append({'cell': cell, 'slot': slot, 'kind': 'CONFLICT' if values else 'UNDEFINED'})
    return {'id': entity['id'], 'status': 'FAIL' if problems else 'PASS', 'cells': len(cells),
            'problem_count': len(problems), 'examples': problems[:10]}


def validate(root, snapshot):
    need(set(snapshot) == {'schema', 'stage', 'entities', 'edges', 'documents'}, 'Invalid snapshot fields')
    stages = profile_stages(root)
    need(snapshot['schema'] == 2 and snapshot['stage'] in stages, 'Invalid schema or stage outside the policy profile')
    entities, edges, documents = snapshot['entities'], snapshot['edges'], snapshot['documents']
    need(isinstance(entities, dict) and isinstance(edges, dict) and isinstance(documents, dict), 'Registries must be objects')
    model_results = []
    # Global order is valid for comparisons: every profile is an ordered subsequence of STAGES.
    active_stage = STAGES.index(snapshot['stage'])
    for key, entity in entities.items():
        token(key)
        need(entity.get('id') == key and entity.get('kind') in KINDS, 'Invalid entity: ' + key)
        need(isinstance(entity.get('statement'), str) and entity['statement'].strip(), 'Missing statement: ' + key)
        need(entity.get('stage') in stages and isinstance(entity.get('data'), dict), 'Invalid entity stage/data: ' + key)
        need(entity.get('status') in ('active', 'superseded'), 'Invalid entity status: ' + key)
        need(isinstance(entity.get('basis'), list) and all(x in entities and x != key for x in entity['basis']), 'Invalid basis: ' + key)
        if entity['kind'] == 'source':
            source_check(root, entity)
        else:
            need(entity['basis'], 'No origin for ' + key + '; use a source or explicit decision')
        if entity['kind'] == 'obligation':
            required = ('actor', 'trigger', 'precondition', 'action', 'outcome', 'exceptions', 'limits', 'phase', 'modality')
            need(all(k in entity['data'] for k in required), 'Incomplete normalized obligation: ' + key)
            need(all(isinstance(entity['data'][k], str) and entity['data'][k].strip() for k in ('actor', 'action', 'outcome', 'phase', 'modality')), 'Empty obligation fields: ' + key)
        if entity['kind'] == 'scenario':
            need(all(entity['data'].get(k) for k in ('given', 'when', 'then', 'distinguishes')), 'Scenario needs conditions, actions, outcome and rejected implementation: ' + key)
        if entity['kind'] == 'question' and entity['status'] == 'active':
            need(type(entity['data'].get('blocking')) is bool, 'Question needs blocking flag')
            need(not entity['data']['blocking'] or STAGES.index(entity['stage']) > active_stage, 'Blocking question due at current stage: ' + key)
        if entity['status'] == 'active':
            need(all(entities[x]['status'] == 'active' for x in entity['basis']), 'Active entity depends on superseded basis: ' + key)
            if STAGES.index(entity['stage']) <= active_stage and entity['kind'] == 'behavior':
                model_results.append(model_check(entity))
    # Origins may not be circular; a source must eventually ground every chain.
    visiting, visited = set(), set()
    def visit(key):
        need(key not in visiting, 'Cyclic origin at ' + key)
        if key in visited:
            return
        visiting.add(key)
        for parent in entities[key]['basis']:
            visit(parent)
        visiting.remove(key)
        visited.add(key)
    for key in entities:
        visit(key)
    for key, edge in edges.items():
        token(key)
        need(edge.get('id') == key and edge.get('type') in RELATIONS, 'Invalid edge: ' + key)
        need(edge.get('from') in entities and edge.get('to') in entities and edge['from'] != edge['to'], 'Dangling edge: ' + key)
        need(edge.get('due_stage') in stages and isinstance(edge.get('rationale'), str) and edge['rationale'].strip(), 'Edge needs deadline and rationale: ' + key)
    required_docs = stages[:stages.index(snapshot['stage']) + 1]
    need(set(documents) == set(required_docs), 'Documents must cover exactly the profile stages through the current one: ' + ', '.join(required_docs))
    for stage, document in documents.items():
        need(isinstance(document.get('title'), str) and document['title'].strip(), 'Missing document title')
        need(isinstance(document.get('sections'), list) and document['sections'], 'Document needs sections: ' + stage)
        section_ids = set()
        for section in document['sections']:
            token(section.get('id'))
            need(section['id'] not in section_ids, 'Duplicate section ID')
            section_ids.add(section['id'])
            need(isinstance(section.get('title'), str) and section['title'].strip(), 'Section needs title')
            need(isinstance(section.get('prose'), str) and isinstance(section.get('entities'), list), 'Section needs prose/entities')
            need(all(e in entities and entities[e]['status'] == 'active' for e in section['entities']), 'Unknown/superseded document entity')
    due = {k for k, e in entities.items() if e['status'] == 'active' and STAGES.index(e['stage']) <= active_stage}
    kinds = {entities[k]['kind'] for k in due}
    need({'source', 'obligation', 'scenario'} <= kinds, 'A candidate needs a source, obligation and scenario')
    # Compact has no ARCH, so components stay optional there; modules are required at DESIGN in both profiles.
    traced = [kind for threshold, kind in TRACE_KINDS.items() if threshold in stages and active_stage >= STAGES.index(threshold)]
    for kind in traced:
        need(kind in kinds, 'Stage needs at least one ' + kind)
    shown = {e for d in documents.values() for s in d['sections'] for e in s['entities']}
    need(all(k in shown for k in due if entities[k]['kind'] not in ('source',)), 'Active entities absent from documents: ' + ', '.join(sorted(due - shown - {k for k in due if entities[k]['kind'] == 'source'})))
    for key in due:
        if entities[key]['kind'] == 'obligation':
            need(any(e['type'] == 'verifies' and e['to'] == key and entities[e['from']]['kind'] == 'scenario' and entities[e['from']]['status'] == 'active' and e['from'] in due for e in edges.values()), 'Obligation needs a current distinguishing scenario: ' + key)
    # Coverage is structural only; the review must still establish implementation semantics.
    parents = {k: set(entities[k]['basis']) & due for k in due}
    for edge in edges.values():
        if edge['from'] in due and edge['to'] in due and edge['type'] in ('implements', 'refines', 'derives', 'depends_on') and STAGES.index(edge['due_stage']) <= active_stage:
            parents[edge['from']].add(edge['to'])
    def ancestors(key):
        seen, pending = set(), list(parents[key])
        while pending:
            node = pending.pop()
            if node not in seen:
                seen.add(node)
                pending.extend(parents[node] - seen)
        return seen
    for kind in traced:
        covered = set().union(*(ancestors(k) for k in due if entities[k]['kind'] == kind))
        need(all(k in covered for k in due if entities[k]['kind'] == 'obligation'), 'Missing ' + kind + ' trace path for an obligation')
    return model_results


def contract_check(contract, snapshot):
    required = ('goal', 'scope', 'constraints', 'freedom', 'outputs', 'checks', 'unknowns')
    need(isinstance(contract, dict) and all(k in contract for k in required), 'Incomplete generation contract')
    need(contract.get('mode') in ('fragment', 'stage-review'), 'Contract mode must be fragment or stage-review')
    need(isinstance(contract['goal'], str) and contract['goal'].strip(), 'Contract needs goal')
    for key in required[1:]:
        need(isinstance(contract[key], list), 'Contract field must be list: ' + key)
    need(contract['scope'] and contract['outputs'] and set(CRITERIA) <= set(contract['checks']), 'Contract needs scope, outputs and all ten criteria')
    need(not contract['unknowns'], 'Resolve blocking generation questions before sealing a candidate')


def impact(before, after):
    changed = {k for k in before['entities'].keys() | after['entities'].keys() if before['entities'].get(k) != after['entities'].get(k)}
    edge_changes = {k for k in before['edges'].keys() | after['edges'].keys() if before['edges'].get(k) != after['edges'].get(k)}
    affected = set(changed)
    for key in edge_changes:
        for graph in (before, after):
            if key in graph['edges']:
                affected.update((graph['edges'][key]['from'], graph['edges'][key]['to']))
    while True:
        expanded = set(affected)
        for graph in (before, after):
            for key, e in graph['entities'].items():
                if set(e['basis']) & affected:
                    expanded.add(key)
            # Conservative: both endpoints; implementations commonly point upstream.
            for e in graph['edges'].values():
                if e['from'] in affected or e['to'] in affected:
                    expanded.update((e['from'], e['to']))
        if expanded == affected:
            break
        affected = expanded
    documents = [s for s in before['documents'].keys() | after['documents'].keys()
                 if before['documents'].get(s) != after['documents'].get(s) or
                 any(set(sec['entities']) & affected for sec in after['documents'].get(s, {}).get('sections', []))]
    return {'changed_entities': sorted(changed), 'changed_edges': sorted(edge_changes),
            'affected_entities': sorted(affected), 'affected_documents': sorted(documents),
            'review_scope': 'criteria: entire candidate; edges: fresh unless an unchanged edge inherits a prior PASS '
                            '(stage-review: only while its context is unchanged since the last fresh reading, minus a spot check)'}


def entity_changes(before, after):
    fields = [k for k in ('kind', 'stage', 'status', 'statement', 'basis') if before.get(k) != after.get(k)]
    old, new = before.get('data', {}), after.get('data', {})
    return fields + ['data.' + k for k in sorted(old.keys() | new.keys()) if old.get(k) != new.get(k)]


def diff(before, after):
    """Field-level change list: where to look, not what it means."""
    old, new = before['entities'], after['entities']
    documents = {}
    for stage, doc in after['documents'].items():
        previous = before['documents'].get(stage)
        if previous is None:
            documents[stage] = ['(new document)']
        elif previous != doc:
            prior = {s['id']: s for s in previous['sections']}
            ids = [s['id'] for s in doc['sections']]
            changes = (['(title)'] if previous['title'] != doc['title'] else []) + \
                [s['id'] for s in doc['sections'] if prior.get(s['id']) != s] + ['-' + k for k in prior if k not in ids]
            documents[stage] = changes or ['(section order)']
    return {'new_entities': sorted(new.keys() - old.keys()),
            'modified_entities': {k: entity_changes(old[k], new[k]) for k in sorted(old) if k in new and old[k] != new[k]},
            'new_edges': sorted(after['edges'].keys() - before['edges'].keys()),
            'modified_edges': sorted(k for k in before['edges'] if k in after['edges'] and before['edges'][k] != after['edges'][k]),
            'removed_edges': sorted(before['edges'].keys() - after['edges'].keys()),
            'documents': documents}


def due(edge, stage):
    return STAGES.index(edge['due_stage']) <= STAGES.index(stage)


def without_inheritance(assessment):
    return {k: v for k, v in assessment.items() if k not in ('inherited', 'context')}


def incidence(snapshot):
    result = {}
    for key, edge in snapshot['edges'].items():
        for end in (edge['from'], edge['to']):
            result.setdefault(end, set()).add(key)
    return result


def edge_context(snapshot, index, key):
    """What an edge assessment reads: both ends and their relations up to the edge's own due_stage.

    Later-stage refinements of an end do not reopen an earlier edge; a new sibling relation does.
    """
    edge = snapshot['edges'][key]
    ends = (edge['from'], edge['to'])
    limit = STAGES.index(edge['due_stage'])
    related = sorted({k for end in ends for k in index.get(end, ()) if STAGES.index(snapshot['edges'][k]['due_stage']) <= limit})
    return digest({'entities': {end: snapshot['entities'][end] for end in ends}, 'edges': {k: snapshot['edges'][k] for k in related}})


def prior_reviews(root, folder, meta):
    """Reviewed states whose PASS on an unchanged edge may be inherited, most recent first.

    A --from package counts only when its review is complete for its current identity;
    the base revision counts while the policy it was accepted under is unchanged.
    """
    priors = []
    if meta.get('from'):
        prior = Path(meta['from'])
        if (prior / 'review-request.json').is_file() and (prior / 'review.json').is_file():
            pmeta, snapshot = load(prior / 'package.json'), load(prior / 'candidate.json')
            request, review = load(prior / 'review-request.json'), load(prior / 'review.json')
            if review.get('identity') == request['identity'] == review_identity(root, prior, pmeta, snapshot) and \
                    isinstance(review.get('reviewer'), str) and review['reviewer'].strip() and isinstance(review.get('edges'), dict):
                priors.append({'label': 'package:' + pmeta['id'], 'snapshot': snapshot, 'review': review, 'index': incidence(snapshot)})
    snapshot, manifest = read_revision(root, meta['base'], check_exports=False)
    review = load(root / 'revisions' / meta['base'] / 'review.json')
    if isinstance(review.get('edges'), dict) and manifest['policy_hash'] == digest(policy(root)):
        priors.append({'label': 'revision:' + meta['base'], 'snapshot': snapshot, 'review': review, 'index': incidence(snapshot)})
    return priors


def inheritable(prior, snapshot, key):
    edge, assessment = snapshot['edges'][key], prior['review']['edges'].get(key)
    return (prior['snapshot']['edges'].get(key) == edge and isinstance(assessment, dict) and assessment.get('status') == 'PASS' and
            all(prior['snapshot']['entities'].get(edge[end]) == snapshot['entities'][edge[end]] for end in ('from', 'to')))


def inherited_assessment(prior, key):
    """The prior PASS with its source label and the context of its last fresh reading.

    A fresh prior assessment gets the context of the prior snapshot; an inherited one passes its context on.
    Legacy assessments inherited without a context carry none, so stage-review re-reads them.
    """
    source = prior['review']['edges'][key]
    context = source.get('context') if 'inherited' in source else edge_context(prior['snapshot'], prior['index'], key)
    result = dict(without_inheritance(source), inherited=prior['label'])
    if isinstance(context, str):
        result['context'] = context
    return result


def review_plan(snapshot, mode, identity, priors):
    """Per due edge: ('inherit', assessment) or ('fresh', reason key); future edges are omitted.

    fragment inherits every unchanged PASS. stage-review keeps an inherited PASS only while the edge
    context is unchanged since its last fresh reading, and re-reads a script-chosen spot check of the
    rest, so interactions between accepted fragments are read afresh without re-reading the whole graph.
    """
    plan, eligible, index = {}, [], incidence(snapshot)
    for key, edge in sorted(snapshot['edges'].items()):
        if not due(edge, snapshot['stage']):
            continue
        prior = next((p for p in priors if inheritable(p, snapshot, key)), None)
        if prior is None:
            plan[key] = ('fresh', 'changed')
            continue
        assessment = inherited_assessment(prior, key)
        if mode == 'stage-review' and assessment.get('context') != edge_context(snapshot, index, key):
            plan[key] = ('fresh', 'context')
            continue
        plan[key] = ('inherit', assessment)
        if mode == 'stage-review' and edge['due_stage'] == snapshot['stage']:
            eligible.append(key)
    share, low, high = SPOT_CHECK
    count = min(len(eligible), max(low, min(high, -(-len(eligible) * share // 100))))
    for key in sorted(eligible, key=lambda k: digest([identity, k]))[:count]:
        plan[key] = ('fresh', 'spot-check')
    return plan


def carried_findings(root, meta, priors):
    """Open findings of the base plus the whole register of a reviewed --from package."""
    findings = {f['id']: f for f in load(root / 'revisions' / meta['base'] / 'review.json').get('findings', []) if f['state'] == 'open'}
    for prior in priors:
        if prior['label'].startswith('package:'):
            findings.update({f['id']: f for f in prior['review'].get('findings', [])})
    return list(findings.values())


def previous_candidate(meta):
    path = Path(meta['from']) / 'candidate.json' if meta.get('from') else None
    return load(path) if path and path.is_file() else None


def review_brief(meta, contract, snapshot, old, previous, priors, review):
    lines = ['# Review brief', '', '> Generated by prepare-review. Навигация по изменениям, не вердикт: оценивай по самим сущностям и источникам.', '',
             '- Стадия: %s; режим: %s; база: %s' % (snapshot['stage'], contract['mode'], meta['base']),
             '- Источники наследования оценок рёбер: ' + (', '.join(p['label'] for p in priors) or 'нет'), '']
    def changes(title, change):
        lines.extend(['## ' + title, '', 'Новые сущности: ' + (', '.join(change['new_entities']) or '—'), ''])
        lines.extend(['- %s: %s' % (k, ', '.join(v)) for k, v in change['modified_entities'].items()] or ['Изменённых сущностей нет.'])
        lines.extend(['', 'Рёбра: новые — %s; изменённые — %s; удалённые — %s' % tuple(', '.join(change[k]) or '—' for k in ('new_edges', 'modified_edges', 'removed_edges')), ''])
        lines.extend(['- %s: %s' % (k, ', '.join(v)) for k, v in change['documents'].items()] or ['Разделы документов не изменены.'])
        lines.append('')
    if previous is not None:
        changes('Изменения относительно пакета ' + meta['from'], diff(previous, snapshot))
    changes('Изменения относительно базы ' + meta['base'], diff(old, snapshot))
    edges = snapshot['edges']
    fresh = [k for k, a in sorted(review['edges'].items()) if a['status'] == 'UNKNOWN']
    inherited = sum(1 for a in review['edges'].values() if 'inherited' in a)
    lines.extend(['## Оценки рёбер', '', 'Унаследовано PASS: %d; не наступил due_stage: %d; требуют оценки: %d.' % (
                  inherited, sum(1 for e in edges.values() if not due(e, snapshot['stage'])), len(fresh)), ''])
    groups = (('changed', 'Изменились ребро или его концы либо нет проверенного PASS'),
              ('context', 'Связи конца изменились после последней свежей оценки — проверь взаимодействие'),
              ('spot-check', 'Контрольная выборка унаследованных оценок, выбрана скриптом'))
    for reason, title in groups:
        keys = [k for k in fresh if review['edges'][k]['reason'] == NOT_REVIEWED[reason]]
        if keys:
            lines.extend(['### %s (%d)' % (title, len(keys)), ''])
            lines.extend('- %s: %s %s → %s' % (k, edges[k]['type'], edges[k]['from'], edges[k]['to']) for k in keys)
            lines.append('')
    open_findings = [f for f in review['findings'] if f['state'] == 'open']
    lines.extend(['', '## Открытые findings для перепроверки', ''])
    lines.extend(['- %s (%s %s): %s' % (f['id'], f['severity'], f['kind'], str(f.get('closure') or f['reason'])[:300].replace('\n', ' ')) for f in open_findings] or ['Нет.'])
    return '\n'.join(lines) + '\n'


def candidate(root, folder):
    meta, snapshot = load(folder / 'package.json'), load(folder / 'candidate.json')
    need(meta['root'] == str(root.resolve()), 'Package belongs to a different store')
    need(meta['base'] == current(root), 'STALE BASE: start a new package and reconcile changes')
    need(meta['stage'] == snapshot['stage'], 'Package stage cannot be changed')
    old, _ = read_revision(root, meta['base'])
    need(set(old['entities']) <= set(snapshot['entities']), 'Do not delete entities; explicitly supersede them')
    for key, e in old['entities'].items():
        if e['kind'] in ('source', 'user_decision'):
            need(snapshot['entities'][key] == e, 'Source/user decision records are immutable; add a new record')
    for key, e in snapshot['entities'].items():
        if e['status'] == 'superseded' and old['entities'].get(key, {}).get('status') != 'superseded':
            need(any(x['type'] == 'supersedes' and x['to'] == key and snapshot['entities'][x['from']]['kind'] in ('decision', 'user_decision') for x in snapshot['edges'].values()), 'Supersession needs a decision: ' + key)
    return meta, snapshot, old


def review_identity(root, folder, meta, snapshot):
    return digest({'package': meta, 'snapshot': snapshot, 'contract': load(folder / 'contract.json'), 'policy': policy(root)})


def reference(snapshot, ref):
    """True for an entity, edge or document ID, mechanical-report, or a field path such as FR-1#data.exceptions[2]."""
    if not isinstance(ref, str):
        return False
    if ref == 'mechanical-report' or ref in snapshot['entities'] or ref in snapshot['edges'] or ref in snapshot['documents']:
        return True
    match = FIELD_PATH.match(ref)
    if not match:
        return False
    value = snapshot['entities'].get(match[1]) or snapshot['edges'].get(match[1]) or snapshot['documents'].get(match[1])
    for part in match[2].split('.'):
        segment = PATH_SEGMENT.match(part)
        if value is None or not segment or not isinstance(value, dict) or segment[1] not in value:
            return False
        value = value[segment[1]]
        for index in re.findall(r'\[(\d+)\]', segment[2]):
            if not isinstance(value, list) or int(index) >= len(value):
                return False
            value = value[int(index)]
    return True


def summary(text, size=160):
    text = ' '.join(text.split())
    return text if len(text) <= size else text[:size].rstrip() + '… (specctl show для полного текста)'


def sections(snapshot):
    """Entity → (document order, section id): the semantic group a shard follows."""
    result = {}
    for order, (stage, doc) in enumerate(sorted(snapshot['documents'].items(), key=lambda x: STAGES.index(x[0]))):
        for number, section in enumerate(doc['sections']):
            for key in section['entities']:
                result.setdefault(key, ((order, number), stage + '/' + section['id']))
    return result


def review_shards(snapshot, old, review):
    """Split UNKNOWN edges into self-contained reading packets grouped by document section.

    A packet holds the edges, both ends, same-level neighbour relations and basis statements,
    plus field paths changed against the base. Prior reasons are left out so they are not copied.
    """
    placed, index = sections(snapshot), incidence(snapshot)
    edges, why = snapshot['edges'], {text: key for key, text in NOT_REVIEWED.items()}
    pending = [k for k, a in review['edges'].items() if a['status'] == 'UNKNOWN']
    def group(key):
        edge = edges[key]
        return placed.get(edge['from']) or placed.get(edge['to']) or ((len(STAGES), 0), 'other')
    ordered = sorted(pending, key=lambda k: (group(k)[0], edges[k]['to'], k))
    batches, current = [], []
    for key in ordered:
        if current and (len(current) >= SHARD_EDGES or (group(current[-1])[1] != group(key)[1] and len(current) >= SHARD_EDGES // 2)):
            batches.append(current)
            current = []
        current.append(key)
    if current:
        batches.append(current)
    shards = []
    for number, keys in enumerate(batches, 1):
        ends = sorted({edges[k][x] for k in keys for x in ('from', 'to')})
        limit = {k: STAGES.index(edges[k]['due_stage']) for k in keys}
        neighbours = sorted({n for k in keys for x in ('from', 'to') for n in index.get(edges[k][x], ())
                             if n not in keys and STAGES.index(edges[n]['due_stage']) <= limit[k]})
        changes = {x: ('new' if x not in old['entities'] else entity_changes(old['entities'][x], snapshot['entities'][x]))
                   for x in ends if old['entities'].get(x) != snapshot['entities'][x]}
        basis = sorted({b for x in ends for b in snapshot['entities'][x]['basis']} - set(ends))
        name = 'S-%02d' % number
        shards.append({'shard': name, 'stage': snapshot['stage'], 'sections': sorted({group(k)[1] for k in keys}),
                       'instructions': 'Оцени каждое ребро из edges по критическому проходу %s. Для PASS назови механизм и различающий пример '
                                       'в 1–3 предложениях; поля не цитируй — укажи в evidence ID или путь к полю (FR-1#data.exceptions[2]). '
                                       'Ответ — файл result рядом с шардом по форме result_template; notes — кандидаты в findings для основного ревьюера. '
                                       'Не правь кандидат и review.json.' % QUALITY,
                       'result': name + '.result.json',
                       'edges': [dict(edges[k], why=why.get(review['edges'][k]['reason'], 'changed')) for k in keys],
                       'entities': {x: snapshot['entities'][x] for x in ends},
                       'changed_since_base': changes,
                       'neighbour_edges': {n: '%s %s → %s' % (edges[n]['type'], edges[n]['from'], edges[n]['to']) +
                                           ('' if old['edges'].get(n) == edges[n] else ' [new/changed since base: %s]' % edges[n]['rationale'])
                                           for n in neighbours},
                       'basis': {b: '%s: %s' % (snapshot['entities'][b]['kind'], summary(snapshot['entities'][b]['statement'])) for b in basis},
                       'result_template': {'shard': name, 'edges': {k: {'status': 'UNKNOWN', 'reason': '', 'evidence': []} for k in keys}, 'notes': []}})
    return shards


def apply_assessments(root, folder, meta, snapshot, update):
    """Merge reviewer-written assessments into review.json after structural validation."""
    request, review = load(folder / 'review-request.json'), load(folder / 'review.json')
    need(review.get('identity') == request['identity'] == review_identity(root, folder, meta, snapshot), 'STALE review; candidate/contract/policy changed')
    need(isinstance(update, dict) and set(update) <= {'shard', 'reviewer', 'criteria', 'edges', 'formal', 'runtime', 'findings', 'notes'}, 'Unknown assessment fields')
    allowed = None
    if 'shard' in update:
        shard = load(folder / 'shards' / (token(update['shard']) + '.json'))
        allowed = {e['id'] for e in shard['edges']}
    def valid(value, label):
        need(isinstance(value, dict) and set(value) <= {'status', 'reason', 'evidence'}, 'Assessment is fresh; drop inherited/context and extra fields: ' + label)
        need(value.get('status') in ('PASS', 'FAIL', 'UNKNOWN', 'NOT_APPLICABLE'), 'Invalid status: ' + label)
        need(isinstance(value.get('reason'), str) and value['reason'].strip(), 'Assessment requires explanation: ' + label)
        need(isinstance(value.get('evidence', []), list) and all(reference(snapshot, r) for r in value.get('evidence', [])), 'Unknown evidence reference: ' + label)
        need(value['status'] != 'PASS' or value.get('evidence'), 'PASS needs evidence references: ' + label)
        return dict(value, evidence=value.get('evidence', []))
    for key, value in (update.get('edges') or {}).items():
        need(key in snapshot['edges'], 'Unknown edge: ' + str(key))
        need(allowed is None or key in allowed, 'Edge is outside shard ' + str(update.get('shard')) + ': ' + key)
        review['edges'][key] = valid(value, key)
    for key, value in (update.get('criteria') or {}).items():
        need(key in CRITERIA, 'Unknown criterion: ' + str(key))
        review['criteria'][key] = valid(value, key)
    for name in ('formal', 'runtime'):
        if name in update:
            review[name] = valid(update[name], name)
    if 'reviewer' in update:
        need(isinstance(update['reviewer'], str) and update['reviewer'].strip(), 'Reviewer identity is required')
        review['reviewer'] = update['reviewer']
    findings = {f['id']: f for f in review['findings']}
    for finding in update.get('findings') or []:
        need(isinstance(finding, dict), 'Invalid finding')
        token(finding.get('id'))
        findings[finding['id']] = finding
    review['findings'] = list(findings.values())
    atomic_bytes(folder / 'review.json', (json.dumps(review, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))
    return {'applied': {k: len(update.get(k) or {}) for k in ('edges', 'criteria', 'findings')},
            'unknown_edges': sorted(k for k, a in review['edges'].items() if a['status'] == 'UNKNOWN'),
            'notes': update.get('notes') or []}


def md(value):
    return str(value).replace('|', '\\|').replace('\n', '<br>')


def render(snapshot, review=None):
    rendered = {}
    for stage, doc in snapshot['documents'].items():
        lines = ['# ' + doc['title'], '', '> Generated from snapshot.json. Propose edits through a new package.', '']
        for section in doc['sections']:
            lines += ['## ' + section['id'] + ' — ' + section['title'], '', section['prose'], '']
            for key in section['entities']:
                e = snapshot['entities'][key]
                lines += ['### ' + key + ' · ' + e['kind'], '', e['statement'], '',
                          'Основания: ' + ', '.join(e['basis']), '', '| Поле | Значение |', '|---|---|']
                lines += ['| ' + md(k) + ' | ' + md(canonical(v) if not isinstance(v, str) else v) + ' |' for k, v in e['data'].items()]
                lines.append('')
        rendered[DOCUMENT_FILES[stage]] = '\n'.join(lines)
    lines = ['# RTM', '', '| ID | Тип | От | К | Стадия | Смысловая проверка | Основание |', '|---|---|---|---|---|---|---|']
    for key, edge in sorted(snapshot['edges'].items()):
        status = review['edges'].get(key, {}).get('status', 'UNKNOWN') if review else 'UNKNOWN'
        lines.append('| ' + ' | '.join(md(x) for x in (key, edge['type'], edge['from'], edge['to'], edge['due_stage'], status, edge['rationale'])) + ' |')
    lines += ['', '## Обязательства', '', '| ID | Фаза | Входящие связи | Исходящие связи |', '|---|---|---|---|']
    for key, e in sorted(snapshot['entities'].items()):
        if e['kind'] == 'obligation' and e['status'] == 'active':
            incoming = ', '.join(k for k, v in snapshot['edges'].items() if v['to'] == key) or '—'
            outgoing = ', '.join(k for k, v in snapshot['edges'].items() if v['from'] == key) or '—'
            lines.append('| ' + ' | '.join(md(x) for x in (key, e['data']['phase'], incoming, outgoing)) + ' |')
    lines += ['', '## Происхождение (структурные связи basis)', '', '| Сущность | Основания |', '|---|---|']
    lines += ['| ' + md(k) + ' | ' + md(', '.join(e['basis']) or 'Исходный снимок') + ' |'
              for k, e in sorted(snapshot['entities'].items())]
    rendered['RTM.md'] = '\n'.join(lines) + '\n'
    return rendered


def atomic_bytes(path, data):
    temporary = path.with_name(path.name + '.' + uid() + '.tmp')
    temporary.write_bytes(data)
    os.replace(temporary, path)


def sync_docs(root):
    journal_path = root / 'DOCS-PENDING.json'
    if journal_path.exists():
        journal = load(journal_path)
        need(current(root) in (journal['parent'], journal['revision']), 'Publication journal does not match CURRENT')
        snapshot, manifest = read_revision(root, journal['revision'], check_exports=False)
        need(manifest['parent'] == journal['parent'] or journal['revision'] == journal['parent'], 'Journal parent mismatch')
        expected = {DOCUMENT_FILES[s] for s in snapshot['documents']}
        need(set(journal['documents']) == expected, 'Invalid publication journal document set')
    else:
        snapshot, manifest = read_revision(root, check_exports=False)
        journal = {'revision': manifest['revision'], 'parent': manifest['parent'],
                   'documents': {DOCUMENT_FILES[s]: manifest['files'][DOCUMENT_FILES[s]] for s in snapshot['documents']}}
    # Inspect ALL destinations before changing any. Never overwrite a third value.
    for name, old_hash in journal['documents'].items():
        path = root.parent / name
        if path.exists():
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            need(actual in (old_hash, manifest['files'][name]), 'Document contains unrecognized edits; preserve and reconcile: ' + str(path))
    if not journal_path.exists():
        journal['parent'] = current(root)
        write(journal_path, journal)
    for name in journal['documents']:
        atomic_bytes(root.parent / name, (root / 'revisions' / journal['revision'] / name).read_bytes())
    atomic_bytes(root / 'CURRENT', (journal['revision'] + '\n').encode('utf-8'))
    journal_path.unlink()
    return journal['revision']


def publish(root, snapshot, review, parent, generation_contract=None, verification=None):
    old_files = read_revision(root, parent)[1]['files'] if parent else {}
    documents = {DOCUMENT_FILES[s]: old_files.get(DOCUMENT_FILES[s]) for s in snapshot['documents']}
    for name, expected in documents.items():
        path = root.parent / name
        if path.exists():
            need(expected is not None and hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                 'Refusing to overwrite existing or edited document: ' + str(path))
    revision = uid()
    folder = root / 'revisions' / revision
    folder.mkdir(parents=True)
    write(folder / 'snapshot.json', snapshot)
    write(folder / 'review.json', review)
    for name, body in render(snapshot, review if review and 'edges' in review else None).items():
        (folder / name).write_text(body, encoding='utf-8', newline='\n')
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    write(folder / 'manifest.json', {'revision': revision, 'parent': parent, 'created': now(),
                                   'snapshot_hash': digest(snapshot), 'policy_hash': digest(policy(root)),
                                   'contract': generation_contract, 'verification': verification, 'files': files})
    if documents:
        write(root / 'DOCS-PENDING.json', {'revision': revision, 'parent': parent, 'documents': documents})
        sync_docs(root)
    else:
        atomic_bytes(root / 'CURRENT', (revision + '\n').encode('utf-8'))
    return revision


def review_gate(root, folder):
    meta, snapshot, old = candidate(root, folder)
    model = validate(root, snapshot)
    contract_check(load(folder / 'contract.json'), snapshot)
    request, review = load(folder / 'review-request.json'), load(folder / 'review.json')
    identity = review_identity(root, folder, meta, snapshot)
    need(request['identity'] == identity and review.get('identity') == identity, 'STALE review; candidate/contract/policy changed')
    need(isinstance(review.get('reviewer'), str) and review['reviewer'].strip(), 'Reviewer identity is required')
    need(set(review.get('criteria', {})) == set(CRITERIA), 'Review must cover all ten criteria')
    rules = policy(root)['stages'][snapshot['stage']]
    statuses = []
    def assessment(value, allow_na=False):
        need(isinstance(value, dict) and value.get('status') in ('PASS', 'FAIL', 'UNKNOWN', 'NOT_APPLICABLE'), 'Invalid assessment')
        need(isinstance(value.get('reason'), str) and value['reason'].strip(), 'Assessment requires explanation')
        if value['status'] == 'NOT_APPLICABLE':
            need(allow_na, 'NOT_APPLICABLE not allowed by stage policy')
        if value['status'] == 'PASS':
            need(isinstance(value.get('evidence'), list) and value['evidence'], 'PASS needs evidence references')
            for ref in value['evidence']:
                need(reference(snapshot, ref), 'Unknown evidence reference: ' + str(ref))
        return value['status']
    for name in CRITERIA:
        need('inherited' not in review['criteria'][name], 'Criteria are never inherited: ' + name)
        statuses.append(assessment(review['criteria'][name], name in rules['na_allowed']))
    need(set(review.get('edges', {})) == set(snapshot['edges']), 'Review must address every traceability edge')
    plan = None
    for key, edge in snapshot['edges'].items():
        if 'inherited' in review['edges'][key]:
            # Recomputed from the pinned priors, so a reviewer cannot mint an inherited PASS or skip a required fresh reading.
            if plan is None:
                pinned = {p['label']: p['review_digest'] for p in request.get('priors', [])}
                priors = [p for p in prior_reviews(root, folder, meta) if pinned.get(p['label']) == digest(p['review'])]
                need(len(priors) == len(pinned), 'Inherited assessment source missing or changed')
                plan = review_plan(snapshot, load(folder / 'contract.json')['mode'], identity, priors)
            kind, expected = plan.get(key, ('fresh', 'changed'))
            need(kind == 'inherit', 'Inherited assessment not allowed for ' + key + ' (' + str(expected) + '); remove "inherited" and assess afresh')
            # A missing context (package prepared before contexts existed) only makes a later stage-review re-read the edge.
            given = review['edges'][key]
            need(given.get('inherited') == expected['inherited'] and without_inheritance(given) == without_inheritance(expected) and
                 given.get('context', expected.get('context')) == expected.get('context'),
                 'Inherited assessment does not match its reviewed source: ' + key + '; remove "inherited" and assess afresh')
        is_due = due(edge, snapshot['stage'])
        result = assessment(review['edges'][key], not is_due)
        if is_due:
            statuses.append(result)
            if edge['type'] == 'conflicts' and all(snapshot['entities'][edge[k]]['status'] == 'active' for k in ('from', 'to')):
                statuses.append('FAIL')
    need(isinstance(review.get('findings'), list), 'Review needs findings register')
    finding_ids = set()
    for finding in review['findings']:
        token(finding.get('id'))
        need(finding['id'] not in finding_ids, 'Duplicate finding ID')
        finding_ids.add(finding['id'])
        need(finding.get('kind') in ('contradiction', 'contract_gap', 'hypothesis', 'missing_evidence') and
             finding.get('severity') in ('Critical', 'High', 'Medium', 'Low') and
             finding.get('state') in ('open', 'resolved', 'retracted'), 'Invalid finding')
        need(finding.get('reason') and finding.get('sources'), 'Finding requires sources and reasoning')
        need(isinstance(finding['sources'], list) and all(reference(snapshot, x) and x != 'mechanical-report' for x in finding['sources']), 'Unknown finding source')
        if finding['kind'] in ('contradiction', 'contract_gap'):
            need(finding.get('counterexample') and finding.get('closure'), 'Confirmed finding needs counterexample and closure condition')
        if finding['state'] == 'open':
            if finding['kind'] in ('contradiction', 'contract_gap') and finding['severity'] != 'Low':
                statuses.append('FAIL')
            if finding['kind'] == 'missing_evidence':
                statuses.append('UNKNOWN')
    previous_open = {f['id'] for f in carried_findings(root, meta, prior_reviews(root, folder, meta)) if f['state'] == 'open'}
    need(previous_open <= finding_ids, 'Previously open findings must be explicitly rechecked, not dropped')
    gates = {'document': 'FAIL' if 'FAIL' in statuses else 'UNKNOWN' if 'UNKNOWN' in statuses else 'PASS'}
    for name in ('formal', 'runtime'):
        gates[name] = assessment(review.get(name, {}), not rules[name + '_required'])
        if gates[name] == 'PASS':
            refs = review[name]['evidence']
            builtin = name == 'formal' and 'mechanical-report' in refs and model and all(x['status'] == 'PASS' for x in model)
            external = False
            covered_targets = set()
            for ref in refs:
                entity = snapshot['entities'].get(ref, {})
                data = entity.get('data', {})
                targets = data.get('targets', {})
                if entity.get('kind') == 'evidence' and data.get('level') == ('implementation_test' if name == 'runtime' else 'model'):
                    need(data.get('executed') is True and data.get('command') and data.get('exit_code') == 0, 'Executed evidence needs successful command/result')
                    need(targets and all(k in snapshot['entities'] and digest(snapshot['entities'][k]) == v for k, v in targets.items()), 'Evidence targets missing or stale')
                    need(any(snapshot['entities'][x]['kind'] == 'source' for x in entity['basis']), 'Evidence needs imported execution report')
                    external = True
                    covered_targets.update(targets)
            need(builtin or external, name + ' PASS needs applicable executed evidence, not a scenario or assertion')
            required_targets = {k for k, e in snapshot['entities'].items() if e['status'] == 'active' and
                                STAGES.index(e['stage']) <= STAGES.index(snapshot['stage']) and
                                e['kind'] == ('obligation' if name == 'runtime' or not model else 'behavior')}
            need(builtin or required_targets <= covered_targets, name + ' evidence does not cover its declared candidate scope')
        if rules[name + '_required']:
            statuses.append(gates[name])
    if any(r['status'] == 'FAIL' for r in model):
        statuses.append('FAIL')
        gates['formal'] = 'FAIL'
    gate = 'FAIL' if 'FAIL' in statuses else 'UNKNOWN' if 'UNKNOWN' in statuses else 'PASS'
    return {'gate': gate, 'gates': gates, 'model_checks': model, 'impact': impact(old, snapshot)}, snapshot, review


def approved(root, snapshot, stage):
    # Approval is bound to the entire revision plus policy, not just a title/version.
    for path in (root / 'approvals').glob('*.json'):
        event = load(path)
        if event['revision'] == current(root) and event['stage'] == stage and event['snapshot_hash'] == digest(snapshot) and event['policy_hash'] == digest(policy(root)):
            return True
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('docs/specification'))
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    init.add_argument('--exploration', type=Path, help='Required /explore result; default: 00-exploration.md next to the store')
    init.add_argument('--profile', choices=sorted(PROFILES), default='compact', help='compact: REQ, DESIGN; extended: REQ, ARCH, DESIGN')
    src = sub.add_parser('source'); src.add_argument('--file', type=Path, required=True); src.add_argument('--id', required=True)
    begin = sub.add_parser('begin'); begin.add_argument('--stage', choices=STAGES, required=True); begin.add_argument('--contract', type=Path); begin.add_argument('--work', type=Path, required=True)
    begin.add_argument('--from', dest='source_package', type=Path, help='Unaccepted package on the same base: carry its candidate, contract, findings and reviewed edge assessments')
    for name in ('check', 'prepare-review', 'accept', 'impact', 'diff'):
        cmd = sub.add_parser(name); cmd.add_argument('--package', type=Path, required=True)
    show = sub.add_parser('show'); show.add_argument('--package', type=Path, required=True); show.add_argument('ids', nargs='+')
    assess = sub.add_parser('assess', help='Merge JSON assessments (a shard result or reviewer file) into review.json')
    assess.add_argument('--package', type=Path, required=True); assess.add_argument('files', type=Path, nargs='+')
    approve = sub.add_parser('approve'); approve.add_argument('--stage', choices=STAGES, required=True); approve.add_argument('--decision', required=True)
    sub.add_parser('status')
    sub.add_parser('sync-docs')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == 'init':
        exploration = args.exploration or root.parent / '00-exploration.md'
        need(exploration.name == '00-exploration.md', 'Input must be 00-exploration.md produced by /explore')
        need(exploration.is_file(), 'Missing 00-exploration.md; complete /explore first or specify --exploration')
        need(exploration.read_text(encoding='utf-8-sig').strip(), 'Exploration must not be empty')
        root.mkdir(parents=True, exist_ok=False)
        defaults = {'formal_required': False, 'runtime_required': False, 'na_allowed': ['external_assumptions']}
        write(root / 'policy.json', {'version': 2, 'profile': args.profile,
                                     'stages': {s: copy.deepcopy(defaults) for s in PROFILES[args.profile]}})
        source = import_source(root, exploration, 'SRC-EXPLORATION')
        source['data']['role'] = 'exploration'
        snapshot = {'schema': 2, 'stage': STAGES[0], 'entities': {source['id']: source}, 'edges': {}, 'documents': {}}
        revision = publish(root, snapshot, {'bootstrap': True}, None)
        print(canonical({'revision': revision, 'profile': args.profile, 'stages': PROFILES[args.profile],
                         'state': 'initialized; no content reviewed or approved'}))
        return 0
    need(root.is_dir(), 'Store not initialized')
    if args.command == 'sync-docs':
        with locked(root):
            revision = sync_docs(root)
        print(canonical({'revision': revision, 'documents': str(root.parent), 'state': 'documents synchronized; approval unchanged'}))
        return 0
    if args.command == 'source':
        print(canonical(import_source(root, args.file, args.id)))
        return 0
    if args.command == 'begin':
        snapshot, manifest = read_revision(root)
        stages = profile_stages(root)
        need(args.stage in stages, 'Stage ' + args.stage + ' is not in the policy profile: ' + ', '.join(stages))
        need(snapshot['stage'] in stages, 'Current stage is outside the policy profile; restore the profile the store was built with')
        previous_stage = stages.index(snapshot['stage'])
        target = stages.index(args.stage)
        need(target <= previous_stage + 1, 'Do not skip document stages')
        if target > previous_stage:
            need(approved(root, snapshot, snapshot['stage']), 'Previous stage needs explicit approval for this revision')
        need(target >= previous_stage, 'For backchannel edits keep current stage; repair affected earlier entities/documents in one package')
        need(args.contract or args.source_package, 'begin needs --contract or --from')
        meta = {'id': uid(), 'root': str(root), 'base': manifest['revision'], 'stage': args.stage, 'created': now()}
        contract = args.contract
        if args.source_package:
            prior = args.source_package.resolve()
            pmeta = load(prior / 'package.json')
            need(pmeta['root'] == str(root), 'Package belongs to a different store')
            need(pmeta['base'] == manifest['revision'], 'STALE BASE: --from package was built on another revision; reconcile both sides manually')
            need(pmeta['stage'] == args.stage, '--from package targets another stage')
            snapshot, contract = load(prior / 'candidate.json'), contract or prior / 'contract.json'
            meta['from'] = str(prior)
        args.work.mkdir(parents=True, exist_ok=False)
        snapshot['stage'] = args.stage
        write(args.work / 'package.json', meta)
        write(args.work / 'candidate.json', snapshot)
        write(args.work / 'contract.json', load(contract))
        print(str(args.work.resolve()))
        return 0
    if args.command in ('diff', 'show'):
        folder = args.package.resolve()
        meta, snapshot, old = candidate(root, folder)
        if args.command == 'show':
            result = {}
            for key in args.ids:
                need(key in snapshot['entities'] or key in snapshot['edges'], 'Unknown entity or edge: ' + key)
                result[key] = snapshot['edges'].get(key) or dict(snapshot['entities'][key], edges=sorted(
                    k for k, e in snapshot['edges'].items() if key in (e['from'], e['to'])))
            print(json.dumps(result, ensure_ascii=False, indent=1))
            return 0
        previous = previous_candidate(meta)
        print(json.dumps({'base': diff(old, snapshot), 'previous': diff(previous, snapshot) if previous else None}, ensure_ascii=False, indent=1))
        return 0
    if args.command == 'assess':
        folder = args.package.resolve()
        meta, snapshot, _ = candidate(root, folder)
        results = [dict(apply_assessments(root, folder, meta, snapshot, load(path)), file=str(path)) for path in args.files]
        unknown = results[-1]['unknown_edges']
        print(json.dumps({'files': [{k: r[k] for k in ('file', 'applied', 'notes')} for r in results],
                          'unknown_edges': len(unknown), 'unknown_sample': unknown[:20]}, ensure_ascii=False, indent=1))
        return 0
    if args.command in ('check', 'prepare-review', 'accept', 'impact'):
        folder = args.package.resolve()
        if args.command == 'accept':
            with locked(root):
                result, snapshot, review = review_gate(root, folder)
                need(result['gate'] == 'PASS', 'Candidate cannot be accepted: ' + canonical(result))
                revision = publish(root, snapshot, review, current(root), load(folder / 'contract.json'), result)
            print(canonical({'revision': revision, 'state': 'accepted; not user-approved', **result}))
            return 0
        meta, snapshot, old = candidate(root, folder)
        if args.command == 'impact':
            print(canonical(impact(old, snapshot)))
            return 0
        model = validate(root, snapshot)
        contract_check(load(folder / 'contract.json'), snapshot)
        report = {'mechanical': 'FAIL' if any(r['status'] == 'FAIL' for r in model) else 'PASS',
                  'semantic': 'UNKNOWN', 'models': model, 'impact': impact(old, snapshot)}
        if args.command == 'prepare-review':
            need(report['mechanical'] == 'PASS', 'Repair mechanical failures before review')
            identity = review_identity(root, folder, meta, snapshot)
            contract = load(folder / 'contract.json')
            sources = prior_reviews(root, folder, meta)
            plan = review_plan(snapshot, contract['mode'], identity, sources)
            assessment = {'status': 'UNKNOWN', 'reason': 'Not reviewed', 'evidence': []}
            edges = {}
            for key, edge in snapshot['edges'].items():
                if not due(edge, snapshot['stage']):
                    edges[key] = {'status': 'NOT_APPLICABLE', 'reason': 'due_stage %s is after %s; assess at that stage' % (edge['due_stage'], snapshot['stage']), 'evidence': []}
                elif plan[key][0] == 'inherit':
                    edges[key] = plan[key][1]
                else:
                    edges[key] = {'status': 'UNKNOWN', 'reason': NOT_REVIEWED[plan[key][1]], 'evidence': []}
            review = {'identity': identity, 'reviewer': '',
                      'criteria': {c: copy.deepcopy(assessment) for c in CRITERIA}, 'edges': edges,
                      'findings': carried_findings(root, meta, sources),
                      'formal': copy.deepcopy(assessment), 'runtime': copy.deepcopy(assessment)}
            write(folder / 'review-request.json', {'identity': identity, 'created': now(), 'report': report,
                  'priors': [{'label': p['label'], 'review_digest': digest(p['review'])} for p in sources]})
            write(folder / 'review.json', review)
            previous = previous_candidate(meta)
            (folder / 'review-brief.md').write_text(review_brief(meta, contract, snapshot, old, previous, sources, review), encoding='utf-8', newline='\n')
            preview = folder / 'preview'
            preview.mkdir(exist_ok=False)
            for name, body in render(snapshot).items():
                (preview / name).write_text(body, encoding='utf-8')
            (folder / 'shards').mkdir(exist_ok=False)
            shards = review_shards(snapshot, old, review)
            for shard in shards:
                # indent=1 keeps lines readable for a reviewer while cutting the size of nested entity data.
                with (folder / 'shards' / (shard['shard'] + '.json')).open('x', encoding='utf-8', newline='\n') as stream:
                    stream.write(json.dumps(shard, ensure_ascii=False, indent=1) + '\n')
            report['shards'] = [{'shard': x['shard'], 'edges': len(x['edges']), 'sections': x['sections']} for x in shards]
            with (folder / 'review-brief.md').open('a', encoding='utf-8', newline='\n') as brief:
                brief.write('\n## Шарды для оценки рёбер\n\nФайлы shards/<ID>.json; ответ — shards/<ID>.result.json, вносится командой assess.\n\n')
                brief.write(''.join('- %s: %d рёбер; %s\n' % (x['shard'], x['edges'], ', '.join(x['sections'])) for x in report['shards']) or 'Нет.\n')
        elif (folder / 'review.json').exists():
            result, _, _ = review_gate(root, folder)
            print(canonical(result))
            return 0 if result['gate'] == 'PASS' else 1
        print(canonical(report))
        return 1 if report['mechanical'] == 'FAIL' else 0
    snapshot, manifest = read_revision(root)
    if args.command == 'approve':
        need(args.stage in snapshot['documents'] and snapshot['entities'] and manifest['contract'], 'Approve only a document in a nonempty accepted revision')
        need(manifest['contract']['mode'] == 'stage-review', 'Complete a stage-review package before user approval')
        need(args.decision.strip(), 'Provide the actual user approval reference/quote')
        need(manifest['policy_hash'] == digest(policy(root)), 'Policy changed; re-review before approval')
        with locked(root):
            need(current(root) == manifest['revision'], 'Revision changed while approving')
            write(root / 'approvals' / (uid() + '.json'), {'stage': args.stage, 'revision': manifest['revision'],
                  'snapshot_hash': digest(snapshot), 'policy_hash': digest(policy(root)), 'decision': args.decision, 'created': now()})
        print(canonical({'approval': 'recorded', 'revision': manifest['revision']}))
        return 0
    stages = profile_stages(root)
    print(canonical({'revision': manifest['revision'], 'profile': policy(root)['profile'], 'stage': snapshot['stage'],
                     'final_stage': snapshot['stage'] == stages[-1], 'approved': approved(root, snapshot, snapshot['stage']),
                     'policy_current': manifest['policy_hash'] == digest(policy(root)),
                     'verification': manifest.get('verification'),
                     'verification_state': 'CURRENT' if manifest['policy_hash'] == digest(policy(root)) else 'STALE',
                     'state': 'accepted' if manifest['contract'] else 'initialized',
                     'artifacts': str(root / 'revisions' / manifest['revision']),
                     'documents': {stage: str(root.parent / DOCUMENT_FILES[stage]) for stage in snapshot['documents']}}))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Invalid, OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as error:
        print(canonical({'gate': 'UNKNOWN', 'error': str(error)}), file=sys.stderr)
        sys.exit(2)
