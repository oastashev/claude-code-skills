# Контракт плана

Python 3.10+, стандартная библиотека. ROOT — корень проекта, SKILL — фактический каталог kickoff; аргументы экранируй для текущего shell.

```text
python SKILL/scripts/planctl.py lock --root ROOT --files inputs.json --out docs/kickoff/baseline.json
python SKILL/scripts/planctl.py check --root ROOT --plan docs/kickoff/plan.json
python SKILL/scripts/planctl.py check --root ROOT --plan docs/kickoff/plan.json --execution
python SKILL/scripts/planctl.py parallel --root ROOT --plan docs/kickoff/plan.json --workers 1 2 4
```

inputs.json — массив относительных путей всех входов из SKILL.md. lock создаёт новый baseline: {schema: 1, files: {path: sha256}}, не переписывает существующий. Не сокращай список ради сокрытия изменений. Сам baseline не включает plan/review/approval и производный Markdown.

check печатает mechanical, semantic, readiness, approval, plan_hash, baseline_hash, errors. Код 0 — READY (и совпадающее утверждение при --execution); 1 — FAIL/UNKNOWN/неутверждённый execution; 2 — ошибочный ввод. Без review результат UNKNOWN. Скрипт не доказывает правильность суждений ревьюера или полноту переданного списка источников.

## plan.json

Команда parallel читает только кандидат плана и строит анализ раскладки: baseline/review/approval она не проверяет и не изменяет. Код 0 означает успешный расчёт, включая PARTIAL; 1 — противоречие заявленной независимости графу/общим writes; 2 — некорректный ввод. Перед запуском реализации обязателен check --execution. check также выводит parallelism и блокирует выбранную совместную волну без подтверждённых independent-пар.

Корень:
- schema: 2; id: стабильный ID плана; revision: ID ревизии specify. Snapshot ревизии — schema 2 на стадии DESIGN; check требует в baseline документы всех её стадий (01-requirements.md, 02-architecture.md при профиле extended, 03-design.md).
- baseline: путь baseline.json; snapshot: путь snapshot.json; audit_gates: путь gates.json; audit_manifest: путь manifest.json того же завершённого аудита. Manifest содержит specification.store/revision и входной инвентарь. Скрипт сверяет binding, хеши входов и наличие нормативных источников. Соответствие gates/report/manifest одному scope и подлинность выводов проверяются критерием baseline.
- exploration: фактический относительный путь 00-exploration.md (по умолчанию рядом с хранилищем); exploration_source: ID соответствующего active source (по умолчанию SRC-EXPLORATION). Оригинал и source snapshot должны совпадать по SHA256. При импорте новой редакции выбери новый ID, не переписывай старый source.
- scope: {goal, phase, basis: [ID]} — полезный результат, фаза, основания.
- requirements: объект по ID **всех active obligation** snapshot.
- changes: массив срезов; conditions: массив условий.
- execution: {mode: sequential|parallel, max_workers: целое > 0}.
- parallelism: {pairs: [...], estimates?: {...}} — основания анализа, независимо от выбранного execution. Для новых планов заполняй всегда; отсутствие у прежнего плана означает unknown для пар без зависимости/явного конфликта, а не разрешение параллелизма.
- review: путь review.json; approval: путь approval.json.

Requirement: {disposition: include|deferred|excluded, reason, basis: [ID], owners: [change-id], applies_to: [change-id], scenarios: [scenario-id], coverage: [...]}.
include требует owners, applies_to, scenarios; owners входят в applies_to.
deferred/excluded имеют пустые owners/applies_to/scenarios/coverage: исходные сценарии остаются в snapshot, но не назначены выполнению.

Coverage row: {change, scenario, scope: local|integration, requires: [change-id]}. Пара change/scenario уникальна. requires включает change и только его прямые/транзитивные зависимости, не будущие или независимые срезы. Сценарий входит в scenarios требования и назначенного change, где для него есть checks. Объединение coverage покрывает все scenarios требования; каждый applies_to имеет хотя бы одну применимую проверку. Смысл и достаточность локальных/интеграционных проверок подтверждаются review.

Например, export-service проверяет S-local с requires=[export-service]; зависящий от него UI проверяет S-end-to-end с requires=[export-service, ui]. Ранний срез не проверяет будущий UI. Полная гарантия требования считается подтверждённой лишь после всех назначенных проверок, а не после первого owner.

Для старого плана без coverage скрипт сохраняет прежнее значение «все сценарии у каждого носителя». Раздельное распределение требует явной coverage и нового review/approval. Старый план без audit_manifest не допускается к execution: создай новый baseline через полный audit и новую редакцию плана; прежние evidence и approvals не редактируй задним числом.
Фаза исходного obligation не меняется; её соответствие scope проверяется по смыслу. Non-goals и критерии успеха отражай в scope.goal либо дополнительных полях scope.

Change:
- id: стабильное безопасное имя каталога, например order-create.
- outcome, rationale: наблюдаемый результат и необходимость для MVP.
- basis: [ID]; contracts: [ID contract]; modules: [ID module] — модули DESIGN, которые срез создаёт или меняет. План schema 1 с полем tasks (ссылки на задачи DDD) не принимается: составь новую редакцию по текущей спецификации.
- requirements: [ID obligation] — все применимые, не только принадлежащие срезу.
- scenarios: [ID scenario].
- depends_on: [change-id]; wave: целое >= 0.
- writes: [относительные пути или glob] — предполагаемые области записи.
- independence: обоснование независимости соседей; для одиночного среза — объяснение последовательности.
- checks: [{scenario: ID, method, expected}] — будущая проверка, не выполненный тест.

Parallel pair: {a: change-id, b: change-id, status: independent|conflict|unknown, reason, evidence: [точные ссылки]}. Неупорядоченная пара уникальна. Прямые/транзитивные зависимости скрипт выводит сам как dependent; явно оценивать нужно несвязанные пары. Автоматические выводы скрипта не являются доказательством семантической независимости.

Estimates (необязательно): {unit: единица, basis: основания оценок, values: {change-id: положительное число}}. Все changes должны иметь оценки в общей единице; неполный набор не дополняется defaults. Без estimates выводятся волны и длина зависимостей по количеству changes, timing=UNKNOWN. Условный процент сокращения — результат модели, не обещание ускорения.

Condition:
{id, description, owner, timing: before_start|before_verify|before_release,
changes: [change-id], status: open|closed, evidence: [ссылки]}.
closed требует evidence. Открытое before_start допускается в READY-плане, но блокирует соответствующий change. Вопросы, мешающие определить сам план, дают FAIL/UNKNOWN в review.

## Review и утверждение

review: {schema: 1, plan_hash, baseline_hash, criteria: {...}}.
Ключи criteria: baseline, scope, atomicity, completeness, consistency, verifiability, feasibility, contracts, traceability, assumptions.
Каждый: {status: PASS|FAIL|UNKNOWN, reason, evidence: [точные ссылки]}.
Хеши — SHA256 **байтов** plan.json и baseline.json; check выводит их и при UNKNOWN.
Проверяй полный кандидат; прежний PASS автоматически не переносится.

approval: {schema: 1, plan_hash, baseline_hash, decision, approved_at}.
decision — реальная цитата/ссылка ответа пользователя. Скрипт проверяет привязку, а не достоверность согласия.

07-kickoff.md: ID/хеш плана, цель MVP, включённое/отложенное/non-goals, срезы и зависимости, трассировка, условия, проверка конечного результата и инструкции переноса/старта. Источник структуры — JSON; Markdown не редактируется независимо.

## Ограничения помощника

Помощник проверяет совпадение строк writes, но не вычисляет пересечение glob и не доказывает независимость API/ресурсов. Полнота baseline и подлинность утверждений specify/audit проверяются критерием baseline; присутствие и хеш файла не доказывают его смысл.

Состав, смысл и timing условий меняются только пересмотром плана. Закрытие условий, создание changes и состояние выполнения не входят в контракт kickoff и не записываются в утверждённый plan.
