# Контракт roadmap

Python 3.10+, стандартная библиотека. ROOT — корень репозитория приложения, SKILL — фактический каталог materialize; аргументы экранируй для текущего shell.

```text
python SKILL/scripts/materializectl.py bind --root ROOT --change openspec/changes/<id>
python SKILL/scripts/materializectl.py check --root ROOT --roadmap docs/materialize/roadmap.json
python SKILL/scripts/materializectl.py check --root ROOT --roadmap docs/materialize/roadmap.json --workers 1 2 4
```

bind печатает {files: {path: sha256}} для proposal.md и specs/*/spec.md одного change. check ничего не записывает и печатает roadmap_hash, plan_hash, mechanical, plan_consistency, semantic, readiness, next, errors, divergences, refinements, reviews, order, blocked_by_conditions, pairs, scenarios, longest_dependency_chain. Код 0 — READY; 1 — FAIL/UNKNOWN/DIVERGED; 2 — некорректный ввод.

## roadmap.json

- schema: 1; plan: docs/kickoff/plan.json; plan_hash: SHA256 байтов плана.
- adapter: docs/kickoff/adapter.json; adapter_hash; adapter.plan_hash обязан совпадать с plan_hash.
- specs: каталог текущих спецификаций OpenSpec, обычно openspec/specs.
- reviews: каталог ревью changes, обычно docs/materialize/reviews.
- changes: объект по ID **всех** срезов плана.
- edges: найденные зависимости; pairs: оценки независимости активных changes.

Change: {state: planned|active|archived, path, archive: null|путь, writes: [...], files: {path: sha256}}.
- path оканчивается ID среза. writes включает все writes плана и уточнения из репозитория.
- planned: каталога нет, archive null, files пуст.
- active: каталог существует, tasks.md есть; files — ровно proposal и spec delta (из bind), хеши актуальны. design/tasks не хешируются: их правка при реализации не меняет контракт change.
- archived: каталог перенесён в archive, files пуст; spec delta уже применены к specs. Пары с архивированными changes удаляй.
- Active и archived допустимы, только если все зависимости change архивированы. Число активных changes и execution плана не ограничивают materialize.

Edge: {change, depends_on, kind, reason, evidence: [точные ссылки]}. kind: api, data, migration, spec, code, package, config, fixture, resource, scenario, manual. Не повторяй зависимости плана. Зависимости из spec delta скрипт выводит сам (source=derived).

Pair: {a, b, status: independent|conflict|unknown, reason, evidence}. Неупорядоченная пара уникальна, только активные changes. Отсутствующая оценка — unknown.

После `/kickoff revise` roadmap старого плана STALE: создай новый по новому plan_hash, состояния — по файловой системе. Архивированный change засчитывается новому плану, только если срез с тем же ID не изменился по смыслу; иначе — divergence.

## Вывод скрипта

- next: create {change, wave, blocked_by_conditions} — первый по волне и ID planned change с архивированными зависимостями; wait {waiting_for: активные changes, pending: {change: незакрытые зависимости}, reason}; complete или blocked. Решение принимается только при READY.
- Уточнённый граф = depends_on плана + edges + derived. Цикл — FAIL.
- refinements: уточнения, согласные с порядком волн плана. Не блокируют; предложи включить их при следующем `/kickoff revise`.
- divergences: зависимость от change той же или более поздней волны (order) и не-independent пара активных changes одной утверждённой волны (wave), которую исполнитель может запустить вместе. Действие — `/kickoff revise`.
- Статус пары: dependent при зависимости; conflict при общих writes или общей capability, либо если так оценено в плане; для двух активных — оценка roadmap, для пары с ещё не созданным change — оценка плана; иначе unknown. independent в roadmap, противоречащее этому, — ошибка.
- delta: MODIFIED/REMOVED/RENAMED требования, которого нет ни в текущих specs, ни среди введённых другим активным change, и ADDED уже существующего требования — ошибки. Разбираются только заголовки требований, не смысл сценариев.
- order: все changes по утверждённым волнам и ID с состояниями. blocked_by_conditions: открытые before_start условия плана.
- scenarios: жадные барьерные волны неархивированных changes для заданного числа исполнителей; при estimates плана — сумма работ и сумма максимумов по волнам в единице плана.

## Анализ

1. Для создаваемого change сверь фактические точки касания в коде: модули, публичные API, схемы и миграции (включая нумерацию), пакеты и lockfile, конфигурацию, fixtures, генерируемый код, окружения, внешние аккаунты, ручные действия. Разные файлы не доказывают независимость; общий модуль не всегда означает конфликт.
2. Сценарий, требующий результата другого change, — зависимость, даже при разных файлах.
3. Оцени пары создаваемого change с каждым активным change по evidence из репозитория. Оценка плана — отправная точка: conflict плана скрипт сохраняет, independent нужно подтвердить заново.
4. check выдаёт варианты для 1/2/4 исполнителей (либо чисел из аргументов `/materialize parallel`). Размер найденной волны — допустимая раскладка, не доказанный максимум. Без estimates время и экономия — UNKNOWN; не подставляй условные размеры.
5. Если репозиторий допускает больше или требует меньше параллелизма, чем выбрано в плане, это рекомендация или divergence для `/kickoff revise`, а не правка волн.

## Review

Ревью пишется для каждого созданного change: `<reviews>/<id>.json` = {schema: 1, change, plan_hash, files, criteria: {...}}. files — вывод bind для этого change; правка proposal или spec delta делает ревью STALE. Ключи criteria, каждый {status: PASS|FAIL|UNKNOWN, reason, evidence: [точные ссылки]}:

| Критерий | Условие |
|---|---|
| traceability | Proposal содержит plan_hash, обязательства, сценарии, контракты, зависимости и условия среза |
| equivalence | Delta сохраняют смысл, язык, модальность, исключения и IDs источников; сквозные требования не дублируются |
| coverage | Строки coverage перенесены по scope и requires; change не проверяет будущий результат; частичная гарантия не объявлена полной |
| dependencies | Зависимости плана сохранены и архивированы; каждое edge подтверждено evidence; derived-зависимости проверены по смыслу |
| independence | Каждая independent-пара с активными changes подтверждена по коду, данным, ресурсам и окружению, а не только по путям |
| preparation | design/tasks основаны на DDD и текущем коде, задачи имеют проверяемый результат |

Отсутствующее или не PASS ревью активного change даёт blocked. Прежний PASS автоматически не переносится.

## 08-materialize.md

plan_hash, roadmap_hash; решение последнего запуска; таблица change → каталог, волна, состояние, capabilities; уточнения и расхождения с действием; существенные пары с основаниями и неизвестные пары с необходимыми данными; варианты 1/2/4 с ограничениями и рекомендация с учётом интеграции, ручных действий и накладных расходов. Источник — roadmap.json и вывод check; Markdown не редактируется независимо.
