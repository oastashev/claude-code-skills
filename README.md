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
OpenSpec-ready Claude Code project:

| Skill | Command | Purpose |
|---|---|---|
| explore | `/explore` | Brainstorm and scope the idea → `docs/00-exploration.md` |
| assemble | `/assemble` | Build BRD/TRD/SAD/SDD/DDD documents one by one, with approval gates |
| audit | `/audit` | Check documentation completeness, traceability and EARS compliance |
| kickoff | `/kickoff` | Generate `openspec/`, `CLAUDE.md`, `KICKOFF.md` and package the project |

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
