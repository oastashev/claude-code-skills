# claude-code-skills

Claude Code plugin marketplace.

## Using this marketplace

Add it in Claude Code:

```
/plugin marketplace add oastashev/claude-code-skills
```

(or, from a local clone: `/plugin marketplace add ./claude-code-skills`)

Then install a plugin from it:

```
/plugin install app-pipeline@claude-code-skills
```

## Plugins

### app-pipeline

Four-step pipeline for going from a high-level app idea to an audited,
OpenSpec-ready repository that an agent executes change by change:

| Skill | Command | Purpose |
|---|---|---|
| explore | `/explore` | Brainstorm and scope the idea → `docs/00-exploration.md` |
| assemble | `/assemble` | Build BRD/TRD/SAD/SDD/DDD documents one by one, with approval gates |
| audit | `/audit` | Check documentation completeness, traceability and EARS compliance |
| kickoff | `/kickoff` | Write the launch plan `docs/07-kickoff.md` (deployment order, change roadmap starting with a walking skeleton, parallelism analysis — execution waves, critical path and estimated time saving, human checkpoints, audit conditions) and copy two agent-neutral instruction files into `docs/` |

The two instruction files are templates from [skills/kickoff/templates/](plugins/app-pipeline/skills/kickoff/templates/) and travel with `docs/` into the new repository, so any agent can run them:

| File | How to run | Purpose |
|---|---|---|
| `docs/init-kickoff.md` | "execute docs/init-kickoff.md" in the cloned repo | Create `openspec/` (config + changes), `AGENTS.md`/`CLAUDE.md`/`README.md` with the mandatory code conventions (Clean Architecture layering, linter and formatter for the project's language), run `openspec init` for Claude Code, Codex and OpenCode, install the `execute-kickoff` skill from `docs/execute-kickoff.md`, commit |
| `docs/execute-kickoff.md` | installed as a project skill by init-kickoff | Execute the plan one change per run; changes of one wave run in parallel git worktrees |

The installed project-local skill `execute-kickoff` (`/execute-kickoff` in Claude Code and OpenCode, `$execute-kickoff` in Codex) then executes the plan one change per run: it detects the current change and its state from `openspec/`, formalises design/tasks when missing, implements, verifies, archives and commits, stopping at human checkpoints (the walking skeleton must answer in the target environment before anything else is built). When the plan puts several independent changes into one wave, the run in the primary checkout opens a git worktree and a `change/<name>` branch per change, an agent in each worktree implements and verifies its change, and the next run in the primary checkout merges the verified branches one by one, runs the full test suite, archives and removes the worktrees.

See [plugins/app-pipeline/skills/](plugins/app-pipeline/skills/) for each skill's full instructions.

## Repository layout

```
.claude-plugin/marketplace.json   # marketplace manifest (this repo)
plugins/
  app-pipeline/
    .claude-plugin/plugin.json    # plugin manifest
    skills/                       # auto-discovered Claude Code skills
```

## Adding a new plugin

1. Create `plugins/<plugin-name>/.claude-plugin/plugin.json`.
2. Add skills/commands/agents under `plugins/<plugin-name>/` (`skills/`, `commands/`, `agents/` are auto-discovered).
3. Register it in `.claude-plugin/marketplace.json`'s `plugins` array with `"source": "<plugin-name>"`.
