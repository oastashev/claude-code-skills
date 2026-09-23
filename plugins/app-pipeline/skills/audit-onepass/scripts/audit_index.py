"""Индекс комплекта документации /assemble.

Читает docs/*.md и собирает факты, на которых работают проверки audit_checks.py:
таблицы, требования, носители, символы (поля, ключи, значения словарей),
объявления типов, вызовы, числовые утверждения и перекрёстные ссылки.

Ничего не правит. Запуск: python3 audit_index.py [--docs docs] [--json out.json]
"""
import json, re, sys, pathlib, argparse

ID_RE = re.compile(r'\b(BR|US|FR|NFR|CAP|ADR|IF|CH|C|M|E|T|A|R|Q)-(\d{2,3})(?![\w-])')
CELL_SPLIT = re.compile(r'(?<!\\)\|')
CONFIG_ROOTS = {'apply', 'archive', 'review', 'limits', 'notify', 'git', 'bin', 'agents', 'factory'}
RANGE_RE = re.compile(r'(FR|NFR|M|C|T|CH|BR)-(\d{2,3})…(?:FR|NFR|M|C|T|CH|BR)-(\d{2,3})')
BACKTICK = re.compile(r'`([^`\n]{1,80})`')
EARS_PATTERNS = [
    ('WHILE-WHEN', re.compile(r'^WHILE .*?, WHEN ')),
    ('WHERE-WHEN', re.compile(r'^WHERE .*?, WHEN ')),
    ('WHERE-IF', re.compile(r'^WHERE .*?, IF .*?, THEN ')),
    ('event', re.compile(r'^WHEN ')),
    ('state', re.compile(r'^WHILE ')),
    ('unwanted', re.compile(r'^IF .*?, THEN ')),
    ('optional', re.compile(r'^WHERE ')),
    ('ubiquitous', re.compile(r'^[A-Z][\w .`]* SHALL ')),
]
MARKER_WORDS = ['should', 'may', 'might', 'could', 'appropriate', 'adequate',
                'user-friendly', 'fast', 'easy', 'etc.', 'and/or', 'as needed',
                'if possible', 'TBD', 'optionally', 'if necessary']
NUM_WORDS = {'один': 1, 'одна': 1, 'два': 2, 'две': 2, 'три': 3, 'четыре': 4, 'пять': 5,
             'шесть': 6, 'семь': 7, 'восемь': 8, 'девять': 9, 'десять': 10,
             'одиннадцать': 11, 'двенадцать': 12, 'тринадцать': 13, 'четырнадцать': 14,
             'пятнадцать': 15, 'шестнадцать': 16, 'семнадцать': 17, 'восемнадцать': 18,
             'девятнадцать': 19, 'двадцать': 20, 'тридцать': 30, 'сорок': 40}
UNIT_NOUNS = r'(требовани\w+|колон\w+|ключ\w+|событи\w+|пол\w+|значени\w+|задач\w+|change\w*|фикстур\w+|артефакт\w+|строк\w+|шаблон\w+|факт\w+|лок\w+)'


def cells(line):
    parts = [c.strip() for c in CELL_SPLIT.split(line)]
    if parts and parts[0] == '':
        parts = parts[1:]
    if parts and parts[-1] == '':
        parts = parts[:-1]
    return parts


def expand_ids(text, kinds=('FR', 'NFR')):
    """Разворачивает диапазоны и собирает одиночные ID указанных видов."""
    out = []
    for m in RANGE_RE.finditer(text):
        if m.group(1) in kinds:
            out += [f'{m.group(1)}-{i:03d}' for i in range(int(m.group(2)), int(m.group(3)) + 1)]
    for m in re.finditer(r'(?<![…\w])(' + '|'.join(kinds) + r')-(\d{2,3})(?!…)(?![\w-])', text):
        out.append(f'{m.group(1)}-{m.group(2)}')
    return out


SPEC_DOCS = re.compile(r'^(00-|01-|02-|03-|04-|05-|STATUS)')


def read_docs(docs_dir, spec_only=True):
    """Спецификация — это 00…05 и STATUS. Отчёт аудита и входные материалы
    (дизайн, findings) в индекс не попадают: они цитируют старые редакции
    и давали бы ложные находки."""
    docs = {}
    for p in sorted(pathlib.Path(docs_dir).glob('*.md')):
        if spec_only and not SPEC_DOCS.match(p.name):
            continue
        docs[p.name] = p.read_text(encoding='utf-8')
    return docs


def parse_tables(text, doc):
    """Возвращает таблицы: {doc, line, header:[...], rows:[{col:val}], raw:[строки]}."""
    tables, lines = [], text.split('\n')
    i = 0
    while i < len(lines):
        if lines[i].startswith('|') and i + 1 < len(lines) and re.match(r'^\|[\s:|-]+\|?\s*$', lines[i + 1]):
            header = cells(lines[i])
            rows, raw, j = [], [], i + 2
            while j < len(lines) and lines[j].startswith('|'):
                c = cells(lines[j])
                rows.append({header[k] if k < len(header) else f'col{k}': v for k, v in enumerate(c)})
                raw.append(lines[j]); j += 1
            tables.append({'doc': doc, 'line': i + 1, 'header': header, 'rows': rows, 'raw': raw})
            i = j
        else:
            i += 1
    return tables


def parse_requirements(tables):
    reqs = {}
    for t in tables:
        if not t['header'] or t['header'][0] != 'ID':
            continue
        if not any('EARS' in h for h in t['header']):
            continue
        ears_col = next(h for h in t['header'] if 'EARS' in h)
        for r in t['rows']:
            rid = r.get('ID', '').strip()
            if not re.fullmatch(r'(FR|NFR)-\d{3}', rid):
                continue
            reqs[rid] = {
                'id': rid, 'doc': t['doc'],
                'ears': r.get(ears_col, ''),
                'note': r.get('Пояснение', ''),
                'priority': r.get('Приоритет', '').strip(),
                'source': r.get('Источник', ''),
                'scenarios': r.get('Сценарии приёмки', ''),
            }
    return reqs


def parse_carriers(tables, kind_prefixes):
    """{ID носителя: множество требований} по колонкам «Реализует…» / «FR…»."""
    carriers = {}
    for t in tables:
        if not t['header'] or t['header'][0] != 'ID':
            continue
        col = None
        for h in t['header']:
            if h.startswith('Реализует') or h in ('FR', 'FR/NFR'):
                col = h
        if col is None:
            continue
        for r in t['rows']:
            rid = r.get('ID', '').strip()
            if not any(rid.startswith(p + '-') for p in kind_prefixes):
                continue
            carriers.setdefault(rid, set()).update(expand_ids(r.get(col, '')))
    return carriers


def parse_ts_blocks(text):
    return re.findall(r'```ts\n(.*?)```', text, re.S)


def parse_interfaces(ts_src):
    """{ИмяТипа: [поля]} из interface/type в блоках ts (включая закомментированные)."""
    out = {}
    src = re.sub(r'^\s*//\s?', '', ts_src, flags=re.M)
    for m in re.finditer(r'(?:export\s+)?interface\s+(\w+)(?:\s+extends\s+[\w, ]+)?\s*\{(.*?)\n?\}', src, re.S):
        body = m.group(2)
        fields = re.findall(r'(?:^|[;{\n])\s*(\w+)\s*[?]?\s*:', body)
        out.setdefault(m.group(1), set()).update(fields)
    for m in re.finditer(r'(?:export\s+)?type\s+(\w+)\s*=\s*([^;]+);', src, re.S):
        out.setdefault('type ' + m.group(1), set()).update(re.findall(r"'([^']+)'", m.group(2)))
    return {k: sorted(v) for k, v in out.items()}


def parse_functions(ts_src):
    """{имя: {'params': [...], 'arity': n}} из объявлений функций в блоках ts."""
    out = {}
    src = re.sub(r'^\s*//\s?', '', ts_src, flags=re.M)
    for m in re.finditer(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)', src):
        params = [p.strip() for p in m.group(2).split(',') if p.strip()]
        out[m.group(1)] = {'params': params, 'arity': len(params)}
    for m in re.finditer(r'^\s*(\w+)\s*\(([^)]*)\)\s*:\s*\w', src, re.M):
        if m.group(1) in ('if', 'for', 'while', 'switch', 'return'):
            continue
        params = [p.strip() for p in m.group(2).split(',') if p.strip()]
        out.setdefault(m.group(1), {'params': params, 'arity': len(params)})
    return out


def parse_calls(text):
    """Вызовы вида name(...) и obj.name(...) вне блоков ts — в прозе алгоритмов."""
    prose = re.sub(r'```.*?```', '', text, flags=re.S)
    calls = []
    for m in re.finditer(r'`?\b(?:(\w+)\.)?(\w+)\(([^`)]*)\)', prose):
        obj, name, args = m.group(1), m.group(2), m.group(3)
        if name in ('if', 'for', 'while', 'см', 'и', 'или'):
            continue
        depth, cur, argv = 0, '', []
        for ch in args:
            if ch in '([{':
                depth += 1
            elif ch in ')]}':
                depth -= 1
            if ch == ',' and depth == 0:
                argv.append(cur.strip()); cur = ''
            else:
                cur += ch
        if cur.strip():
            argv.append(cur.strip())
        calls.append({'obj': obj, 'name': name, 'args': argv, 'arity': len(argv),
                      'text': m.group(0)[:120]})
    return calls


def parse_symbols(text):
    """Символы в обратных кавычках с грубой классификацией."""
    syms = {}
    for m in BACKTICK.finditer(text):
        s = m.group(1).strip()
        if not s or ' ' in s and not s.startswith('`'):
            kind = None
        if re.fullmatch(r'[a-z][a-z0-9_]*(\.[a-z][a-z0-9_*]*)+', s) and \
                s.split('.')[0] in CONFIG_ROOTS:
            kind = 'config-key'
        elif re.fullmatch(r'[a-z][a-z0-9_]*', s):
            kind = 'field'
        elif re.fullmatch(r'[a-z][a-z0-9_]*: ?[a-z][a-z0-9 _-]*', s):
            kind = 'value'
        elif re.fullmatch(r'[A-Z][A-Za-z0-9]+', s):
            kind = 'type'
        else:
            continue
        syms.setdefault(s, {'kind': kind, 'count': 0})
        syms[s]['count'] += 1
    return syms


def parse_vocabularies(text):
    """Закрытые словари вида: `failed` (тринадцать значений): `a`, `b`, …"""
    vocab = {}
    for m in re.finditer(r'`(\w+)`\s*\(([^)]*значени[^)]*)\):\s*([^\n]+)', text):
        name, decl, tail = m.group(1), m.group(2), m.group(3)
        values = re.findall(r'`([^`]+)`', tail)
        declared = None
        for w, n in NUM_WORDS.items():
            if w in decl:
                declared = n
        vocab[name] = {'values': values, 'declared': declared, 'actual': len(values)}
    return vocab


def parse_claims(text, doc):
    """Числовые утверждения в прозе: «девятнадцать требований», «18 колонок»."""
    out = []
    prose = re.sub(r'```.*?```', '', text, flags=re.S)
    for m in re.finditer(r'(\d{1,4}|' + '|'.join(NUM_WORDS) + r')\s+' + UNIT_NOUNS, prose, re.I):
        raw = m.group(1).lower()
        n = int(raw) if raw.isdigit() else NUM_WORDS.get(raw)
        if n is None:
            continue
        ctx = prose[max(0, m.start() - 90):m.end() + 60].replace('\n', ' ')
        out.append({'doc': doc, 'n': n, 'unit': m.group(2).lower(), 'context': ctx})
    return out


def parse_refs(text, doc):
    """Ссылки вида «проверка FR-411 „только openspec/“» — ID рядом с цитатой."""
    out = []
    for m in re.finditer(r'((?:FR|NFR)-\d{3})[^.;|\n]{0,40}[«„"]([^»“"\n]{4,80})[»“"]', text):
        out.append({'doc': doc, 'id': m.group(1), 'quote': m.group(2),
                    'context': text[max(0, m.start() - 80):m.end() + 20].replace('\n', ' ')})
    for m in re.finditer(r'[«„"]([^»“"\n]{4,80})[»“"][^.;|\n]{0,20}\(((?:FR|NFR)-\d{3})\)', text):
        out.append({'doc': doc, 'id': m.group(2), 'quote': m.group(1),
                    'context': text[max(0, m.start() - 80):m.end() + 20].replace('\n', ' ')})
    return out


def build(docs_dir='docs', spec_only=True):
    docs = read_docs(docs_dir, spec_only)
    idx = {'docs': {}, 'text': {}, 'docs_dir': str(docs_dir), 'tables': [], 'reqs': {}, 'carriers': {}, 'interfaces': {},
           'functions': {}, 'calls': [], 'symbols': {}, 'vocab': {}, 'claims': [],
           'refs': [], 'headers': {}}
    for name, text in docs.items():
        idx['docs'][name] = {'lines': len(text.split('\n')), 'bytes': len(text.encode())}
        idx['text'][name] = text
        tables = parse_tables(text, name)
        idx['tables'] += tables
        m = re.search(r'^Версия: ([\d.]+)[^\n]*', text, re.M)
        based = re.findall(r'docs/([\w-]+\.md) v([\d.]+)', text[:1200])
        journal = re.findall(r'^\| ([\d.]+) \| 20\d\d-\d\d-\d\d', text, re.M)
        idx['headers'][name] = {'version': m.group(1) if m else None,
                                'based_on': based, 'journal': journal}
        for k, v in parse_symbols(text).items():
            idx['symbols'].setdefault(k, {'kind': v['kind'], 'docs': {}})
            idx['symbols'][k]['docs'][name] = v['count']
        idx['vocab'].update(parse_vocabularies(text))
        idx['claims'] += parse_claims(text, name)
        idx['refs'] += parse_refs(text, name)
        for block in parse_ts_blocks(text):
            for t, f in parse_interfaces(block).items():
                idx['interfaces'].setdefault(t, set()).update(f)
            for fn, sig in parse_functions(block).items():
                idx['functions'].setdefault(fn, sig)
        for c in parse_calls(text):
            c['doc'] = name
            idx['calls'].append(c)
    idx['interfaces'] = {k: sorted(v) for k, v in idx['interfaces'].items()}
    idx['reqs'] = parse_requirements(idx['tables'])
    idx['carriers'] = {k: sorted(v) for k, v in
                       parse_carriers(idx['tables'], ('C', 'M', 'IF', 'E', 'CH', 'T')).items()}
    return idx


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--docs', default='docs')
    ap.add_argument('--json', default='')
    a = ap.parse_args()
    index = build(a.docs)
    print(f"документов {len(index['docs'])}, таблиц {len(index['tables'])}, "
          f"требований {len(index['reqs'])}, носителей {len(index['carriers'])}, "
          f"типов {len(index['interfaces'])}, функций {len(index['functions'])}, "
          f"вызовов {len(index['calls'])}, символов {len(index['symbols'])}, "
          f"словарей {len(index['vocab'])}, числовых утверждений {len(index['claims'])}, "
          f"ссылок с цитатой {len(index['refs'])}")
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding='utf-8')
        print('индекс записан в', a.json)
