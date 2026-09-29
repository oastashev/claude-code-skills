#!/usr/bin/env python3
"""Mechanical scaffold checks and next-change decision.

Does not certify semantic equivalence, independence or review judgments."""
import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path, PurePosixPath

CRITERIA = 'traceability equivalence coverage dependencies independence preparation'.split()
STATES = ('planned', 'active', 'archived')
EDGE_KINDS = ('api', 'data', 'migration', 'spec', 'code', 'package', 'config', 'fixture', 'resource',
              'scenario', 'manual')
SECTION = re.compile(r'^##\s+(ADDED|MODIFIED|REMOVED|RENAMED)\s+Requirements\s*$', re.IGNORECASE)
HEADING = re.compile(r'^##\s')
REQUIREMENT = re.compile(r'^###\s+Requirement:\s*(.+?)\s*$')
RENAME = re.compile(r'^\s*-\s*(FROM|TO):\s*`?\s*###\s+Requirement:\s*(.+?)\s*`?\s*$', re.IGNORECASE)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def relative(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError('Expected portable relative path: ' + str(value))
    p = PurePosixPath(value)
    if p.is_absolute() or '..' in p.parts or value != p.as_posix() or value == '.':
        raise ValueError('Unsafe/noncanonical path: ' + value)
    return value


def path(root, value):
    p = (root / relative(value)).resolve()
    if not p.is_relative_to(root.resolve()):
        raise ValueError('Path escapes root: ' + value)
    return p


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def strings(value):
    return (isinstance(value, list) and all(nonempty(v) for v in value)
            and len(value) == len(set(value)))


def parse_delta(text):
    """Returns ([{op, name, to?}], errors) for the OpenSpec delta format."""
    entries, errors, op, source = [], [], None, None
    for number, line in enumerate(text.splitlines(), 1):
        section = SECTION.match(line)
        if section or HEADING.match(line):
            if source is not None:
                errors.append('line %d: RENAMED FROM without TO' % number)
                source = None
            op = section.group(1).upper() if section else None
            continue
        if op == 'RENAMED':
            rename = RENAME.match(line)
            if rename and rename.group(1).upper() == 'FROM':
                if source is not None:
                    errors.append('line %d: RENAMED FROM without TO' % number)
                source = rename.group(2)
            elif rename:
                if source is None:
                    errors.append('line %d: RENAMED TO without FROM' % number)
                else:
                    entries.append(dict(op=op, name=source, to=rename.group(2)))
                source = None
            elif REQUIREMENT.match(line):
                errors.append('line %d: RENAMED needs FROM/TO lines' % number)
            continue
        requirement = REQUIREMENT.match(line)
        if requirement:
            if op is None:
                errors.append('line %d: requirement outside delta section' % number)
            else:
                entries.append(dict(op=op, name=requirement.group(1)))
    if source is not None:
        errors.append('RENAMED FROM without TO at end of file')
    if not entries and not errors:
        errors.append('No recognized delta operations')
    seen = set()
    for entry in entries:
        key = (entry['op'], entry['name'])
        if key in seen:
            errors.append('Duplicate %s requirement: %s' % key)
        seen.add(key)
    return entries, errors


def requirements(spec):
    if not spec.is_file():
        return set()
    return {m.group(1) for m in map(REQUIREMENT.match, spec.read_text(encoding='utf-8-sig').splitlines()) if m}


def change_files(root, change_dir):
    """Contract-bearing files of an OpenSpec change: proposal and spec deltas."""
    found = [change_dir / 'proposal.md'] + sorted((change_dir / 'specs').glob('*/spec.md'))
    return {p.relative_to(root).as_posix(): digest(p) for p in found if p.is_file()}


def schedule(ids, deps, relation, limit):
    completed, waves = set(), []
    while len(completed) < len(ids):
        ready = [cid for cid in ids if cid not in completed and deps[cid] <= completed]
        chosen = []
        for cid in ready:
            if len(chosen) < limit and all(relation(cid, other) == 'independent' for other in chosen):
                chosen.append(cid)
        if not chosen:
            raise ValueError('Cannot schedule dependency graph')
        waves.append(chosen)
        completed.update(chosen)
    return waves


def check(root, roadmap_path, limits=(1, 2, 4)):
    if not limits or any(type(n) is not int or n < 1 for n in limits):
        raise ValueError('Worker limits must be positive integers')
    roadmap_file = path(root, roadmap_path)
    roadmap = read(roadmap_file)
    plan_file = path(root, roadmap['plan'])
    adapter_file = path(root, roadmap['adapter'])
    identity = {'roadmap_hash': digest(roadmap_file), 'plan_hash': digest(plan_file)}
    plan, adapter = read(plan_file), read(adapter_file)
    errors = []

    def need(ok, message):
        if not ok:
            errors.append(message)

    need(roadmap['schema'] == 1 and plan['schema'] == 1, 'Unsupported schema')
    need(roadmap['plan_hash'] == identity['plan_hash'], 'STALE plan binding')
    need(adapter.get('plan_hash') == identity['plan_hash'], 'Adapter bound to another plan')
    need(roadmap['adapter_hash'] == digest(adapter_file), 'STALE adapter binding')
    specs_root, reviews_root = path(root, roadmap['specs']), path(root, roadmap['reviews'])
    planned = {c['id']: c for c in plan['changes']}
    entries = roadmap['changes']
    need(set(entries) == set(planned), 'Roadmap must map every plan change exactly once')
    ids = sorted(set(entries) & set(planned), key=lambda cid: (planned[cid]['wave'], cid))

    states, deltas, bound = {}, {}, {}
    for cid in ids:
        entry, change_dir = entries[cid], path(root, entries[cid]['path'])
        state = states[cid] = entry['state']
        need(state in STATES, cid + ': invalid state')
        need(PurePosixPath(entry['path']).name == cid, cid + ': change directory must match plan ID')
        need(strings(entry['writes']) and set(planned[cid]['writes']) <= set(entry['writes']),
             cid + ': writes must keep plan writes')
        for write in entry['writes']:
            relative(write)
        if state != 'active':
            need(entry['files'] == {}, cid + ': only active changes bind files')
            need(not change_dir.exists(), cid + ': ' + state + ' change directory exists')
            if state == 'archived':
                need(nonempty(entry.get('archive')) and path(root, entry['archive']).is_dir(), cid + ': archive missing')
            else:
                need(entry.get('archive') is None, cid + ': planned change has archive')
            continue
        need(entry.get('archive') is None, cid + ': active change has archive')
        need(change_dir.is_dir(), cid + ': change directory missing')
        need((change_dir / 'tasks.md').is_file(), cid + ': active change needs tasks.md')
        bound[cid] = change_files(root, change_dir)
        need(entry['path'] + '/proposal.md' in entry['files'], cid + ': proposal not bound')
        need(set(entry['files']) == set(bound[cid]), cid + ': bound files differ from change contents')
        for name, expected in entry['files'].items():
            p = path(root, name)
            need(p.is_file() and digest(p) == expected, 'STALE or missing: ' + name)
        deltas[cid] = []
        for spec in sorted((change_dir / 'specs').glob('*/spec.md')):
            found, problems = parse_delta(spec.read_text(encoding='utf-8-sig'))
            errors.extend(spec.relative_to(root).as_posix() + ': ' + p for p in problems)
            deltas[cid] += [(spec.parent.name, item) for item in found]
    active = [cid for cid in ids if states[cid] == 'active']
    archived = {cid for cid in ids if states[cid] == 'archived'}
    remaining = [cid for cid in ids if states[cid] != 'archived']

    deps = {cid: set(planned[cid]['depends_on']) & set(ids) for cid in ids}
    edges = []
    for row in roadmap['edges']:
        cid, dep = row.get('change'), row.get('depends_on')
        valid = (cid in deps and dep in deps and cid != dep and row.get('kind') in EDGE_KINDS and
                 nonempty(row.get('reason')) and strings(row.get('evidence')) and bool(row.get('evidence')))
        need(valid, 'Invalid discovered edge: ' + str(cid) + ' -> ' + str(dep))
        if valid:
            need(dep not in deps[cid], 'Edge repeats a known dependency: ' + cid + ' -> ' + dep)
            deps[cid].add(dep)
            edges.append(dict(change=cid, depends_on=dep, kind=row['kind'], source='declared', reason=row['reason']))

    added, capabilities = {}, {}
    for cid in active:
        for cap, item in deltas[cid]:
            capabilities.setdefault(cap, set()).add(cid)
            for name in ([item['name']] if item['op'] == 'ADDED' else [item['to']] if item['op'] == 'RENAMED' else []):
                owner = added.setdefault((cap, name), cid)
                need(owner == cid, 'Requirement introduced twice: ' + cap + '/' + name + ' by ' + owner + ', ' + cid)
    for cid in active:
        for cap, item in deltas[cid]:
            current = requirements(specs_root / cap / 'spec.md')
            if item['op'] == 'ADDED':
                need(item['name'] not in current, cid + ': ADDED duplicates current requirement ' + cap + '/' + item['name'])
                continue
            owner = added.get((cap, item['name']))
            if owner and owner != cid:
                if owner not in deps[cid]:
                    deps[cid].add(owner)
                    edges.append(dict(change=cid, depends_on=owner, kind='spec', source='derived',
                                      reason=item['op'] + ' of requirement introduced by ' + owner + ': ' + cap + '/' + item['name']))
            elif owner is None:
                need(item['name'] in current, cid + ': ' + item['op'] + ' of unknown requirement ' + cap + '/' + item['name'])

    order, ancestors = [], {}
    while len(order) < len(ids):
        ready = [cid for cid in ids if cid not in ancestors and deps[cid] <= ancestors.keys()]
        if not ready:
            errors.append('Dependency cycle in refined graph')
            return dict(identity, mechanical='FAIL', readiness='FAIL', next={'action': 'blocked'},
                        errors=errors, analysis_state='INVALID'), 1
        for cid in ready:
            ancestors[cid] = deps[cid] | set().union(*(ancestors[d] for d in deps[cid]))
            order.append(cid)

    # Completion means archived: nothing may be created or archived ahead of its dependencies.
    for cid in ids:
        if states[cid] != 'planned':
            need(deps[cid] <= archived, cid + ': ' + states[cid] + ' before its dependencies were archived: ' +
                 ', '.join(sorted(deps[cid] - archived)))

    divergences, refinements = [], []
    for edge in edges:
        cid, dep = edge['change'], edge['depends_on']
        if planned[dep]['wave'] >= planned[cid]['wave']:
            divergences.append(dict(kind='order', changes=[dep, cid], action='kickoff revise',
                                    detail='Dependency is not in an earlier approved wave: ' + edge['reason']))
        else:
            refinements.append(edge)

    assessed = {}
    for row in roadmap['pairs']:
        pair = tuple(sorted(str(row.get(k)) for k in ('a', 'b')))
        valid = (pair[0] != pair[1] and set(pair) <= set(active) and pair not in assessed and
                 row.get('status') in ('independent', 'conflict', 'unknown') and nonempty(row.get('reason')) and
                 strings(row.get('evidence')) and bool(row.get('evidence')))
        need(valid, 'Invalid/duplicate pair (active changes only): ' + '/'.join(pair))
        if valid:
            assessed[pair] = row
    in_plan = {tuple(sorted((r['a'], r['b']))): r for r in plan.get('parallelism', {}).get('pairs', [])}
    relations, report = {}, []
    for i, a in enumerate(remaining):
        for b in remaining[i + 1:]:
            pair = tuple(sorted((a, b)))
            row, prior = assessed.get(pair), in_plan.get(pair, {})
            shared = sorted(set(entries[a]['writes']) & set(entries[b]['writes']))
            shared += sorted('capability ' + cap for cap, owners in capabilities.items() if {a, b} <= owners)
            if a in ancestors[b] or b in ancestors[a]:
                status, reason, basis = 'dependent', 'Direct or transitive refined dependency', 'graph'
            elif shared:
                status, reason, basis = 'conflict', 'Shared writes: ' + ', '.join(shared), 'repository'
            elif prior.get('status') == 'conflict':
                status, reason, basis = 'conflict', prior['reason'], 'plan'
            elif {a, b} <= set(active):
                status, reason = (row['status'], row['reason']) if row else ('unknown', 'Not assessed in repository')
                basis = 'repository'
            else:
                status, reason = prior.get('status', 'unknown'), prior.get('reason', 'Not assessed in plan')
                basis = 'plan'
            if row and row['status'] == 'independent' and status != 'independent':
                errors.append('Independence contradicts graph/shared writes/plan: ' + '/'.join(pair))
            relations[pair] = status
            report.append(dict(a=pair[0], b=pair[1], status=status, basis=basis, reason=reason,
                               evidence=row['evidence'] if row else prior.get('evidence', []), shared=shared))

    def relation(a, b):
        return relations[tuple(sorted((a, b)))]

    # Execution may run an approved wave together; repository evidence must not contradict that.
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            if planned[a]['wave'] == planned[b]['wave'] and relation(a, b) != 'independent':
                divergences.append(dict(kind='wave', changes=[a, b], action='kickoff revise',
                                        detail='Approved wave %d pair is %s' % (planned[a]['wave'], relation(a, b))))

    reviews = {}
    for cid in active:
        review_path, status = reviews_root / (cid + '.json'), 'UNKNOWN'
        if review_path.is_file():
            review = read(review_path)
            if (review.get('schema') == 1 and review.get('change') == cid and
                    review.get('plan_hash') == identity['plan_hash'] and review.get('files') == bound[cid]):
                criteria = review['criteria']
                need(set(criteria) == set(CRITERIA), cid + ': review criteria incomplete')
                statuses = []
                for name in CRITERIA:
                    c = criteria.get(name, {})
                    valid = (c.get('status') in ('PASS', 'FAIL', 'UNKNOWN') and nonempty(c.get('reason'))
                             and strings(c.get('evidence')) and bool(c.get('evidence')))
                    statuses.append(c.get('status') if valid else 'UNKNOWN')
                status = 'FAIL' if 'FAIL' in statuses else 'UNKNOWN' if 'UNKNOWN' in statuses else 'PASS'
            else:
                errors.append(cid + ': STALE review identity')
        reviews[cid] = status

    remaining_deps = {cid: deps[cid] - archived for cid in remaining}
    estimates = plan.get('parallelism', {}).get('estimates')
    weights = {cid: 1 for cid in remaining}
    if estimates is not None:
        values = estimates.get('values', {})
        if set(planned) <= set(values) and all(type(values[cid]) in (int, float) and math.isfinite(values[cid])
                                               and values[cid] > 0 for cid in planned):
            weights = {cid: values[cid] for cid in remaining}
        else:
            errors.append('Invalid plan estimates')
            estimates = None
    lengths, chains = {}, {}
    for cid in (c for c in order if c in remaining_deps):
        previous = max(sorted(remaining_deps[cid]), key=lambda d: lengths[d]) if remaining_deps[cid] else None
        lengths[cid] = weights[cid] + (lengths[previous] if previous else 0)
        chains[cid] = (chains[previous] if previous else []) + [cid]
    tail = max(lengths, key=lambda cid: lengths[cid]) if lengths else None
    scenarios = []
    for limit in sorted(set(limits)):
        waves = schedule(remaining, remaining_deps, relation, limit)
        scenario = dict(workers=limit, waves=waves, wave_count=len(waves),
                        observed_width=max(map(len, waves), default=0))
        if estimates is not None and remaining:
            scenario.update(estimated_work_span=sum(max(weights[c] for c in w) for w in waves),
                            sequential_work_span=sum(weights.values()))
        scenarios.append(scenario)

    blocked = {}
    for condition in plan.get('conditions', []):
        if condition['status'] == 'open' and condition['timing'] == 'before_start':
            for cid in condition['changes']:
                blocked.setdefault(cid, []).append(condition['id'])
    # Recheck bytes after reading dependent inputs; this is not a filesystem transaction.
    need(digest(roadmap_file) == identity['roadmap_hash'], 'Roadmap changed during check')
    need(digest(plan_file) == identity['plan_hash'], 'Plan changed during check')

    mechanical = 'FAIL' if errors else 'PASS'
    semantic = ('FAIL' if 'FAIL' in reviews.values() else
                'UNKNOWN' if 'UNKNOWN' in reviews.values() else 'PASS')
    readiness = ('FAIL' if errors or divergences or semantic == 'FAIL' else
                 'UNKNOWN' if semantic == 'UNKNOWN' else 'READY')
    if readiness != 'READY':
        decision = dict(action='blocked', reason='Resolve errors, divergences or reviews of active changes first')
    elif not remaining:
        decision = dict(action='complete', reason='Every plan change is archived')
    else:
        # Creation depends only on archived dependencies; execution capacity is not scaffold's concern.
        pending = {cid: sorted(remaining_deps[cid]) for cid in remaining if states[cid] == 'planned'}
        candidates = [cid for cid in pending if not pending[cid]]
        if candidates:
            decision = dict(action='create', change=candidates[0], wave=planned[candidates[0]]['wave'],
                            blocked_by_conditions=blocked.get(candidates[0], []))
        else:
            decision = dict(action='wait', waiting_for=active, pending=pending,
                            reason='Every remaining change depends on changes that are not archived')
    result = dict(identity, mechanical=mechanical, plan_consistency='DIVERGED' if divergences else 'CONSISTENT',
                  semantic=semantic, readiness=readiness, next=decision, errors=errors, divergences=divergences,
                  refinements=refinements, reviews=reviews,
                  order=[dict(change=cid, wave=planned[cid]['wave'], state=states[cid],
                              depends_on=sorted(deps[cid])) for cid in order],
                  blocked_by_conditions=blocked,
                  analysis_state='PARTIAL' if any(p['status'] == 'unknown' for p in report) else 'COMPLETE',
                  pairs=report, scenarios=scenarios,
                  longest_dependency_chain=dict(changes=chains.get(tail, []), weight=lengths.get(tail, 0),
                                                unit=estimates['unit'] if estimates else 'change_count'),
                  limitations=['Approved plan waves stay authoritative; scenarios are advisory for kickoff revise.',
                               'Pairs with planned changes use plan assessments until both changes exist.',
                               'Delta parsing covers requirement headings only, not scenario semantics.',
                               'Greedy barrier waves are not an optimal schedule; estimates exclude merge overhead.'])
    return result, 0 if readiness == 'READY' else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    bind = sub.add_parser('bind', help='Print proposal/spec delta hashes of one change')
    bind.add_argument('--root', required=True)
    bind.add_argument('--change', required=True)
    chk = sub.add_parser('check', help='Validate roadmap and decide the next action')
    chk.add_argument('--root', required=True)
    chk.add_argument('--roadmap', required=True)
    chk.add_argument('--workers', type=int, nargs='+', default=[1, 2, 4])
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).resolve()
        if args.command == 'bind':
            change_dir = path(root, args.change)
            if not (change_dir / 'proposal.md').is_file():
                raise ValueError('Change has no proposal.md: ' + args.change)
            print(json.dumps({'files': change_files(root, change_dir)}, ensure_ascii=False, indent=2))
            return 0
        result, code = check(root, args.roadmap, args.workers)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
