---
name: execute-kickoff
description: "Executes the project's implementation plan (docs/07-kickoff.md) one OpenSpec change per run: detects the current phase from openspec/ state, formalises the change (design/tasks) if needed, implements its tasks, verifies, archives and commits, then stops. Run it again for the next change. Changes of one wave can run in parallel: the run in the primary checkout opens a git worktree per change and later merges and archives them, runs inside the worktrees do the work. Triggers: /execute-kickoff, $execute-kickoff, 'continue the kickoff plan', 'next change'."
---

# execute-kickoff

You are executing a pre-planned greenfield project. The plan is fixed: `docs/07-kickoff.md` (roadmap, human checkpoints, open conditions), `openspec/changes/<NNN>-<name>/` (one directory per change, executed wave by wave — see §1), `docs/02-trd.md` … `docs/05-ddd.md` (requirements and design; read by section and ID, never whole). Project rules for you: `AGENTS.md`.

**One run = one change**, from wherever it stopped last time up to `openspec archive` and a commit, or up to a human checkpoint. Never start the next change in the same run. The only run that touches several changes is the wave coordinator (§7), and it implements nothing. Never ask which change to work on — the state of `openspec/` answers that.

Detect the phase every time, even if the conversation seems to say where you are. Whatever the user typed after the command is a hint, not a state.

## 1. Detect the phase

Run, in this order, and derive the state from the results — not from memory:

```bash
openspec list --json                 # root must not be null; active changes
ls openspec/changes/archive/         # archived changes (done)
git status --short                   # uncommitted work from an interrupted run
git rev-parse --abbrev-ref HEAD      # change/<name> → this checkout is a wave worker
grep -H "^- Wave:" openspec/changes/*/proposal.md    # wave of every active change
```

- No active changes left → the plan is complete. Report and stop.
- **Wave** of a change = the number in the `- Wave: N` line of its `proposal.md`. No such line anywhere → every change is its own wave, in numeric order. **Current wave** = the lowest wave that still has an active change. Sanity-check that every prefix from `000` up to the highest one exists either as an active change or in `archive/`; a hole means the plan was edited by hand — stop and report.
- **Mode**, from the evidence above:

| Mode | Evidence | Current change |
|---|---|---|
| `worker` | HEAD is `change/<name>` | `<name>`, nothing else. If it is already archived or not in the current wave, stop and report |
| `sequential` | any other branch, and the current wave has exactly one active change | that change, on the branch you are on — exactly as if waves did not exist |
| `coordinator` | any other branch, and the current wave has two or more active changes | none → §7 |

- In `worker` and `sequential` mode, then `openspec status --change "<name>" --json` and `openspec instructions apply --change "<name>" --json`. Together with `tasks.md` checkboxes, that gives one of:

Check the rows in this order; the first match wins (a `CHECKPOINT` note takes precedence over unchecked tasks — a checkpoint can be raised mid-implementation):

| State | Evidence | Go to |
|---|---|---|
| `needs-artifacts` | `status` shows `design` or `tasks` missing (change has only proposal + specs) | §2 |
| `checkpoint` | tasks.md ends with a `> CHECKPOINT: …` note written by a previous run, regardless of how many tasks are checked | §5 (resolution), then §3 or §4 |
| `verified` | `worker` mode only: tasks.md ends with a `> VERIFIED: …` note written by a previous run | §6, worker part — sync with the integration branch |
| `implementing` | tasks.md has unchecked items, no `CHECKPOINT` note | §3 |
| `verifying` | all tasks checked, change not archived, no `CHECKPOINT` or `VERIFIED` note | §4 |
| `archiving` | verification of §4 passed in this run (including a checkpoint confirmed by the user) | §6 |

Announce it in one line: `Change 002-user-registration — state: implementing (4/9 tasks done)`.

If `git status` shows uncommitted changes, they belong to the previous interrupted run of this same change: read `git diff --stat`, keep them, continue. Do not reset, stash or discard anything.

## 2. Formalise the change (design.md, tasks.md)

Only the first three changes ship with design/tasks; every later change gets them now, against the code that actually exists.

1. `openspec instructions design --change "<name>" --json` → follow its template and the `rules.design` from `openspec/config.yaml`. Sources, in this order: `proposal.md` and `specs/*/spec.md` of this change; `docs/04-sdd.md` §1 (module decomposition), §2–§4 and §6 for the modules (M-xx) named in the proposal's Impact; `docs/03-sad.md` §4 and §6 (stack, cross-cutting); the current code (`ls`, existing modules, config). Cite IDs and decisions; do not restate the documents. No new architectural decisions — if one is unavoidable, stop (§5) and propose an ADR.
2. `openspec instructions tasks --change "<name>" --json` → tasks in OpenSpec format (`## N. Group` / `- [ ] N.M task (FR-xxx)`), each smaller than one session, each ending in a verification (test or manual check), each referencing the FR/NFR it implements. Last group is always `Verification`: full test suite, lint, and the scenario checks from the change's specs.
3. `openspec validate "<name>" --strict` — fix until green. Commit: `chore(<name>): add design and tasks`.

Continue to §3 in the same run.

## 3. Implement

In a fresh worktree (`worker` mode, dependencies not installed yet) first run the install command from `AGENTS.md` «Commands» and copy the git-ignored environment files the project needs (`.env` and the like, named in `AGENTS.md` or `docs/07-kickoff.md` § «Окружение») from the primary checkout — its path is the first line of `git worktree list`.

Read every file in `contextFiles` from the apply instructions (proposal, specs, design, tasks) and `AGENTS.md`. Then loop over unchecked tasks in order:

- Implement the task; keep the change minimal and inside the task's scope.
- Run the tests/lint relevant to what you touched (commands in `AGENTS.md`).
- Mark `- [ ]` → `- [x]` only when the specified behaviour is fully implemented — not partially, not deferred.
- After each completed task group (`## N.`), commit: `feat(<name>): <group title>` (or the format from `AGENTS.md` Conventions).

Stop and go to §5 when: a task is ambiguous; implementing reveals a design issue or requires an architectural decision; the work needs a secret, credential, external account or manual deployment you do not have; the scope exceeds the spec and you would have to narrow or silently extend it; a test fails and two attempts did not fix it. Do not guess, do not skip the task, do not mark it done.

## 4. Verify

All tasks checked. Before archiving:

1. Full test suite and lint from `AGENTS.md` Commands — must be green.
2. For every `### Requirement:` in this change's `specs/*/spec.md`, name the test or manual check that covers each `#### Scenario:`. A scenario with no check → write the test now (it belongs to this change) or, if it can only be checked manually, do the check and record the result in `tasks.md` under `## Verification`.
3. `openspec validate "<name>" --strict`.
4. Human checkpoints from `docs/07-kickoff.md` § «Контрольные точки» that apply to this change — for `000-walking-skeleton` that is always «the app responds in the target environment». If you can perform the check yourself (deploy command and access are available, the public URL answers), do it and record the evidence (URL, status code, timestamp) in `tasks.md`. Otherwise → §5.

## 5. Checkpoint — stop and hand over

Append to `tasks.md`:

```
> CHECKPOINT (<YYYY-MM-DD>): <what a human must do or decide, in one or two sentences; what evidence to bring back>
```

Commit (`wip(<name>): checkpoint — <reason>`), then report and **end the run**. The report states: change, state, what was done this run, exactly what the user must do (commands, URL to check, value to provide, decision to take), and «when done, run `/execute-kickoff` again» (`$execute-kickoff` in Codex).

On the next run, the state is `checkpoint`: read the note, ask the user to confirm it is resolved (in Claude Code — `AskUserQuestion` with options «Done, continue» / «Not yet»), take what they provide (evidence, value, decision), remove the `> CHECKPOINT` note, and continue: unchecked tasks remain → §3 from the task that was blocked; all tasks checked → §4 step 4. «Not yet» → end the run without changing anything.

## 6. Archive and commit

**`worker` mode never archives** — concurrent archives on different branches would conflict in `openspec/specs/`. Instead:

- §4 passed in this run → append `> VERIFIED (<YYYY-MM-DD>): tests, lint and scenario checks green on change/<name>` to `tasks.md`, commit `chore(<name>): verified, ready to merge`, report «run `/execute-kickoff` in the primary checkout (`<path>`) to merge and archive», end the run.
- State `verified` → find the integration branch (the branch checked out in the primary checkout: first line of `git worktree list`). If it is an ancestor of HEAD (`git merge-base --is-ancestor <integration> HEAD`), there is nothing to do — report «waiting for the coordinator» and end. Otherwise `git merge <integration>`. Clean merge → full test suite and lint; green → the note stays, report and end. Conflicts, or red after the merge → resolve with the knowledge of this change (keep the other changes' additions intact), remove the `> VERIFIED` note, commit, redo §4 and hand over again.

`sequential` mode and the coordinator (§7, after a merge) archive on the integration branch:

```bash
openspec archive "<name>" --yes      # merges the change's delta specs into openspec/specs/
openspec validate --all --strict     # must stay green after the merge
```

If archive refuses (validation error, unchecked task) — fix the cause, do not use `--no-validate`. If the change had `.openspec.yaml` with `skip_specs: true`, pass `--skip-specs`.

Commit: `chore(<name>): archive change`. Do not push unless `AGENTS.md` Conventions say so.

Report in ≤ 15 lines: change archived; requirements now in `openspec/specs/`; tests status; next change name and its state (`needs-artifacts` or `implementing`); any open condition from `docs/07-kickoff.md` § «Открытые условия» due before the next change — and «run `/execute-kickoff` again».

## 7. Wave coordinator

The current wave has several active changes and you are in the primary checkout. You open worktrees, merge what is finished and report; you never formalise, implement or verify a change here. Every step is idempotent — the user runs this as often as they like.

1. **Preconditions.** `git status --short` must be empty; otherwise stop and report — do not stash or discard. The branch you are on is the integration branch.
2. **Status.** For each active change of the wave: does branch `change/<name>` exist (`git branch --list "change/*"`), where is its worktree (`git worktree list`), and what does its `tasks.md` say — read it from the branch without checking it out: `git show "change/<name>:openspec/changes/<name>/tasks.md"` (file missing → `needs-artifacts`; otherwise checked/total, `CHECKPOINT` or `VERIFIED`).
3. **Open.** For each change of the wave without a branch: `git worktree add "../$(basename "$PWD")-wt/<name>" -b "change/<name>"`. The branch is the claim: if the command fails because the branch exists, another run got there first — skip.
4. **Merge and archive** each `VERIFIED` change, in numeric order, one at a time:
   - `git merge --no-ff "change/<name>" -m "merge(<name>): wave <N>"`. Conflicts you may resolve yourself: only in the files listed under «файлы с очередью» in `docs/07-kickoff.md` § «Волны выполнения» and in lockfiles (regenerate with the install command) — keep the additions of both sides. A conflict anywhere else means the changes were not independent: `git merge --abort`, leave the change to its worker (its next run syncs with the integration branch and re-verifies, §6) and go on to the next one.
   - Full test suite and lint from `AGENTS.md`. Red → fix the integration (`fix(<name>): integrate with wave <N>`), two attempts at most; still red → `git reset --hard ORIG_HEAD` back to the commit before the merge (safe: the tree was clean and the merge is not pushed), report, go on to the next change.
   - Remove the `> VERIFIED` note, archive and commit as in §6, then `git worktree remove "<path>"` and `git branch -d "change/<name>"`.
5. **Report and end the run**: a table of the wave (change, state, worktree path); for every change not yet merged — «open an agent in `<path>` and run `/execute-kickoff` there» (`$execute-kickoff` in Codex); «run `/execute-kickoff` here again to merge finished changes». When the last change of the wave is archived, name the next wave and whether it is sequential or parallel.

One agent is enough to run a parallel wave: run `/execute-kickoff` in each worktree in turn — same result, only slower.

## Rules

- One change per run. The next change is never touched, even to «prepare» it.
- In a worktree, touch only your own change: its `openspec/changes/<name>/` directory, the modules named in its proposal's Impact, and additive edits to the shared «файлы с очередью». Never run `openspec archive`, never edit another change, never merge into the integration branch from a worker.
- Requirements live in `openspec/changes/*/specs/` until archive; never edit `openspec/specs/` by hand, never write requirements in any language other than the EARS English used in the TRD.
- `docs/` is the source of truth and read-only for you. The one exception: appending an ADR to `docs/03-sad.md` when the user approves an architectural change. `docs/STATUS.md` is not yours to update.
- Deviations from the plan go through the change's artifacts (`/opsx:update`-style edit of proposal/design/tasks with a note why), not through silent code changes.
- Do not install tools, create accounts or deploy to environments beyond what `AGENTS.md` and the change's tasks name; that is a checkpoint.
- Do not read `docs/00`–`05` whole. Read the section the task points to.
- Respect the Clean Architecture layering from `AGENTS.md` «Architecture»: new code goes into the layer its module belongs to, domain and application never import framework, database or I/O code. A design that needs to break this is an architectural decision → §5 and an ADR.
- Lint and format from `AGENTS.md` «Commands» must pass before a task is marked done. Never silence a rule inline to get green; if a rule is genuinely wrong for this code, note the justification in the change's `design.md`.
