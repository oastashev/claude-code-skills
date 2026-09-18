---
name: kickoff
description: "Шаг 4 пайплайна разработки приложений: по прошедшей /audit документации генерирует openspec/ (config.yaml с правилами EARS, changes с proposal и delta-спецификациями), CLAUDE.md, инструкцию KICKOFF.md и zip стартового пакета для Claude Code. Триггеры: /kickoff, «подготовь проект к разработке», «собери стартовый пакет», «упакуй проект для Claude Code»."
---

# /kickoff — запуск разработки

Последний шаг пайплайна. На входе — утверждённые `docs/00`–`05` и отчёт `/audit` с вердиктом READY или READY WITH CONDITIONS. На выходе — проект, который можно распаковать, открыть в Claude Code и сразу выполнить первый change через `/opsx:apply`:

```
<project-slug>/
├── CLAUDE.md                 # инструкции для Claude Code: стек, команды, правила, OpenSpec + EARS
├── KICKOFF.md                # подробная инструкция по запуску разработки (по-русски)
├── README.md                 # короткое описание проекта и ссылки на docs/
├── .gitignore
├── docs/                     # документы пайплайна как есть (00–06), STATUS.md, 07-kickoff.md — строка-указатель на KICKOFF.md
└── openspec/
    ├── config.yaml           # schema: spec-driven, context, rules (EARS)
    ├── specs/README.md       # пусто до первого archive — объяснение почему
    └── changes/
        ├── 001-project-foundation/   proposal.md, design.md, tasks.md, specs/platform/spec.md (сквозные NFR)
        ├── 002-<capability>/         proposal.md, design.md, tasks.md, specs/<capability>/spec.md
        └── 00N-…/                    proposal.md, specs/…  (design/tasks достраиваются в Claude Code перед началом change)
```

Плюс `<project-slug>-kickoff-<YYYY-MM-DD>.zip` с тем же содержимым.

## Как задавать вопросы

Любой вопрос пользователю — только через `AskUserQuestion`, с готовыми вариантами ответа: 2–4 конкретных варианта, рекомендуемый — первым с пометкой «(Recommended)». Вопрос обычным текстом в ответе — нарушение: пользователь ждёт кликабельные варианты. Развилки этого скила: выбор папки, «продолжать без актуального аудита или запустить /audit», перезапись существующих файлов в папке проекта.

## Где живут файлы

Как у остальных шагов: подключённая папка проекта → `AskUserQuestion` «Подключу папку сейчас (Recommended)» / «Работать в документах Project» → документы claude.ai Project + `SendUserFile`. Сгенерированные файлы кладутся в корень папки проекта (это и есть будущий репозиторий), zip — рядом. Если папки нет, zip отдаётся через `SendUserFile`, и это единственный способ доставить его — тогда в KICKOFF.md первым пунктом идёт «распаковать zip в пустую папку».

## Предусловия

1. `docs/STATUS.md`: exploration, BRD, TRD, SAD, SDD, DDD — `approved`; строка `audit` — READY или READY WITH CONDITIONS. Сверь «Проверенные версии» из шапки `docs/06-audit-report.md` с версиями в шапках документов: если какой-то документ новее, чем проверял аудит, аудит устарел.
2. Если аудит NOT READY, не проводился или устарел — остановись и спроси через `AskUserQuestion`: «Сначала запустить /audit (Recommended)» / «Продолжить kickoff без актуального аудита». Если пользователь выбирает продолжить — продолжай, но вынеси в KICKOFF.md раздел «Запуск без прохождения аудита» со списком известных рисков; молча пропускать проверку нельзя, потому что дальше эти пробелы превратятся в неверные спецификации.
3. Условия из READY WITH CONDITIONS перенеси в KICKOFF.md и в proposal того change, до которого их нужно закрыть.

## Процесс

### 1. Прочитать всё

Читай прицельно, а не весь `docs/`: TRD §3–§4 — требования и сценарии приёмки (переезжают в спеки дословно), SAD §4 и §6 — стек и сквозные аспекты для `config.yaml` и CLAUDE.md, SDD §1 и §3 — модули и реестр интерфейсов, DDD §1 и §7–§10 — структура репозитория, список changes, задачи CH-01/CH-02, DoD и соглашения, отчёт аудита §1 и §4 — вердикт и условия. Exploration и BRD целиком не нужны: из них в пакет попадают только «Why» в proposal (BR-xx) и два-три предложения в CLAUDE.md — прочитай BRD §1, §5, §6. Остальное дочитывай по ID, когда действительно понадобилось. Ничего нового не придумывай: если чего-то не хватает для файла, это находка аудита, а не повод для творчества — запиши в KICKOFF.md как открытый пункт.

### 2. `openspec/config.yaml`

```yaml
schema: spec-driven
context: |
  <2–6 строк из SAD: что за система, стек, ключевые ограничения>
  Project documentation lives in docs/ (BRD, TRD, SAD, SDD, DDD). Requirement IDs (FR-xxx, NFR-xxx)
  come from docs/02-trd.md and must be preserved in spec requirement headings.
rules:
  proposal:
    - 'Reference the change ID (CH-xx) and the FR/NFR IDs from docs/02-trd.md it covers.'
    - 'Keep "Why" grounded in docs/01-brd.md business requirements (BR-xx).'
  specs:
    - >-
      Every requirement statement MUST follow exactly one EARS pattern and use SHALL:
      "The <system> SHALL <response>" / "WHEN <trigger>, the <system> SHALL <response>" /
      "WHILE <state>, the <system> SHALL <response>" / "IF <condition>, THEN the <system> SHALL <response>" /
      "WHERE <feature>, the <system> SHALL <response>" / combinations such as
      "WHILE <state>, WHEN <trigger>, the <system> SHALL <response>".
    - 'One requirement = one SHALL and one behaviour; no "and/or" bundling; no should/may/appropriate/user-friendly/etc.'
    - 'Requirement headings keep the TRD ID, e.g. "### Requirement: FR-012 Password reset".'
    - 'Every requirement has at least one "#### Scenario:" with WHEN/THEN bullets that is testable.'
    - 'A delta spec that introduces a new capability starts with a "## Purpose" section (at least one full sentence).'
  design:
    - 'Follow docs/03-sad.md and docs/04-sdd.md; do not introduce new architectural decisions without an ADR.'
  tasks:
    - 'Every task references the FR/NFR it implements and ends with a verification step (test or manual check).'
```

Подставь реальный контекст; правила оставь — именно они заставят `/opsx:propose` в Claude Code писать новые спецификации в EARS, а не только те, что сгенерируешь ты. YAML здесь капризен: строка правила с двоеточием или с `#` внутри без кавычек ломает парсер, и CLI молча игнорирует весь config (`Warning: could not parse … ignoring it`) — правила пропадают. Поэтому каждое правило — в одинарных кавычках или блок-скаляром `>-`, а после генерации проверь парсинг (`openspec validate` печатает предупреждение, если файл не читается; либо `python3 -c "import yaml,sys; yaml.safe_load(open('openspec/config.yaml'))"`).

### 3. Changes

Greenfield-проект: в OpenSpec `openspec/specs/` описывает текущее поведение системы, а системы ещё нет, поэтому главные спецификации остаются пустыми, а все требования идут в `changes/*/specs/` как `## ADDED Requirements` и переезжают в `specs/` при `/opsx:archive`. Не клади требования в `openspec/specs/` напрямую — тогда Claude Code будет считать их уже реализованными.

Список changes и порядок — из DDD §7 (`CH-xx`). Каталог: `openspec/changes/<NNN>-<change-name>/`, нумерация по порядку выполнения (`001-project-foundation`, `002-user-registration`; числовой префикс OpenSpec не мешает). Для **каждого** change:

`proposal.md`
```markdown
# <change-name>

## Why
<проблема/ценность со ссылкой на BR-xx>

## What Changes
- <capability>: FR-001, FR-002 … (ADDED)
- …

## Capabilities
### New Capabilities
- `<capability>` — specs/<capability>/spec.md
### Modified Capabilities
- (none)

## Impact
- Affected components: C-xx, M-xx (из SAD/SDD)
- Depends on: 001-project-foundation
- Conditions from audit: <если есть>
```
Секция `## Capabilities` — контракт между proposal и specs в схеме spec-driven: по ней `/opsx:propose` и `/opsx:ff` понимают, какие спецификации ожидаются. Не пропускай её.

Валидатор OpenSpec требует, чтобы у change была хотя бы одна delta-спецификация. Поэтому первый change `001-project-foundation` получает спецификацию capability `platform` (`specs/platform/spec.md`), куда попадают сквозные NFR — CI, тесты, производительность, наблюдаемость, безопасность платформы — то, что не относится к одной функциональной capability. NFR, ограничивающие конкретную capability (например, время ответа поиска), кладутся в спецификацию этой capability. Так каждое FR/NFR из TRD живёт ровно в одном change. Если всё же нужен change без спецификаций (чистый рефакторинг, документация) — положи в его каталог `.openspec.yaml`:
```yaml
schema: spec-driven
skip_specs: true
```

`specs/<capability>/spec.md` — по одному файлу на capability, которую change затрагивает; формулировки FR берутся из TRD дословно, сценарии — из колонки «Сценарии приёмки». Для новой capability первой идёт секция `## Purpose` (одно-два полных предложения; источник — колонка «Описание» из exploration §7): при `/opsx:archive` она копируется в основную спецификацию, а без неё archive подставит заглушку `TBD`, и `openspec validate --strict` станет красным.
```markdown
## Purpose
Account lifecycle for end users: sign-up, e-mail verification and sign-in for the <system>.

## ADDED Requirements

### Requirement: FR-001 Account creation
WHEN a visitor submits the sign-up form with a valid e-mail and password, the system SHALL create an account and send a verification e-mail.

#### Scenario: Successful sign-up
- **WHEN** a visitor submits a valid e-mail and a password of at least 12 characters
- **THEN** an account is created with status `unverified`
- **AND** a verification e-mail is sent within 30 seconds

#### Scenario: Duplicate e-mail
- **WHEN** the e-mail already belongs to an account
- **THEN** the system returns error `EMAIL_TAKEN` and no e-mail is sent
```
NFR оформляются так же (`### Requirement: NFR-003 API latency` + сценарий с измеримой проверкой). Каждый change, который меняет уже добавленное ранее требование, использует `## MODIFIED Requirements` с полным текстом требования, а не диффом. Валидатор в `--strict` проверяет наличие `SHALL`/`MUST` в тексте требования и хотя бы одного `#### Scenario:` (ровно четыре решётки); паттерн EARS и WHEN/THEN он не проверяет — за это отвечают правила в config.yaml и `/audit`.

Для **первого change** (каркас) и **второго** дополнительно создай:

`design.md` — из SAD/SDD/DDD: структура репозитория, выбранные технологии с версиями, как компоненты связаны, решения по конфигурации и тестам, ссылки на ADR. Не пересказывай документы — цитируй ID и решения.

`tasks.md` — из DDD §8, формат OpenSpec:
```markdown
## 1. Repository scaffold
- [ ] 1.1 Initialise <framework> project with <package manager>; commit lockfile (T-001)
- [ ] 1.2 Add linter/formatter config and `make lint`/`npm run lint` (T-002)
## 2. Database
- [ ] 2.1 …
## 3. Verification
- [ ] 3.1 CI runs lint + tests on push; green on empty project
```
Каждая задача — меньше одной сессии Claude Code, с проверяемым результатом. Для остальных changes `design.md` и `tasks.md` не пиши: их достроит Claude Code в момент, когда до change дойдёт очередь, с учётом реально написанного кода (`/opsx:propose <change>` для существующего change создаёт недостающие артефакты; в расширенном профиле то же делает `/opsx:ff <change>`). Такой change с одними proposal + specs валидируется зелёно, а `openspec status` показывает `[ ] design`, `[-] tasks`. В `proposal.md` таких changes добавь строку «Design and tasks: generate when the previous change is archived; source — docs/04-sdd.md and docs/02-trd.md (docs/05-ddd.md details only CH-01 and CH-02)».

`openspec/specs/README.md`: «Main specs are empty until the first change is archived; requirements live in changes/*/specs until then.»

### 4. `CLAUDE.md`

Файл, который Claude Code читает в каждой сессии. Коротко (до ~120 строк), только то, что нужно для работы:

```markdown
# <Project name>

## What this is
<2–3 предложения из BRD>. Full documentation: docs/ (01-brd … 05-ddd). Specs and change workflow: openspec/.

## Stack
<из SAD: язык/версии, фреймворки, БД, инфраструктура>

## Commands
install / dev / test / lint / build / migrate — реальные команды из DDD §6, §10

## Workflow (OpenSpec)
- Work is organised in openspec/changes/. Order: 001 → 002 → … (see KICKOFF.md roadmap).
- For each change: /opsx:propose <change> (fills in missing design/tasks; /opsx:ff if the expanded profile is enabled) → /opsx:apply <change> → run the full test suite → /opsx:verify if available, otherwise re-check tasks.md against specs → /opsx:archive. Do not start the next change before archiving the current one.
- New scope → /opsx:propose <name>, never implement without a change.
- Requirements are written in EARS (see openspec/config.yaml rules). Keep FR/NFR IDs in headings.

## Conventions
<из DDD §10: структура каталогов, именование, стиль, коммиты, ветки>

## Definition of Done
<из DDD §9>

## Do not
- Do not change architecture decisions (docs/03-sad.md ADRs) without adding a new ADR.
- Do not edit requirements in openspec/specs/ by hand; specs change only through changes and archive (editing a spec's Purpose text is fine).
```

CLAUDE.md — по-английски: он адресован Claude Code, а не читателю документации.

### 5. `KICKOFF.md` — инструкция по запуску

По-русски, для человека, который открывает проект впервые. Пиши плотно: таблицы вместо прозы, не пересказывай содержимое `docs/` — ссылайся на файл и раздел. Ориентир — до ~150 строк. Разделы:

1. **Что в пакете** — дерево с назначением каждого элемента.
2. **Предварительные требования** — Node.js LTS, git, Claude Code (`npm install -g @anthropic-ai/claude-code`), OpenSpec (`npm install -g @fission-ai/openspec@latest`), плюс стек проекта (из SAD: runtime, БД, Docker и т. п.) с командами проверки версий.
3. **Первый запуск, шаг за шагом** — распаковать; `git init` и первый коммит; `openspec init --tools claude` в корне (создаёт `.claude/commands/opsx/*.md` и `.claude/skills/openspec-*/` — команды `/opsx:explore, propose, apply, update, sync, archive`; существующие `openspec/config.yaml`, `changes/` и `CLAUDE.md` не трогает — проверить `openspec list --changes` после); `openspec validate --all --strict` — должен быть зелёным; запустить `claude` в корне. Отдельным необязательным пунктом — расширенный набор команд (`/opsx:ff`, `/opsx:verify`, `/opsx:onboard`, `new`, `continue`): он включается интерактивно командой `openspec config profile` (выбрать custom и нужные workflows — это настройка машины, не проекта, в zip её не положить), затем `openspec update`.
4. **Цикл разработки одного change** — `/opsx:apply 001-project-foundation` → тесты → `/opsx:archive`; для следующих: `/opsx:propose <change>` (достроит design/tasks для существующего change; в расширенном профиле — `/opsx:ff <change>`) → проверить design/tasks против DDD → `/opsx:apply` → тесты → `/opsx:verify` (если включён) → `/opsx:archive`. Что делать при отклонении от документов (`/opsx:update`, новый ADR).
5. **Дорожная карта changes** — таблица: №, change, capabilities, FR/NFR, зависимости, оценка, условия аудита.
6. **Правила** — EARS для любых новых требований (шаблоны), DoD, ветки/коммиты, что нельзя менять без ADR.
7. **Окружение** — переменные окружения (имена и назначение, без секретов), сервисы, как поднять локально.
8. **Открытые условия и риски** — из аудита и DDD, с указанием, до какого change закрыть.
9. **Чек-лист первого дня** — 10–15 пунктов с чекбоксами.

### 6. Проверка

Верификация обязательна — пакет уйдёт в работу без тебя:

- Каждое FR/NFR из TRD с приоритетом Must/Should встречается ровно в одном change (`grep` по ID по `changes/*/specs/`); список пропущенных и дублированных — исправить, а не отметить.
- `openspec/config.yaml` парсится (см. §2) — иначе правила EARS не действуют.
- Все capabilities из DDD §7 имеют каталог в `changes/*/specs/`.
- Зависимости changes не образуют цикла, `001` не зависит ни от чего.
- Если сеть позволяет — установи CLI в рабочем пространстве (`npm install -g @fission-ai/openspec@latest` или `npx -y @fission-ai/openspec@latest`) и запусти `openspec validate --all --strict` в корне пакета; ошибки исправь. Если CLI недоступен — скажи об этом в KICKOFF.md и в чате, чтобы пользователь запустил валидацию сам на шаге 3.
- В `changes/*/specs/` нет русского текста: требования и сценарии скопированы из TRD как есть.
- Перечитай CLAUDE.md глазами Claude Code: есть ли команды тестов и порядок changes.

### 7. Упаковка и доставка

1. Собери дерево в рабочем пространстве, `zip -r <project-slug>-kickoff-<YYYY-MM-DD>.zip <project-slug>/` (без `node_modules`, `.git`, временных файлов).
2. `SendUserFile` для zip.
3. Если папка проекта подключена — запиши в неё и файлы по отдельности (`CLAUDE.md`, `KICKOFF.md`, `README.md`, `.gitignore`, `openspec/`), и zip. Существующие файлы с теми же именами не перезаписывай молча: `AskUserQuestion` — «Перезаписать» / «Сохранить рядом с суффиксом» / «Пропустить».
4. В `docs/07-kickoff.md` положи одну строку-указатель: `Инструкция по запуску — в KICKOFF.md в корне проекта.` Копировать инструкцию целиком не нужно: повторный `/audit` читает `docs/` и оплатил бы дубль ещё раз. Обнови `docs/STATUS.md` (строка `kickoff`: статус `packaged`, дата, имя zip).
5. Если папка не подключена и файлы ушли только в zip — дополнительно положи `KICKOFF.md`, `CLAUDE.md` и `openspec/config.yaml` в документы claude.ai Project (`project_write` под теми же путями), чтобы повторный `/audit` мог их прочитать.
6. В чате — короткий итог: сколько changes, сколько требований разложено, что валидация показала, первый шаг для пользователя. Не пересказывай KICKOFF.md.

## Чего не делать

- Не класть требования в `openspec/specs/` для greenfield-проекта.
- Не генерировать design/tasks для всех changes сразу: дальние changes устареют к моменту выполнения, а `/opsx:ff` сделает их по актуальному коду.
- Не переводить EARS-формулировки на русский и не переформулировать их «покрасивее» — они утверждены в TRD.
- Не копировать KICKOFF.md в `docs/07-kickoff.md` целиком — там строка-указатель.
- Не начинать реализацию (код приложения) — это работа Claude Code по `/opsx:apply`.
- Не делать `git init`/коммиты в папке пользователя — это описано в KICKOFF.md как его первый шаг.
- Не задавать вопросы обычным текстом — только `AskUserQuestion` с вариантами.
