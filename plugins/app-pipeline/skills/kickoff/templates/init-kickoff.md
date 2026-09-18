# init-kickoff — инициализация репозитория

Инструкция для агента — Claude Code, Codex или OpenCode. Запускается строкой «выполни docs/init-kickoff.md» в корне уже клонированного git-репозитория, куда пользователь скопировал `docs/` (00–07, STATUS.md, этот файл и `execute-kickoff.md`). На выходе — репозиторий, в котором любой из агентов (Claude Code, Codex, OpenCode) выполняет план командой `/execute-kickoff`:

```
<repo>/
├── AGENTS.md                 # инструкции для агентов (канонические; Codex и OpenCode читают его напрямую)
├── CLAUDE.md                 # @AGENTS.md + 2–3 строки, специфичные для Claude Code
├── README.md                 # что за проект, как запустить, ссылки на docs/ и порядок работы
├── .gitignore
├── docs/                     # как принёс пользователь; STATUS.md обновляется
├── openspec/
│   ├── config.yaml           # schema: spec-driven, context, rules (EARS, Clean Architecture, lint)
│   ├── specs/README.md       # пусто до первого archive
│   └── changes/
│       ├── 000-walking-skeleton/     proposal.md, design.md, tasks.md, specs/platform/spec.md
│       ├── 001-project-foundation/   proposal.md, design.md, tasks.md, specs/platform/spec.md
│       ├── 002-<capability>/         proposal.md, design.md, tasks.md, specs/<capability>/spec.md
│       └── 00N-…/                    proposal.md, specs/…   (design/tasks сделает execute-kickoff)
├── .claude/skills/execute-kickoff/SKILL.md      # + скилы openspec-* от `openspec init`
├── .agents/skills/execute-kickoff/SKILL.md      # Codex ($execute-kickoff)
└── .opencode/skills/execute-kickoff/SKILL.md    # OpenCode, + .opencode/commands/execute-kickoff.md
```

## Как задавать вопросы

С готовыми вариантами ответа: 2–4 варианта, рекомендуемый — первым с пометкой «(Recommended)»; в Claude Code — через `AskUserQuestion`. Развилки: перезапись уже существующих файлов, продолжение при устаревшем аудите, коммит при незаданной git-identity.

## Предусловия

Проверь, прежде чем что-то писать:

1. `git rev-parse --show-toplevel` совпадает с текущим каталогом — это корень репозитория. Иначе остановись и скажи, куда перейти.
2. `docs/00-exploration.md` … `docs/07-kickoff.md`, `docs/execute-kickoff.md` и `docs/STATUS.md` на месте; в STATUS строка `kickoff` — `ready`, `audit` — READY или READY WITH CONDITIONS. Чего-то нет — остановись и назови, что сделать (запустить `/kickoff`, скопировать `docs/`).
3. `openspec --version` работает. Нет — `npm install -g @fission-ai/openspec@latest`; если сеть не позволяет — остановись: без CLI не будет ни `openspec init`, ни валидации.
4. Если `openspec/`, `AGENTS.md` или `.claude/skills/execute-kickoff/` уже есть — спроси: «Перезаписать сгенерированное (Recommended)» / «Создать только отсутствующее» / «Остановиться». `docs/` не трогается в любом случае.

## Что читать

Прицельно, по разделам: `docs/07-kickoff.md` целиком (дорожная карта, контрольные точки, условия, окружение — он короткий и написан для этого шага); TRD §3–§4 — требования и сценарии (переезжают в спеки дословно); SAD §4, §6, §7 — стек, сквозные аспекты, целевое окружение; SDD §1, §3 — модули и реестр интерфейсов; DDD §1, §2–§4 (дизайн модулей, схема БД, контракты API — для `design.md` changes `000`–`002`), §6 (команды запуска и деплоя — для AGENTS.md и README), §8, §9, §10 — структура репозитория, задачи CH-00–CH-02, DoD, соглашения; BRD §1 — два-три предложения о продукте для AGENTS.md. Остальное — по ID, когда действительно понадобилось. Ничего не придумывай: не хватает данных для файла — это открытый пункт в README «Open items», а не повод сочинить.

## Процесс

### 1. `openspec init`

```bash
openspec init --tools claude,codex,opencode --no-animation .
```

Создаёт `openspec/` (config.yaml-заглушку, `specs/`, `changes/archive/`) и скилы/команды OpenSpec для трёх агентов: `.claude/skills/openspec-*` + `.claude/commands/opsx/*`, `.agents/skills/openspec-*` (Codex), `.opencode/skills/openspec-*` + `.opencode/commands/opsx-*`. Проверь, что все три каталога появились. Список идентификаторов инструментов — `openspec init --help`, если CLI обновился и имена сменились. Расширенный профиль (`ff`, `verify`) не нужен: эти шаги делает `execute-kickoff` через CLI.

### 2. `openspec/config.yaml`

Перезапиши заглушку:

```yaml
schema: spec-driven
context: |
  <2–6 строк из SAD: что за система, стек, ключевые ограничения>
  Project documentation lives in docs/ (BRD, TRD, SAD, SDD, DDD). Requirement IDs (FR-xxx, NFR-xxx)
  come from docs/02-trd.md and must be preserved in spec requirement headings.
  Changes are executed wave by wave by the execute-kickoff skill ("Wave" in each proposal's Impact; changes of
  one wave are independent and may run in parallel git worktrees); see docs/07-kickoff.md.
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
    - 'One requirement = one SHALL and one behaviour; no "and/or" bundling; no should/may/might/could/appropriate/adequate/user-friendly/fast/easy/etc./as needed/if possible/TBD.'
    - 'Requirement headings keep the TRD ID, e.g. "### Requirement: FR-012 Password reset".'
    - 'Every requirement has at least one "#### Scenario:" with WHEN/THEN bullets that is testable.'
    - 'A delta spec that introduces a new capability starts with a "## Purpose" section (at least one full sentence).'
  design:
    - 'Follow docs/03-sad.md and docs/04-sdd.md; do not introduce new architectural decisions without an ADR.'
    - >-
      Clean Architecture is mandatory: code is split into domain (entities, business rules), application
      (use cases), adapters (controllers, presenters, gateways, repositories) and infrastructure (frameworks,
      DB, HTTP, UI, CLI). Dependencies point inward only; domain and application layers import no framework,
      driver or I/O code. Every design names the layer of each new module (see AGENTS.md "Architecture").
  tasks:
    - 'Every task references the FR/NFR it implements and ends with a verification step (test or manual check).'
    - 'A task is done only when the linter and formatter from AGENTS.md "Commands" pass on the touched code; do not silence rules to get there.'
```

Правила оставь как есть — они заставляют агента писать новые спецификации в EARS. YAML капризен: правило с двоеточием или `#` без кавычек ломает парсер, и CLI молча игнорирует весь config (`Warning: could not parse … ignoring it`). Каждое правило — в одинарных кавычках или `>-`; после записи проверь: `openspec validate --all --strict` не должен печатать предупреждение о config.

### 3. Changes

Greenfield: `openspec/specs/` описывает текущее поведение системы, а системы ещё нет, поэтому главные спецификации пусты, все требования идут в `changes/*/specs/` как `## ADDED Requirements` и переезжают в `specs/` при archive. Не клади требования в `openspec/specs/` напрямую — агент сочтёт их реализованными. `openspec/specs/README.md`: «Main specs are empty until the first change is archived; requirements live in changes/*/specs until then.»

Список, порядок, имена и состав changes — из таблицы «Дорожная карта» в `docs/07-kickoff.md` (она уже сведена с DDD §7): каталог `openspec/changes/<NNN>-<change-name>/`. Для **каждого** change:

`proposal.md`
```markdown
# <change-name>

## Why
<проблема/ценность со ссылкой на BR-xx>

## What Changes
- <capability>: FR-001, FR-002 … (ADDED)

## Capabilities
### New Capabilities
- `<capability>` — specs/<capability>/spec.md
### Modified Capabilities
- (none)

## Impact
- Affected components: C-xx, M-xx (из SAD/SDD)
- Depends on: 001-project-foundation
- Wave: 2
- Conditions from audit: <из docs/07-kickoff.md §«Открытые условия», если закрыть нужно до этого change>
```
Секция `## Capabilities` — контракт между proposal и specs в схеме spec-driven; не пропускай. Строка `- Wave: N` — число из колонки «Волна» дорожной карты, ровно в таком формате и у каждого change: по ней `execute-kickoff` определяет текущую волну и решает, выполнять change последовательно или открыть на волну параллельные worktree. «Affected components» — модули из колонки «Модули M-xx» той же таблицы: воркер волны не выходит за их пределы.

Валидатор требует у change хотя бы одну delta-спецификацию, поэтому `000-walking-skeleton` и `001-project-foundation` получают `specs/platform/spec.md`: скелет — NFR развёртываемости, каркас — остальные сквозные NFR (CI, тесты, наблюдаемость, безопасность платформы, сопровождаемость — сюда входят линтер и проверка границ слоёв, см. «Соглашения по коду» ниже). Две delta-спецификации одной capability в последовательных changes сливаются при archive — штатно. NFR, ограничивающие конкретную capability, живут в её спецификации. Так каждое FR/NFR из TRD — ровно в одном change. Change без спецификаций (рефакторинг, документация) — `.openspec.yaml` в его каталоге:
```yaml
schema: spec-driven
skip_specs: true
```

`specs/<capability>/spec.md` — по файлу на capability, которую change затрагивает; формулировки FR — из TRD §3 дословно, сценарии — из колонки «Сценарии приёмки». Для новой capability первой идёт `## Purpose` (одно-два полных предложения; источник — «Описание» в exploration §7, а если exploration пропущен — карта capabilities в BRD §6–§7), иначе archive подставит `TBD` и `--strict` станет красным.
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
```
NFR — так же (`### Requirement: NFR-003 API latency` + измеримый сценарий). Change, меняющий ранее добавленное требование, использует `## MODIFIED Requirements` с полным текстом. `--strict` проверяет `SHALL`/`MUST` и хотя бы один `#### Scenario:` (ровно четыре решётки); паттерн EARS он не проверяет — за это отвечают правила config.yaml.

`000-walking-skeleton` — минимальное работающее приложение в целевом окружении, и ничего больше; что именно «минимальное» и как проверять — из `docs/07-kickoff.md` §«Целевое окружение» и SAD §7. В комплекте: структура репозитория из DDD §1 (пустые каталоги допустимы), команда локального запуска, команда или инструкция деплоя (ручной деплой допустим — автоматизация в `001`), README «как запустить». Без БД, auth, тестовой инфраструктуры и CI — это `001`. Спецификация — NFR развёртываемости из TRD §4; если таких NFR нет — `.openspec.yaml` с `skip_specs: true` и пункт в README «Open items». Последняя задача в его `tasks.md` — проверка в целевом окружении, она же контрольная точка `execute-kickoff`.

Для **`000`, `001`, `002`** дополнительно:

`design.md` — из SAD/SDD/DDD §2–§4: структура, технологии с версиями, связи компонентов, конфигурация, тесты, ссылки на ADR. Цитируй ID и решения, не пересказывай.

`tasks.md` — из DDD §8, формат OpenSpec:
```markdown
## 1. Repository scaffold
- [ ] 1.1 Initialise <framework> project with <package manager>; commit lockfile (T-001)
## 2. Verification
- [ ] 2.1 Deployed build answers GET /health with 200 at <target URL> (NFR-005)
```
Каждая задача — меньше одной сессии агента, с проверяемым результатом; последняя группа — всегда `Verification`. В `tasks.md` change `001-project-foundation` обязательно есть группа «Code conventions»: установка и конфигурация линтера и форматтера из «Соглашений по коду», их запуск в CI и в `Verification`, а также инструмент проверки границ слоёв, если он есть для стека. Если DDD §8 таких задач не содержит — добавь их, это не выдумка, а требование пайплайна; каркас каталогов по слоям Clean Architecture закладывается уже в `000` (структура из DDD §1), линтер — в `001`. Для остальных changes `design.md`/`tasks.md` не пиши: их сделает `execute-kickoff`, когда до change дойдёт очередь, по реальному коду. В `proposal.md` таких changes — строка «Design and tasks: generated by execute-kickoff when this change becomes current; sources — docs/04-sdd.md, docs/02-trd.md».

### 4. Соглашения по коду

Два требования пайплайна обязательны для любого проекта и попадают в `AGENTS.md`, `openspec/config.yaml` и задачи `001`:

**Clean Architecture.** Четыре слоя, зависимости направлены только внутрь:

| Слой | Что в нём | Чего в нём нет |
|---|---|---|
| domain | сущности E-xx, value objects, инварианты, доменные ошибки | импортов фреймворков, драйверов БД, HTTP, UI |
| application | use cases (по одному на сценарий FR), порты (интерфейсы репозиториев и внешних сервисов) | конкретных реализаций портов, деталей транспорта |
| adapters | контроллеры/хендлеры, презентеры, реализации репозиториев и клиентов внешних систем (IF-xx) | бизнес-правил |
| infrastructure | фреймворк, точка входа, конфигурация, миграции, DI-контейнер | ничего, что нужно тестировать без окружения |

Привязку слоёв к каталогам возьми из DDD §1; если DDD §1 не разложен по слоям — разложи сам, сохранив имена модулей M-xx, и запиши это в README «Open items» как отклонение от документа. Тесты domain и application запускаются без БД, сети и фреймворка.

**Линтер и форматтер** — из SAD §4 / DDD §10. Если документы их не называют, возьми умолчание для языка и запиши выбор в AGENTS.md (это техническое решение, не факт о бизнесе):

| Язык | Линтер + форматтер | Проверка границ слоёв |
|---|---|---|
| TypeScript / JavaScript | ESLint + Prettier | dependency-cruiser или eslint-plugin-boundaries |
| Python | Ruff (lint + format) + mypy | import-linter |
| Go | golangci-lint + gofmt | go-arch-lint |
| Rust | clippy + rustfmt | — (модульная видимость) |
| Java / Kotlin | Checkstyle + Spotless / ktlint + detekt | ArchUnit |
| C# | Roslyn analyzers + dotnet format | NetArchTest |
| PHP | PHP_CodeSniffer + PHPStan | deptrac |
| Dart / Flutter | dart analyze + flutter_lints + dart format | — (правила в analysis_options) |
| Swift | SwiftLint + swift-format | — |

Конфигурация линтера — в репозитории (не только в IDE), команда — в `AGENTS.md` «Commands», запуск — в CI (`001`) и в группе `Verification` каждого change. Правила не отключаются точечно (`eslint-disable`, `noqa`, `nolint`) без строки-обоснования в `design.md` текущего change.

### 5. `AGENTS.md`, `CLAUDE.md`, `README.md`, `.gitignore`

`AGENTS.md` — по-английски, до ~120 строк, единый файл для всех трёх агентов (Codex и OpenCode читают его сами):

```markdown
# <Project name>

## What this is
<2–3 предложения из BRD §1>. Documentation: docs/ (01-brd … 05-ddd, 07-kickoff). Specs and changes: openspec/.

## Stack
<из SAD §4: язык/версии, фреймворки, БД, инфраструктура>

## Commands
install / dev / test / lint / build / migrate / deploy — реальные команды из DDD §6, §10 и SAD §7

## Workflow
- The plan is executed by the execute-kickoff skill: `/execute-kickoff` (Claude Code, OpenCode) or `$execute-kickoff` (Codex). One run = one change. It detects the current change and state from openspec/; run it again for the next change.
- Changes live in openspec/changes/ and run wave by wave (`- Wave: N` in each proposal.md): 000 (walking skeleton — done only when the app responds in the target environment) → 001 → wave 2 → … A wave with one change runs on the current branch. For a wave with several changes, the run in the primary checkout opens a worktree and a `change/<name>` branch per change, the runs inside those worktrees do the work, and the next run in the primary checkout merges and archives what is verified.
- On a `change/<name>` branch touch only that change and the modules in its proposal's Impact; never run `openspec archive` there.
- Unplanned scope → a new change via the openspec-propose skill; never implement without a change. Requirements are EARS (rules in openspec/config.yaml); keep FR/NFR IDs in headings.
- Human checkpoints and open conditions: docs/07-kickoff.md.

## Architecture
Clean Architecture; dependencies point inward only.
| Layer | Directory | Contains | Must not import |
|---|---|---|---|
| domain | <из DDD §1> | entities, value objects, invariants | anything outside domain |
| application | <из DDD §1> | use cases, ports (interfaces) | adapters, infrastructure, frameworks |
| adapters | <из DDD §1> | controllers, presenters, repository and gateway implementations | infrastructure entry points |
| infrastructure | <из DDD §1> | framework wiring, entry point, config, migrations, DI | — |
Domain and application tests run without a database, network or framework. Boundary check: <инструмент из «Соглашений по коду» или «none — reviewed manually»>.

## Conventions
- Linter: <name, config file>; formatter: <name>. Both run in CI and in every change's Verification. Do not disable a rule inline without a justification line in the current change's design.md.
<из DDD §10: каталоги, именование, стиль, коммиты, ветки>

## Definition of Done
<из DDD §9>; lint and format pass on the whole repository.

## Do not
- Do not change architecture decisions (docs/03-sad.md ADRs) without adding a new ADR.
- Do not import framework, database or HTTP code into the domain or application layer.
- Do not edit openspec/specs/ by hand; specs change only through changes and archive.
- Do not edit docs/ except appending an ADR.
```

`CLAUDE.md` — три строки: `@AGENTS.md`, затем «Skills: /execute-kickoff (plan execution), /opsx:* (OpenSpec workflow).» — всё остальное в AGENTS.md, дубль не нужен.

`README.md` — по-русски, коротко: что за проект (BRD §1), как запустить локально (DDD §6), где документация, порядок работы (`/execute-kickoff`), раздел «Open items» — пункты, для которых в документах не хватило данных.

`.gitignore` — под стек из SAD §4 (зависимости, сборка, `.env`, IDE). Каталоги `.claude/`, `.agents/`, `.opencode/` и `openspec/` — **в репозитории**: это скилы и план проекта.

### 6. Скил `execute-kickoff`

Шаблон — `docs/execute-kickoff.md`. Он проектно-независим — всё состояние берёт из `openspec/`, `AGENTS.md` и `docs/07-kickoff.md`, поэтому копируй его **как есть**, не читая в контекст и не адаптируя (файл в `docs/` остаётся — источник для повторной инициализации):

```bash
for d in .claude/skills .agents/skills .opencode/skills; do
  mkdir -p "$d/execute-kickoff" && cp docs/execute-kickoff.md "$d/execute-kickoff/SKILL.md"
done
```

Для OpenCode дополнительно `.opencode/commands/execute-kickoff.md`, чтобы работал `/execute-kickoff`:
```markdown
---
description: "Execute the next step of the project plan (one OpenSpec change per run)"
---
Load and follow the skill `execute-kickoff` (.opencode/skills/execute-kickoff/SKILL.md). Arguments: $ARGUMENTS
```

В Claude Code скил из `.claude/skills/` вызывается как `/execute-kickoff` сам по себе, отдельная команда не нужна. В Codex — `$execute-kickoff` из `.agents/skills/`.

### 7. Проверка

Обязательна — дальше репозиторий уйдёт агенту без тебя:

- `openspec validate --all --strict` — зелёный, без предупреждения о config.yaml.
- Каждое FR/NFR из TRD с приоритетом Must/Should встречается ровно в одном `changes/*/specs/` (grep по ID); пропуски и дубли исправить, а не отметить.
- Все capabilities из дорожной карты имеют каталог в `changes/*/specs/`; `000` не зависит ни от чего, `001` — только от `000`, цикла нет.
- `grep -H "^- Wave:" openspec/changes/*/proposal.md` даёт ровно одну строку на change, числа совпадают с колонкой «Волна» дорожной карты; у `000` — 0, у `001` — 1.
- В `changes/*/specs/` нет русского текста.
- `AGENTS.md` содержит разделы «Architecture» (четыре слоя с каталогами) и «Conventions» с названием линтера и командой; `001-project-foundation/tasks.md` содержит группу «Code conventions»; `openspec/config.yaml` — правила Clean Architecture и линтера в `rules.design` / `rules.tasks`.
- `.claude/skills/execute-kickoff/SKILL.md`, `.agents/skills/execute-kickoff/SKILL.md`, `.opencode/skills/execute-kickoff/SKILL.md` — три одинаковых файла (`diff`).
- `openspec list --json` показывает все changes, `openspec status --change 003-… --json` для дальнего change показывает недостающие design/tasks, а не ошибку.

### 8. Коммит и завершение

1. `docs/STATUS.md`: строка `init-kickoff` — `done`, дата.
2. `git add -A && git commit -m "chore: initialise repository from kickoff plan"`. Если git ругается на identity — спроси: «Задать user.name/user.email для этого репозитория» / «Закоммичу сам». Не пушь.
3. В чате — итог в 10 строк: сколько changes и требований разложено, что показала валидация, какие Open items в README, есть ли в плане параллельные волны (по §2а `docs/07-kickoff.md`), и одна фраза: «Запусти `/execute-kickoff` — он начнёт с `000-walking-skeleton`». Не пересказывай план.

## Чего не делать

- Не класть требования в `openspec/specs/` для greenfield-проекта.
- Не генерировать design/tasks дальше `002` — их сделает `execute-kickoff` по актуальному коду.
- Не раздувать `000-walking-skeleton` до каркаса: без БД, auth, CI, тестов и линтера — но с каталогами по слоям Clean Architecture из DDD §1.
- Не пропускать соглашения по коду «потому что проект маленький»: Clean Architecture и линтер обязательны для любого стека.
- Не переводить EARS-формулировки на русский и не переформулировать их — они утверждены в TRD.
- Не адаптировать шаблон `execute-kickoff` под проект — всё проектное живёт в AGENTS.md и docs/07-kickoff.md.
- Не начинать реализацию (код приложения) и не запускать `execute-kickoff` самому.
- Не редактировать `docs/00`–`07` — только STATUS.md.
- Не задавать вопросы без готовых вариантов ответа.
