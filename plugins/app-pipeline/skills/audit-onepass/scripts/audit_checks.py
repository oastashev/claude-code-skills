"""Батарея механических проверок комплекта /assemble.

Каждая проверка печатает статус и находки. Уровень по умолчанию указан в скобках;
окончательный уровень ставит аудитор, подтвердив находку по тексту.

Запуск: python3 audit_checks.py [--docs docs] [--json findings.json] [--only C-05,C-08]
"""
import argparse, json, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from audit_index import build, expand_ids, cells, MARKER_WORDS, EARS_PATTERNS, NUM_WORDS

FINDINGS = []


def add(check, level, where, what, hint=''):
    FINDINGS.append({'check': check, 'level': level, 'where': where, 'what': what, 'hint': hint})


def sec(name, title):
    print(f'\n=== {name} {title}')


# ---------------------------------------------------------------- C-01 трассировка
def c01(idx):
    sec('C-01', 'замкнутость цепочки BR → FR/NFR → C → M → CH → T (Blocker/Major)')
    reqs = set(idx['reqs'])
    by_kind = {}
    for cid, lst in idx['carriers'].items():
        by_kind.setdefault(cid.split('-')[0], {})[cid] = lst
    for kind, label in (('C', 'компонента (SAD)'), ('M', 'модуля (SDD)'), ('CH', 'change (DDD)')):
        covered = {r for lst in by_kind.get(kind, {}).values() for r in lst}
        missing = sorted(reqs - covered)
        ghosts = sorted(covered - reqs)
        print(f'  без {label}: {len(missing)}; ссылок на несуществующие: {len(ghosts)}')
        for r in missing:
            add('C-01', 'Blocker', r, f'требование без {label}')
        for r in ghosts:
            add('C-01', 'Major', r, f'носитель ссылается на несуществующее требование ({label})')
    # требование в двух changes
    seen = {}
    for ch, lst in by_kind.get('CH', {}).items():
        for r in lst:
            seen.setdefault(r, []).append(ch)
    dupes = {r: v for r, v in seen.items() if len(v) > 1}
    print(f'  требований в двух и более changes: {len(dupes)}')
    for r, v in dupes.items():
        add('C-01', 'Major', r, f'требование в нескольких changes: {", ".join(v)}')
    # задачи CH-00..02
    early = set()
    for ch in ('CH-00', 'CH-01', 'CH-02'):
        early |= set(by_kind.get('CH', {}).get(ch, []))
    tasks_cov = {r for lst in by_kind.get('T', {}).values() for r in lst}
    gap = sorted(early - tasks_cov)
    print(f'  требований CH-00..CH-02 без задачи: {len(gap)}')
    for r in gap:
        add('C-01', 'Major', r, 'требование раннего change без задачи T-xxx')
    empty_tasks = [t for t, lst in by_kind.get('T', {}).items() if not lst]
    print(f'  задач без требований: {len(empty_tasks)} {empty_tasks if empty_tasks else ""}')
    for t in empty_tasks:
        add('C-01', 'Minor', t, 'задача без ссылки на требование (проверить, не скрыто ли требование)')


# ---------------------------------------------------------------- C-02 версии и журналы
def c02(idx):
    sec('C-02', 'версии в шапках, STATUS и журналы изменений (Major)')
    ver = {d: h['version'] for d, h in idx['headers'].items() if h['version']}
    for d, h in idx['headers'].items():
        if not h['version']:
            continue
        j = h['journal']
        if j:
            srt = sorted(j, key=lambda v: tuple(int(x) for x in v.split('.')))
            if j != srt:
                add('C-02', 'Major', d, 'журнал изменений не отсортирован по возрастанию версии')
            if j[-1] != h['version']:
                add('C-02', 'Major', d, f"последняя строка журнала {j[-1]} ≠ версии в шапке {h['version']}")
        for dep, dv in h['based_on']:
            if dep in ver and ver[dep] != dv:
                add('C-02', 'Major', d, f'шапка ссылается на {dep} v{dv}, действующая версия {ver[dep]}')
    status = next((t for t in idx['tables'] if t['doc'] == 'STATUS.md' and 'Артефакт' in t['header']), None)
    if status:
        for r in status['rows']:
            m = re.search(r'\(v([\d.]+)\)', r.get('Статус', ''))
            art = re.search(r'docs/([\w-]+\.md)', r.get('Артефакт', '') or '')
            if m and art and art.group(1) in ver and ver[art.group(1)] != m.group(1):
                add('C-02', 'Major', 'STATUS.md', f'{art.group(1)}: в STATUS v{m.group(1)}, в шапке v{ver[art.group(1)]}')
    print(f'  версии: {ver}')
    print(f'  находок: {len([f for f in FINDINGS if f["check"] == "C-02"])}')


# ---------------------------------------------------------------- C-03 матрицы
def c03(idx):
    sec('C-03', 'матрицы трассируемости против колонки «Источник» и состава разделов (Major)')
    src_map = {}
    for rid, r in idx['reqs'].items():
        for br in re.findall(r'\bBR-\d{2}\b', r['source']):
            src_map.setdefault(br, set()).add(rid)
    matrix = {}
    for t in idx['tables']:
        if t['header'][:1] == ['BR'] or (t['header'] and t['header'][0] == 'BR'):
            for row in t['rows']:
                br = row.get('BR', '').strip()
                if re.fullmatch(r'BR-\d{2}', br):
                    cell = [v for k, v in row.items() if k != 'BR']
                    matrix[br] = set(expand_ids(' '.join(cell)))
    both = set(src_map) | set(matrix)
    bad = 0
    for br in sorted(both):
        a, b = src_map.get(br, set()), matrix.get(br, set())
        if a != b:
            bad += 1
            add('C-03', 'Major', br, f'матрица ≠ «Источник»: лишние {sorted(b - a)[:6]}, недостающие {sorted(a - b)[:6]}')
    print(f'  BR в матрице: {len(matrix)}; расхождений: {bad}')


# ---------------------------------------------------------------- C-04 механика EARS
def c04(idx):
    sec('C-04', 'механика EARS: шаблон, один SHALL, маркеры, приоритет, источник, сценарий (Major/Minor)')
    bad = {'shall': [], 'pattern': [], 'marker': [], 'prio': [], 'src': [], 'scen': []}
    for rid, r in sorted(idx['reqs'].items()):
        e = r['ears']
        if e.count('SHALL') != 1:
            bad['shall'].append(rid); add('C-04', 'Major', rid, f"SHALL встречается {e.count('SHALL')} раз")
        if not any(p.search(e) for _, p in EARS_PATTERNS):
            bad['pattern'].append(rid); add('C-04', 'Major', rid, 'формулировка не соответствует ни одному шаблону EARS')
        for w in MARKER_WORDS:
            if re.search(r'(?<![\w-])' + re.escape(w), e):
                bad['marker'].append(f'{rid}:{w}'); add('C-04', 'Minor', rid, f'слово-маркер «{w}» внутри требования')
        if r['priority'] not in ('Must', 'Should'):
            bad['prio'].append(rid); add('C-04', 'Major', rid, f"приоритет «{r['priority']}» вне {{Must, Should}}")
        if not re.search(r'\bBR-\d{2}\b', r['source']):
            bad['src'].append(rid); add('C-04', 'Major', rid, 'нет источника BR-xx')
        if len(r['scenarios'].strip()) < 12:
            bad['scen'].append(rid); add('C-04', 'Major', rid, 'нет сценария приёмки')
    total = len(idx['reqs'])
    failed = {f['where'] for f in FINDINGS if f['check'] == 'C-04'}
    print(f'  требований {total}; прошли механику {total - len(failed)} ({100 * (total - len(failed)) / max(total,1):.1f} %)')
    for k, v in bad.items():
        if v:
            print(f'  {k}: {len(v)} → {v[:8]}')


# ---------------------------------------------------------------- C-05 символы
def c05(idx):
    sec('C-05', 'символы: поля и ключи, использованные без объявления (кандидаты, Minor)')
    declared = set()
    for fields in idx['interfaces'].values():
        declared |= set(fields)
    for t in idx['tables']:
        head = ' '.join(t['header']).lower()
        if 'ключ' in head or 'поле' in head or 'атрибут' in head or 'колон' in head:
            for row in t['rows']:
                for v in row.values():
                    declared |= set(re.findall(r'`([\w.*]+)`', v or ''))
    for r in idx['reqs'].values():
        if re.search(r'SHALL (write|keep|record|append).{0,60}(fields|columns|ключ)', r['ears']):
            declared |= set(re.findall(r'`(\w+)`', r['ears']))
    declared |= set(re.findall(r'`([\w.]+)`\s*[—:-]', '\n'.join(idx['text'].values())))
    used = {s_: i for s_, i in idx['symbols'].items() if i['kind'] in ('field', 'config-key')}
    # интересны только имена контрактной формы: snake_case или точечный ключ
    undeclared = sorted(s_ for s_ in used
                        if s_ not in declared and ('_' in s_ or '.' in s_))
    print(f'  символов-полей и ключей: {len(used)}; без объявления: {len(undeclared)}')
    for s_ in undeclared[:60]:
        docs = ', '.join(used[s_]['docs'])
        add('C-05', 'Minor', s_, f'используется в {docs}, но не объявлен ни в одном контракте или таблице ключей')
    print(f'  кандидаты: {undeclared[:14]}')


# ---------------------------------------------------------------- C-06 контракты
def c06(idx):
    sec('C-06', 'контракты: счётчик ключей в сценарии против состава в формулировке (Major)')
    for rid, r in idx['reqs'].items():
        m = re.search(r'ровно (\d+|' + '|'.join(NUM_WORDS) + r')\s+(?:обязательных\s+)?ключ', r['scenarios'])
        if not m:
            continue
        raw = m.group(1).lower()
        n = int(raw) if raw.isdigit() else NUM_WORDS[raw]
        head = re.split(r'\bplus\b|;', r['ears'])[0]
        fields = [f for f in re.findall(r'`(\w+)`', head)]
        if not fields:
            continue
        if len(set(fields)) != n:
            add('C-06', 'Major', rid,
                f'сценарий обещает {n} ключей, в основной части формулировки перечислено {len(set(fields))}: {sorted(set(fields))}')
    # поля объявленных типов против обращений вида obj.field в псевдокоде
    known = set()
    for f in idx['interfaces'].values():
        known |= set(f)
    ts_fields = set()
    for d, txt in idx['text'].items():
        for block in re.findall(r'```ts\n(.*?)```', txt, re.S):
            ts_fields |= set(re.findall(r'\b[a-z]\.(\w{3,})\b', block))
    JS_BUILTINS = {'map', 'test', 'filter', 'slice', 'length', 'split', 'join', 'push',
                   'includes', 'match', 'some', 'every', 'replace', 'trim', 'concat',
                   'startsWith', 'endsWith', 'toString', 'keys', 'values', 'entries',
                   'catch', 'then', 'find', 'sort', 'flat', 'exec', 'parse', 'stringify'}
    unknown = sorted(f for f in ts_fields
                     if f not in known and f not in JS_BUILTINS and not f[0].isupper())
    print(f'  полей объявлено {len(known)}; обращений вида x.field вне объявлений: {len(unknown)} → {unknown[:12]}')
    for f in unknown:
        add('C-06', 'Major', f'поле .{f}', 'обращение к полю, которого нет ни в одном объявленном типе')
    print(f'  находок: {len([f for f in FINDINGS if f["check"] == "C-06"])}')


# ---------------------------------------------------------------- C-07 словари
def c07(idx):
    sec('C-07', 'закрытые словари: у каждого значения есть писатель и читатель (Blocker/Major)')
    body = {rid: (r['ears'] + ' ' + r['note'] + ' ' + r['scenarios']) for rid, r in idx['reqs'].items()}
    for name, v in idx['vocab'].items():
        if v['declared'] and v['declared'] != v['actual']:
            add('C-07', 'Major', f'словарь {name}',
                f"объявлено {v['declared']} значений, перечислено {v['actual']}")
        for val in v['values']:
            writers = [rid for rid, t in body.items() if re.search(r'`?' + re.escape(val) + r'`?', t) and
                       re.search(r'SHALL[^.]*' + re.escape(val), body[rid])]
            mentions = [rid for rid, t in body.items() if val in t]
            if not mentions:
                add('C-07', 'Major', f'{name}: {val}', 'значение словаря не упомянуто ни одним требованием')
            elif not writers:
                add('C-07', 'Minor', f'{name}: {val}',
                    f'нет требования, которое его устанавливает; упоминают: {mentions[:4]}')
        print(f'  {name}: значений {v["actual"]}' + (f" (объявлено {v['declared']})" if v['declared'] else ''))
    print(f'  находок: {len([f for f in FINDINGS if f["check"] == "C-07"])}')


# ---------------------------------------------------------------- C-08 сигнатуры
def c08(idx):
    sec('C-08', 'сигнатуры против вызовов: арность и поля (Blocker)')
    fns = idx['functions']
    checked = 0
    for c in idx['calls']:
        sig = fns.get(c['name'])
        if not sig:
            continue
        checked += 1
        if c['arity'] and sig['arity'] and c['arity'] != sig['arity']:
            add('C-08', 'Major', f"{c['doc']}: {c['name']}",
                f"вызов с {c['arity']} аргументами против объявления с {sig['arity']}: {c['text']}",
                'объявление: ' + ', '.join(sig['params']) +
                ' — Blocker, если это нормативный алгоритм, Minor, если сокращение в прозе')
    print(f'  объявлено функций {len(fns)}; вызовов сопоставлено {checked}; '
          f"находок {len([f for f in FINDINGS if f['check'] == 'C-08'])}")


# ---------------------------------------------------------------- C-09 приоритеты
def c09(idx):
    sec('C-09', 'Must, достижимый только через Should (Blocker/Major)')
    prio = {rid: r['priority'] for rid, r in idx['reqs'].items()}
    for rid, r in idx['reqs'].items():
        if prio.get(rid) != 'Must':
            continue
        refs = set(re.findall(r'\b(?:FR|NFR)-\d{3}\b', r['ears'] + ' ' + r['scenarios'])) - {rid}
        if not refs:
            continue
        shoulds = [x for x in refs if prio.get(x) == 'Should']
        musts = [x for x in refs if prio.get(x) == 'Must']
        if shoulds and not musts:
            add('C-09', 'Major', rid,
                f'Must ссылается только на Should: {shoulds} — результат недостижим без необязательного')
    print(f'  находок: {len([f for f in FINDINGS if f["check"] == "C-09"])}')


# ---------------------------------------------------------------- C-10 конфликты триггеров
def c10(idx):
    sec('C-10', 'два требования на один вход с разным исходом (Blocker)')
    def norm(e):
        m = re.match(r'^(WHEN|WHILE|IF|WHERE)\s+(.*?)(?:,\s*(?:THEN\s+)?)?(?:the\s+\w+[\w\s-]*|Factory)\s+SHALL', e)
        if not m:
            return None
        t = m.group(2).lower()
        t = re.sub(r'[`.,]', '', t)
        t = re.sub(r'\b(the|a|an|of|its|their|that|this)\b', '', t)
        return ' '.join(sorted(t.split()))
    buckets = {}
    for rid, r in idx['reqs'].items():
        k = norm(r['ears'])
        if k and len(k) > 25:
            buckets.setdefault(k, []).append(rid)
    for k, ids in buckets.items():
        if len(ids) > 1:
            eff = {i: idx['reqs'][i]['ears'].split('SHALL', 1)[1][:60] for i in ids}
            if len(set(eff.values())) > 1:
                add('C-10', 'Major', ', '.join(ids),
                    'КАНДИДАТ: одинаковый триггер, разные исходы (норма, если требования намеренно разбиты; находка, если исходы взаимоисключающие): ' + ' || '.join(f'{i}:{e.strip()}' for i, e in eff.items()))
    # частичное пересечение: один триггер — подстрока другого
    keys = list(buckets)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            sa, sb = set(a.split()), set(b.split())
            if sa and sb and (sa < sb or sb < sa) and min(len(sa), len(sb)) >= 6:
                ids = buckets[a] + buckets[b]
                add('C-10', 'Minor', ', '.join(ids),
                    'КАНДИДАТ: триггер одного требования — частный случай другого; проверить, названо ли исключение')
    print(f'  кластеров триггеров: {len(buckets)}; находок: {len([f for f in FINDINGS if f["check"] == "C-10"])}')


# ---------------------------------------------------------------- C-11 границы в сценариях
def c11(idx):
    sec('C-11', 'сценарий достигает объявленной в требовании границы (Minor)')
    for rid, r in idx['reqs'].items():
        nums_e = set(re.findall(r'\b(\d{1,6})\b', r['ears']))
        nums_s = set(re.findall(r'\b(\d{1,6})\b', r['scenarios']))
        if nums_e and not (nums_e & nums_s):
            add('C-11', 'Minor', rid,
                f'в требовании числа {sorted(nums_e)[:4]}, в сценариях {sorted(nums_s)[:4] or "нет"} — граница не проверяется')
    print(f'  находок: {len([f for f in FINDINGS if f["check"] == "C-11"])}')


# ---------------------------------------------------------------- C-12 числовые утверждения
def c12(idx):
    sec('C-12', 'числовые утверждения в прозе против таблиц (Major/Minor)')
    counts = {}
    by_ch = {}
    for cid, lst in idx['carriers'].items():
        if cid.startswith('CH-'):
            by_ch[cid] = len(lst)
    counts['требований всего'] = len(idx['reqs'])
    for ch, n in by_ch.items():
        counts[f'требований {ch}'] = n
    interesting = [c for c in idx['claims']
                   if c['unit'].startswith(('требован', 'колон', 'ключ', 'событ'))
                   and not re.match(r'^\s*\| [\d.]+ \|', c['context'])
                   and 'Аудит v' not in c['context'] and 'аудит v' not in c['context']]
    for c in interesting:
        ctx = c['context']
        ref = None
        chs = re.findall(r'CH-\d\d', ctx)
        m = re.match(r'CH-\d\d', chs[0]) if len(set(chs)) == 1 else None
        if m and f'требований {m.group(0)}' in counts and c['unit'].startswith('требован'):
            ref = counts[f'требований {m.group(0)}']
        if ref is not None and ref != c['n']:
            add('C-12', 'Major', c['doc'], f'утверждение «{c["n"]} {c["unit"]}» против таблицы ({ref}): …{ctx[-110:]}')
    print(f'  числовых утверждений про требования/колонки/ключи/события: {len(interesting)}')
    print(f'  сверено автоматически: {len([f for f in FINDINGS if f["check"] == "C-12"])} расхождений; '
          f'остальные — в ручной список отчёта')
    for c in interesting:
        add('C-12', 'info', c['doc'], f'{c["n"]} {c["unit"]}: …{c["context"][-90:]}')


# ---------------------------------------------------------------- C-13 свежесть ссылок
def c13(idx):
    sec('C-13', 'ссылка с цитатой указывает на требование, которое это и проверяет (Major)')
    stop = set('и в на по не что это the a of'.split())
    for r in idx['refs']:
        ctx = r.get('context', '')
        if re.search(r'удал|изъят|переиспольз|не переиспользуются', r['quote'] + ctx):
            continue
        req = idx['reqs'].get(r['id'])
        if not req:
            add('C-13', 'Major', f"{r['doc']} → {r['id']}", 'ссылка на несуществующее требование')
            continue
        body = (req['ears'] + ' ' + req['note'] + ' ' + req['scenarios']).lower()
        words = [w for w in re.findall(r'[\w/]{3,}', r['quote'].lower()) if w not in stop]
        if not words:
            continue
        stems = [w[:5] for w in words]
        hit = sum(1 for w in stems if w in body)
        if len(words) >= 3 and hit / len(words) < 0.34:
            add('C-13', 'Major', f"{r['doc']} → {r['id']}",
                f'цитата «{r["quote"]}» не находится в тексте {r["id"]} — вероятно, ссылка устарела')
    print(f'  ссылок с цитатой: {len(idx["refs"])}; находок: {len([f for f in FINDINGS if f["check"] == "C-13"])}')


# ---------------------------------------------------------------- C-14 распределение и теги
def c14(idx):
    sec('C-14', 'распределение по changes, теги задач, обещания автоархивации (Blocker/Major)')
    tasks = {}
    for t in idx['tables']:
        if t['header'][:2] == ['ID', 'Задача']:
            for row in t['rows']:
                tid = row.get('ID', '').strip()
                if re.fullmatch(r'T-\d{3}', tid):
                    tasks[tid] = row.get('Задача', '')
    manual = [t for t, v in tasks.items() if v.strip().startswith('`[manual]`')]
    print(f'  задач: {len(tasks)}; помечено [manual]: {manual}')
    text = '\n'.join(t for d, t in idx['text'].items() if d.startswith('05'))
    if manual and re.search(r'`\[manual\]`[^.]{0,120}(не закрывает никто|не давать)', text):
        if re.search(r'архивирует .{0,40}фабрика|архивирует `000`', text):
            add('C-14', 'Blocker', 'DDD §7/§8',
                f'задачи {manual} помечены `[manual]`, при этом документ обещает автоархивацию их change')
    print(f'  находок: {len([f for f in FINDINGS if f["check"] == "C-14"])}')


# ---------------------------------------------------------------- C-15 требование без входа
# Производные состояния: то, что не приходит извне, а вычисляется самой системой.
# Если триггер на них опирается, где-то должно быть требование, которое их ставит.
DERIVED = ('classif', 'window', 'verdict', 'event', 'phase', 'class')
PRODUCE = ('classif', 'set ', 'sets ', 'mark', 'treat', 'assign', 'record', 'derive')
HEAD_STOP = ('windows', 'windowshide')   # операционная система, а не состояние


def c15(idx):
    sec('C-15', 'требование без входа: триггер опирается на состояние, которого никто не ставит (Major, кандидаты)')

    def trigger(e):
        m = re.match(r'^(?:WHILE\s+.*?,\s*)?(WHEN|WHILE|IF|WHERE)\s+(.*?)(?:,\s*(?:THEN\s+)?)(?:the\s+[\w\s-]*?|Factory\s+|it\s+)SHALL', e)
        if m:
            return m.group(2)
        m = re.match(r'^(WHEN|WHILE|IF|WHERE)\s+(.*?)\s+SHALL', e)
        return m.group(2) if m else None

    effects = {rid: (r['ears'].split('SHALL', 1)[1].lower() if 'SHALL' in r['ears'] else '')
               for rid, r in idx['reqs'].items()}
    checked = 0
    for rid, r in idx['reqs'].items():
        t = trigger(r['ears'])
        if not t:
            continue
        checked += 1
        tl = t.lower()
        for stem in DERIVED:
            # слово целиком, а не часть snake_case-поля внешнего ответа (`api_error_status`)
            m = re.search(r'(?<![\w_])([a-z-]*' + stem + r'[a-z-]*)(?![\w_])', tl)
            if not m:
                continue
            head = m.group(1)
            if head in HEAD_STOP:
                break
            producer = None
            # ищем любую словоформу того же корня: «classification» ↔ «classify»
            hre = re.compile(r'(?<![\w])[a-z-]*' + stem + r'[a-z-]*(?![\w])')
            for other, eff in effects.items():
                if other == rid:
                    continue
                hm = hre.search(eff)
                # производит тот, чьё действие ставит это состояние: глагол-присваиватель
                # стоит до конца упоминания («classify the window as…», «classification»),
                # а не после него («send the five-hour-window notification» — не производитель)
                if hm and any(v in eff[:hm.end()] for v in PRODUCE):
                    producer = other
                    break
            if not producer:
                add('C-15', 'Major', rid,
                    f'КАНДИДАТ: триггер опирается на «{head}» — состояние, которое система вычисляет сама, '
                    f'но ни одно требование его не ставит; проверить, не потерян ли вход')
            break
    print(f'  требований с триггером: {checked}; находок: {len([f for f in FINDINGS if f["check"] == "C-15"])}')


CHECKS = [('C-01', c01), ('C-02', c02), ('C-03', c03), ('C-04', c04), ('C-05', c05),
          ('C-06', c06), ('C-07', c07), ('C-08', c08), ('C-09', c09), ('C-10', c10),
          ('C-11', c11), ('C-12', c12), ('C-13', c13), ('C-14', c14), ('C-15', c15)]

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--docs', default='docs')
    ap.add_argument('--json', default='')
    ap.add_argument('--only', default='')
    a = ap.parse_args()
    idx = build(a.docs)
    only = set(a.only.split(',')) if a.only else None
    for name, fn in CHECKS:
        if only and name not in only:
            continue
        try:
            fn(idx)
        except Exception as e:
            print(f'  ПРОВЕРКА {name} УПАЛА: {type(e).__name__}: {e}')
            add(name, 'info', '-', f'проверка не отработала: {e}')
    real = [f for f in FINDINGS if f['level'] != 'info']
    print('\n=== ИТОГО')
    for lvl in ('Blocker', 'Major', 'Minor'):
        n = len([f for f in real if f['level'] == lvl])
        print(f'  {lvl}: {n}')
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(FINDINGS, ensure_ascii=False, indent=1), encoding='utf-8')
        print('  находки записаны в', a.json)
