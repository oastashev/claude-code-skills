# Артефакты и вспомогательные команды

## Рабочая папка и результаты

Рабочая папка — `PROJECT_ROOT/.blueprint/audit/<UTC-run-id>/`. Создай её перед сбором входов. UTC-run-id обозначает один запуск; при совпадении имени добавь уникальный суффикс. Пример структуры:

```text
.blueprint/audit/<UTC-run-id>/
  input.json       явный список исходных документов
  collected/       manifest.json и structural-checks.json от collect
  extracted/       текст, извлечённый из нетекстовых документов
  scratch/         черновики, индексы и промежуточные реестры
  execution/       результаты команд и контрпримеров
```

Подкаталоги создавай по необходимости. `collected/` заранее не создавай: его создаёт collect и отказывает, если он уже существует. Входной поиск должен исключать `.blueprint/**`. Не используй рабочую папку как нормативный источник. При повторной проверке старую рабочую папку сохраняй, для нового запуска создавай новую.

Завершённый отчёт и реестры размещай в `.blueprint/outputs/audit/<UTC-run-id>/` или по явному указанию пользователя. Скопируй туда manifest.json, structural-checks.json и доказательства, на которые ссылается итоговый отчёт, сохраняя исходные хеши и привязки к документам. Итоговый комплект должен быть читаем без временной папки; промежуточные материалы автоматически не удаляй.

## Явный вход

Создай UTF-8 JSON-конфигурацию `.blueprint/audit/<UTC-run-id>/input.json`. Пути документов относительно root, не относительно input.json и не абсолютные; namespace разделяет повторяющиеся ID разных продуктов. role и authority устанавливаются после чтения, а не по имени файла.

```json
{
  "documents": [
    {"path": "01-brd.md", "role": "BRD", "namespace": "product", "authority": "current"},
    {"path": "02-trd.md", "role": "TRD", "namespace": "product", "authority": "current"}
  ],
  "prefixes": ["CAP", "US", "BR", "FR", "NFR", "C", "M", "CH", "T"]
}
```

Выбери доступный `python`, `python3` или `py -3`. SKILL_DIR ниже — фактический каталог этого навыка, не обязательная переменная окружения; сформируй корректно экранированные аргументы для текущей оболочки. Не подставляй сырой текст запроса в shell.

```text
python SKILL_DIR/scripts/audit_support.py collect --root PROJECT_ROOT --config PROJECT_ROOT/.blueprint/audit/RUN_ID/input.json --out PROJECT_ROOT/.blueprint/audit/RUN_ID/collected
python SKILL_DIR/scripts/audit_support.py verify --root PROJECT_ROOT --manifest PROJECT_ROOT/.blueprint/audit/RUN_ID/collected/manifest.json
python SKILL_DIR/scripts/audit_support.py compare --previous OLD/manifest.json --current NEW/manifest.json
```

`collect` создаёт manifest.json и structural-checks.json в новом каталоге, не меняет документы. Все доступные входы хешируются. Markdown/text индексируются; JSON проверяется строгим парсером без лексической индексации; остальные форматы получают availability=available, indexing=not_supported. Это подтверждает наличие байтов, а не понимание содержимого. missing/unreadable/invalid_utf8/invalid_json означают неполноту. Для PDF/DOCX и иных форматов отдельно сохрани извлечённое содержание и привязку к оригиналу; без чтения обязательный смысловой критерий остаётся UNKNOWN. Скрипт не открывает URL и не допускает пути за root.

Для текущей спецификации specify в input.json добавь `"specification": {"store": "docs/specification", "revision": "ФАКТИЧЕСКИЙ_CURRENT"}`. collect дополнит явный documents файлами CURRENT/policy, snapshot/manifest/review/RTM/документами выбранной ревизии, текущими Markdown, source snapshots и существующими approvals этой ревизии. Фактический exploration (в том числе нестандартный путь) и дополнительные внешние доказательства укажи в documents. Manifest сохраняет specification.store/revision. CURRENT обязан совпадать, незавершённая публикация блокируется; verify также проверяет появление DOCS-PENDING. Для исторического аудита используй явный список без привязки к CURRENT и явно назови scope историческим.

Присутствие approval-файла не доказывает согласие, а хеш policy — её правильность: оцени их смысл и применимость отдельно. До передачи в kickoff проверь совпадение источников exploration, текущих Markdown и snapshot, связь политики и утверждения с ревизией. Старые manifests с unsupported_format не переписывай: собери новый запуск и покажи изменение контракта инвентаризации.

`structural-checks.json` — индекс ID, диапазонов, кандидатных определений и ссылок. Кандидат дубликата или неразрешённая ссылка требуют проверки контекста человеком/LLM: у проекта может быть другая нотация. Примеры внутри fenced code индексируются как примеры и не определяют требования. Строки сохраняются без пересчёта через форматтер. Скрипт не ставит семантические оценки и не генерирует findings автоматически.

`verify`: код 0 — входы доступны и совпадают, поддерживаемый синтаксис корректен; это не семантический PASS. Код 1 — входы/выбранный CURRENT изменились; 2 — комплект неполон или публикация не завершена. `compare` выводит added/removed/changed/unchanged и изменения метаданных; неизменный хеш не означает неизменность выводов при новом контексте.

## Полный результат аудита

Создай в итоговом каталоге `.blueprint/outputs/audit/<UTC-run-id>/` (или выбранном пользователем месте), рядом с копиями manifest.json и structural-checks.json:

1. `report.md`: scope, версии/хеши, краткий итог, десять критериев, поэтапные и сквозные gates, находки с источниками, непроверенное, приоритет исправлений и условия перепроверки.
2. `findings.json`: подтверждённые находки и явно отделённые гипотезы.
3. `criteria.csv`: document,criterion,scope,status,evidence,explanation — десять критериев на каждый проверяемый текущий документ; missing-критерии не пропускать.
4. `traceability.csv`: namespace,from_file,from_id,to_file,to_id,relation,coverage,evidence — граф связей; coverage = syntactic/semantic-confirmed/unknown/uncovered.
5. `unknowns.json`: ID, отсутствующее доказательство, затронутые проверки, влияние на gate, что требуется для снятия.
6. `gates.json`: machine-readable gates по правилам ниже.
7. При recheck — `delta.json` со статусом каждой прежней F/U-находки и причиной изменения.
8. `execution.json`, если что-либо запускалось: команда и cwd без секретов, exit_code, версии, проверяемый контракт и пути результатов. Если исполнений не было, укажи это явно в report.md.

Пример формы findings.json (значения в примере иллюстративны, не готовая находка):

```json
{
  "schema_version": 1,
  "run_id": "20260925T100000Z",
  "findings": [{
    "id": "F-001",
    "kind": "contradiction",
    "status": "confirmed",
    "severity": "High",
    "confidence": "high",
    "title": "Повтор обходит обязательную проверку лимита",
    "scope": "новый процесс при повторной попытке",
    "requirement_ids": ["BR-12", "FR-129"],
    "evidence": [{
      "file": "02-trd.md",
      "sha256": "actual-input-sha256",
      "lines": [291, 291],
      "section": "Повторы",
      "excerpt": "точная короткая выдержка из текущего источника",
      "level": "document"
    }],
    "claim": "Несовместимые обязательства и условия их одновременного действия",
    "counterexample": "Конкретные входы, путь, ожидаемые несовместимые исходы",
    "impact": "Наблюдаемое нарушение",
    "recommendation": "Минимальное согласованное изменение",
    "owner_role": "владелец требований",
    "closure_check": "Сценарий, который различает исправление и прежнее поведение",
    "limitations": "Реализация не предоставлена",
    "previous_id": null
  }]
}
```

Для contradiction обычно нужны минимум две адресуемые выдержки; обе могут быть в одном файле. Для gap покажи, где контракт определён и что именно осталось неопределённым. excerpt обязана совпадать с источником; не сохраняй условные значения из примера. Если отдельный сценарий требует процитировать секрет, замаскируй его и отметь редакцию цитаты, не записывай секрет в артефакты.

`gates.json`: schema_version, run_id, policy, gates[]. У каждого gate: id, scope, required, status, finding_ids, unknown_ids, evidence. Отдельные gates document/formal/runtime, дополнительно этапы и overall. NOT_APPLICABLE требует explanation. Статус не вычисляется по одному числу найденных ID.

`delta.json`: previous_run, current_run, input_changes, findings[]. Элемент: id, previous_status, current_status, disposition (confirmed/revised/resolved/retracted/unknown/new), reason, evidence. Новые источники и уточнение смысла показывать отдельно от исправления текста. Стабильность ID — обязанность семантического анализа, не эвристики названий.

Перед завершением проверь: citations разрешаются по manifest; ID находок уникальны; gate не ссылается на несуществующий F/U; итоговые количества совпадают с реестрами; обещанный scope покрыт; файлы вне scope не представлены как проверенные; рекомендации не нарушают явные решения пользователя.
