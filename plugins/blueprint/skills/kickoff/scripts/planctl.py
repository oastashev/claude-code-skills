#!/usr/bin/env python3
"""Mechanical kickoff checks. Does not certify semantic judgments or consent."""
import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path, PurePosixPath

CRITERIA = ('baseline scope atomicity completeness consistency verifiability '
            'feasibility contracts traceability assumptions').split()
# Document names published by specify next to its store.
SPECIFICATION_DOCUMENTS = ('01-BRD.md', '02-TRD.md', '03-SAD.md', '04-SDD.md', '05-DDD.md')


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


def parallel_analysis(plan, limits=(1, 2, 4)):
    """Conservative barrier-wave schedules; never infers semantic independence."""
    changes = {c['id']: c for c in plan['changes']}
    if not changes or len(changes) != len(plan['changes']):
        raise ValueError('Parallel analysis needs unique changes')
    if not limits or any(type(n) is not int or n < 1 for n in limits):
        raise ValueError('Worker limits must be positive integers')
    order, ancestors = [], {}
    while len(order) < len(changes):
        ready = sorted(k for k, c in changes.items() if k not in ancestors and set(c['depends_on']) <= ancestors.keys())
        if not ready:
            raise ValueError('Dependency cycle or unknown dependency')
        for cid in ready:
            deps = set(changes[cid]['depends_on'])
            ancestors[cid] = deps | set().union(*(ancestors[d] for d in deps)) if deps else set()
            order.append(cid)
    analysis = plan.get('parallelism', {})
    assessments = {}
    for row in analysis.get('pairs', []):
        a, b = row['a'], row['b']
        pair = tuple(sorted((a, b)))
        if a == b or a not in changes or b not in changes or pair in assessments:
            raise ValueError('Invalid/duplicate parallel pair')
        if row['status'] not in ('independent', 'conflict', 'unknown'):
            raise ValueError('Invalid parallel assessment')
        if not nonempty(row['reason']) or not strings(row['evidence']) or not row['evidence']:
            raise ValueError('Parallel assessment needs reason and evidence')
        assessments[pair] = row
    pairs, errors, relations = [], [], {}
    ids = sorted(changes)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            row = assessments.get((a, b))
            shared = sorted(set(changes[a]['writes']) & set(changes[b]['writes']))
            if a in ancestors[b] or b in ancestors[a]:
                status, reason = 'dependent', 'Direct or transitive implementation dependency'
            elif shared:
                status, reason = 'conflict', 'Shared write declarations: ' + ', '.join(shared)
            elif row:
                status, reason = row['status'], row['reason']
            else:
                status, reason = 'unknown', 'No reviewed evidence of semantic/resource independence'
            if row and row['status'] == 'independent' and status in ('dependent', 'conflict'):
                errors.append('Independence contradicts graph/shared writes: ' + a + '/' + b)
            relations[(a, b)] = status
            pairs.append(dict(a=a, b=b, status=status, reason=reason,
                              evidence=row['evidence'] if row else [], shared_writes=shared))
    estimates = analysis.get('estimates')
    weights = {cid: 1 for cid in changes}
    if estimates is not None:
        values = estimates['values']
        if (set(values) != set(changes) or not nonempty(estimates['unit']) or not nonempty(estimates['basis']) or
                any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values.values())):
            raise ValueError('Estimates need one positive finite value per change, shared unit and basis')
        weights = values
    lengths, chains = {}, {}
    for cid in order:
        deps = changes[cid]['depends_on']
        previous = max(sorted(deps), key=lambda d: lengths[d]) if deps else None
        lengths[cid] = weights[cid] + (lengths[previous] if previous else 0)
        chains[cid] = (chains[previous] if previous else []) + [cid]
    tail = max(order, key=lambda cid: lengths[cid])
    scenarios = []
    for workers in sorted(set(limits)):
        completed, waves = set(), []
        while len(completed) < len(changes):
            ready = sorted(cid for cid, c in changes.items() if cid not in completed and set(c['depends_on']) <= completed)
            chosen = []
            for cid in ready:
                if len(chosen) < workers and all(relations[tuple(sorted((cid, other)))] == 'independent' for other in chosen):
                    chosen.append(cid)
            if not chosen:
                raise ValueError('Cannot schedule dependency graph')
            waves.append(chosen)
            completed.update(chosen)
        scenario = dict(workers=workers, waves=waves, wave_count=len(waves),
                        observed_width=max(map(len, waves)))
        if estimates is not None:
            sequential = sum(weights.values())
            duration = sum(max(weights[cid] for cid in wave) for wave in waves)
            scenario.update(estimated_work_span=duration, sequential_work_span=sequential,
                            conditional_reduction_percent=round(100 * (1 - duration / sequential), 2))
        scenarios.append(scenario)
    checkpoints = [dict(id=c['id'], timing=c['timing'], changes=c['changes'], owner=c['owner'])
                   for c in plan.get('conditions', []) if c['status'] == 'open']
    return dict(analysis_state='PARTIAL' if any(p['status'] == 'unknown' for p in pairs) else 'COMPLETE',
                pairs=pairs, scenarios=scenarios, open_conditions=checkpoints, errors=errors,
                longest_dependency_chain=dict(changes=chains[tail], weight=lengths[tail],
                    unit=estimates['unit'] if estimates else 'change_count'),
                timing='ESTIMATED' if estimates else 'UNKNOWN',
                limitations=['Greedy deterministic barrier waves, not an optimal schedule or maximum parallelism.',
                             'Different paths do not prove independence; glob overlap, APIs and resources require review.',
                             'Estimates assume comparable workers and exclude merge overhead, retries and human waiting.',
                             'Scenarios are advisory; open conditions still block their execution barriers.'])


def check(root, plan_path, execution=False):
    plan = read(path(root, plan_path))
    baseline_path = path(root, plan['baseline'])
    baseline = read(baseline_path)
    identity = {'plan_hash': digest(path(root, plan_path)),
                'baseline_hash': digest(baseline_path)}
    errors = []

    def need(ok, message):
        if not ok:
            errors.append(message)

    def refs(values, allowed, label, required=False):
        need(strings(values), label + ': expected unique string list')
        if not strings(values):
            return set()
        need(not required or bool(values), label + ': empty')
        need(set(values) <= set(allowed), label + ': unknown reference')
        return set(values)

    need(plan['schema'] == 1 and baseline['schema'] == 1, 'Unsupported schema')
    need(nonempty(plan['id']) and nonempty(plan['revision']), 'Missing identity')
    need(bool(baseline['files']), 'Empty baseline')
    for name, expected in baseline['files'].items():
        p = path(root, name)
        need(p.is_file() and digest(p) == expected, 'STALE or missing: ' + name)
    for field in ('snapshot', 'audit_gates', 'audit_manifest'):
        need(plan[field] in baseline['files'], field + ' not bound to baseline')
    snap_path = path(root, plan['snapshot'])
    need(snap_path.parent.name == plan['revision'], 'Revision/snapshot mismatch')
    store = snap_path.parent.parent.parent
    need(not (store / 'DOCS-PENDING.json').exists(), 'Specification publication pending')
    bound_paths = {path(root, name) for name in baseline['files']}
    required_paths = [store / 'CURRENT', store / 'policy.json',
                      snap_path.parent / 'manifest.json', snap_path.parent / 'review.json']
    required_paths += [store.parent / name for name in SPECIFICATION_DOCUMENTS]
    exploration = path(root, plan.get('exploration', (store.parent / '00-exploration.md').relative_to(root).as_posix()))
    required_paths.append(exploration)
    for required in required_paths:
        need(required.resolve() in bound_paths, 'Required baseline input absent: ' + str(required))
    current = store / 'CURRENT'
    need(current.is_file() and current.read_text(encoding='utf-8').strip() == plan['revision'],
         'CURRENT revision mismatch')
    need(any(p.parent == store / 'approvals' for p in bound_paths), 'No bound specify approval')
    snap = read(snap_path)
    need(snap['schema'] == 1 and snap['stage'] == 'DDD', 'DDD snapshot required')
    entities = snap['entities']
    exploration_source = entities.get(plan.get('exploration_source', 'SRC-EXPLORATION'), {})
    need(exploration_source.get('kind') == 'source' and exploration_source.get('status') == 'active',
         'Exploration must reference an active source')
    need(exploration.is_file() and digest(exploration) == exploration_source.get('data', {}).get('sha256'),
         'Exploration differs from selected source snapshot')
    for entity in entities.values():
        if entity['kind'] == 'source':
            source = store / 'sources' / (entity['data']['sha256'] + '.txt')
            need(source.resolve() in bound_paths, 'Unbound specification source')
    active = {k: v for k, v in entities.items() if v['status'] == 'active'}
    obligations = {k for k, v in active.items() if v['kind'] == 'obligation'}
    scenarios = {k for k, v in active.items() if v['kind'] == 'scenario'}
    need(nonempty(plan['scope']['goal']) and nonempty(plan['scope']['phase']), 'Empty scope')
    refs(plan['scope']['basis'], active, 'scope.basis', True)
    need(set(plan['requirements']) == obligations, 'Every active obligation must be classified exactly once')

    audit_manifest = read(path(root, plan['audit_manifest']))
    binding = audit_manifest.get('specification', {})
    need(binding.get('revision') == plan['revision'], 'Audit revision binding missing or stale')
    need(binding.get('store') == store.relative_to(root).as_posix(), 'Audit store binding mismatch')
    audited = {}
    for item in audit_manifest['documents']:
        p = path(root, item['path'])
        need(p not in audited, 'Duplicate audited input')
        audited[p] = item
        need(item['availability'] in ('readable', 'available') and p.is_file() and digest(p) == item.get('sha256'),
             'Audit input missing or stale: ' + item['path'])
    for required in required_paths + [snap_path]:
        need(required.resolve() in audited, 'Required source absent from audit: ' + str(required))
    for entity in entities.values():
        if entity['kind'] == 'source':
            need((store / 'sources' / (entity['data']['sha256'] + '.txt')).resolve() in audited,
                 'Specification source absent from audit')
    need(any(p.parent == store / 'approvals' for p in audited), 'No specify approval in audit')

    gates = read(path(root, plan['audit_gates']))
    need(gates['schema_version'] == 1, 'Audit schema unsupported')
    gate_ids = [g['id'] for g in gates['gates']]
    need(len(gate_ids) == len(set(gate_ids)), 'Duplicate audit gate')
    need(any(g.get('required') is True for g in gates['gates']), 'Audit has no mandatory gates')
    for g in gates['gates']:
        need(type(g['required']) is bool, 'Gate required must be boolean')
        need(g['status'] in ('PASS', 'FAIL', 'UNKNOWN', 'NOT_APPLICABLE'), 'Invalid gate status')
        if g['status'] == 'NOT_APPLICABLE':
            need(nonempty(g.get('explanation')), 'N/A gate needs explanation')
        if g['required']:
            need(g['status'] in ('PASS', 'NOT_APPLICABLE'), 'Mandatory audit gate: ' + g['id'])

    changes = {c['id']: c for c in plan['changes']}
    need(bool(changes) and len(changes) == len(plan['changes']), 'Empty/duplicate changes')
    mode = plan['execution']['mode']
    workers = plan['execution']['max_workers']
    need(mode in ('sequential', 'parallel'), 'Invalid execution mode')
    need(type(workers) is int and workers > 0, 'Invalid worker limit')
    need(mode != 'sequential' or workers == 1, 'Sequential needs one worker')
    waves = {}
    for cid, c in changes.items():
        need(bool(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', cid)), 'Unsafe change ID: ' + cid)
        for key in ('outcome', 'rationale', 'independence'):
            need(nonempty(c[key]), cid + ': empty ' + key)
        refs(c['basis'], active, cid + '.basis', True)
        for key, kind in (('contracts', 'contract'), ('tasks', 'task')):
            refs(c[key], {k for k, v in active.items() if v['kind'] == kind}, cid + '.' + key)
        reqs = refs(c['requirements'], obligations, cid + '.requirements', True)
        scs = refs(c['scenarios'], scenarios, cid + '.scenarios', True)
        deps = refs(c['depends_on'], changes, cid + '.depends_on')
        need(type(c['wave']) is int and c['wave'] >= 0, cid + ': invalid wave')
        waves.setdefault(c['wave'], []).append(c)
        for dep in deps & changes.keys():
            need(changes[dep]['wave'] < c['wave'], cid + ': dependency must precede wave (cycle/order)')
        need(strings(c['writes']), cid + ': invalid writes')
        for write in c['writes']:
            relative(write)
        checked = set()
        for test in c['checks']:
            need(test['scenario'] in scs, cid + ': check for unassigned scenario')
            need(nonempty(test['method']) and nonempty(test['expected']), cid + ': empty check')
            checked.add(test['scenario'])
        need(checked == scs, cid + ': every scenario needs check')
        expected = {rid for rid, r in plan['requirements'].items() if cid in r['applies_to']}
        need(reqs == expected, cid + ': applies_to mismatch')
    for members in waves.values():
        need(len(members) <= workers, 'Wave exceeds worker limit')
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                need(not set(a['writes']) & set(b['writes']), 'Shared write in wave: ' + a['id'] + '/' + b['id'])
    try:
        parallel_report = parallel_analysis(plan, (1, 2, 4, workers))
        errors.extend(parallel_report['errors'])
        pair_status = {(r['a'], r['b']): r['status'] for r in parallel_report['pairs']}
        for members in waves.values():
            for i, a in enumerate(members):
                for b in members[i + 1:]:
                    pair = tuple(sorted((a['id'], b['id'])))
                    need(pair_status[pair] == 'independent', 'Selected parallel wave lacks independence: ' + '/'.join(pair))
    except ValueError as error:
        errors.append(str(error))
        parallel_report = {'analysis_state': 'INVALID', 'error': str(error)}
    def predecessors(cid):
        found, todo = set(), list(changes[cid]['depends_on'])
        while todo:
            dep = todo.pop()
            if dep in changes and dep not in found:
                found.add(dep)
                todo.extend(changes[dep]['depends_on'])
        return found
    for rid, r in plan['requirements'].items():
        included = r['disposition'] == 'include'
        need(r['disposition'] in ('include', 'deferred', 'excluded'), rid + ': invalid disposition')
        need(nonempty(r['reason']), rid + ': missing reason')
        refs(r['basis'], active, rid + '.basis', True)
        owners = refs(r['owners'], changes, rid + '.owners', included)
        applies = refs(r['applies_to'], changes, rid + '.applies_to', included)
        scs = refs(r['scenarios'], scenarios, rid + '.scenarios', included)
        need(owners <= applies, rid + ': owner must apply requirement')
        if not included:
            need(not owners and not applies and not scs, rid + ': deferred/excluded assigned to execution')
        coverage = r.get('coverage')
        if coverage is None:
            # Legacy plans assigned the whole scenario set to every carrier.
            # Preserve that meaning; new split allocations must be explicit.
            for cid in applies & changes.keys():
                need(scs <= set(changes[cid]['scenarios']), rid + ': split scenario allocation needs explicit coverage')
            coverage = [dict(change=cid, scenario=sc, scope='local', requires=[cid])
                        for cid in applies & changes.keys() for sc in scs]
        need(isinstance(coverage, list), rid + ': coverage must be a list')
        if not isinstance(coverage, list):
            continue
        covered, carriers, pairs_seen = set(), set(), set()
        for row in coverage:
            cid, sc = row['change'], row['scenario']
            need(cid in applies and sc in scs, rid + ': coverage outside assigned requirement')
            need((cid, sc) not in pairs_seen, rid + ': duplicate coverage')
            pairs_seen.add((cid, sc))
            need(row['scope'] in ('local', 'integration'), rid + ': invalid coverage scope')
            required = refs(row['requires'], changes, rid + '.coverage.requires', True)
            need(cid in required, rid + ': coverage must include its host change')
            if cid in changes:
                need(sc in changes[cid]['scenarios'], rid + ': assigned scenario missing in ' + cid)
                need(required <= predecessors(cid) | {cid}, rid + ': scenario depends on unavailable changes')
            covered.add(sc)
            carriers.add(cid)
        need(covered == scs, rid + ': incomplete scenario coverage')
        need(carriers == applies, rid + ': every carrier needs an applicable check')
    condition_ids = set()
    for c in plan['conditions']:
        need(nonempty(c['id']) and c['id'] not in condition_ids, 'Invalid/duplicate condition ID')
        condition_ids.add(c['id'])
        need(nonempty(c['description']) and nonempty(c['owner']), 'Condition needs description/owner')
        need(c['timing'] in ('before_start', 'before_verify', 'before_release'), 'Invalid condition timing')
        refs(c['changes'], changes, 'condition.changes', True)
        need(c['status'] in ('open', 'closed'), 'Invalid condition status')
        need(strings(c['evidence']), 'Invalid condition evidence')
        need(c['status'] != 'closed' or bool(c['evidence']), 'Closed condition needs evidence')

    semantic = 'UNKNOWN'
    review_path = path(root, plan['review'])
    if review_path.is_file():
        review = read(review_path)
        bound = review.get('schema') == 1 and all(review.get(k) == v for k, v in identity.items())
        if bound:
            cs = review['criteria']
            statuses = []
            need(set(cs) == set(CRITERIA), 'Review criteria incomplete')
            for name in CRITERIA:
                c = cs.get(name, {})
                valid = (c.get('status') in ('PASS', 'FAIL', 'UNKNOWN') and
                         nonempty(c.get('reason')) and strings(c.get('evidence')) and bool(c.get('evidence')))
                statuses.append(c.get('status') if valid else 'UNKNOWN')
            semantic = 'FAIL' if 'FAIL' in statuses else 'UNKNOWN' if 'UNKNOWN' in statuses else 'PASS'
        else:
            errors.append('STALE review identity')
    approved = False
    approval_path = path(root, plan['approval'])
    if approval_path.is_file():
        a = read(approval_path)
        approved = (a.get('schema') == 1 and all(a.get(k) == v for k, v in identity.items())
                    and nonempty(a.get('decision')) and nonempty(a.get('approved_at')))
    # Recheck bytes after reading dependent inputs; this is not a filesystem transaction.
    need(digest(path(root, plan_path)) == identity['plan_hash'], 'Plan changed during check')
    need(digest(baseline_path) == identity['baseline_hash'], 'Baseline changed during check')
    for name, expected in baseline['files'].items():
        p = path(root, name)
        need(p.is_file() and digest(p) == expected, 'Input changed during check: ' + name)
    mechanical = 'FAIL' if errors else 'PASS'
    readiness = 'FAIL' if errors or semantic == 'FAIL' else 'UNKNOWN' if semantic == 'UNKNOWN' else 'READY'
    result = dict(identity, mechanical=mechanical, semantic=semantic, readiness=readiness,
                  approval=bool(approved), errors=errors, parallelism=parallel_report)
    return result, 0 if readiness == 'READY' and (not execution or approved) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    lock = sub.add_parser('lock')
    lock.add_argument('--root', required=True)
    lock.add_argument('--files', required=True)
    lock.add_argument('--out', required=True)
    chk = sub.add_parser('check')
    chk.add_argument('--root', required=True)
    chk.add_argument('--plan', required=True)
    chk.add_argument('--execution', action='store_true')
    parallel = sub.add_parser('parallel', help='Analyze potential parallelism without changing the plan')
    parallel.add_argument('--root', required=True)
    parallel.add_argument('--plan', required=True)
    parallel.add_argument('--workers', type=int, nargs='+', default=[1, 2, 4])
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).resolve()
        if args.command == 'lock':
            names = read(path(root, args.files))
            if not strings(names) or not names:
                raise ValueError('Input files must be a nonempty unique list')
            out = path(root, args.out)
            if args.out in names:
                raise ValueError('Baseline cannot include itself')
            data = {'schema': 1, 'files': {n: digest(path(root, n)) for n in names}}
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
            print(json.dumps({'baseline': args.out, 'files': len(names)}))
            return 0
        if args.command == 'parallel':
            plan_path = path(root, args.plan)
            plan_hash = digest(plan_path)
            result = parallel_analysis(read(plan_path), args.workers)
            if digest(plan_path) != plan_hash:
                raise ValueError('Plan changed during parallel analysis')
            result.update(plan_hash=plan_hash, scope='Scheduling only; baseline/review/approval not checked')
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result['errors'] else 0
        result, code = check(root, args.plan, args.execution)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
