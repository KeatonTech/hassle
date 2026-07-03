# Hassle — rules for all Claude sessions

You are one agent among several implementing this project. Your job is **one milestone
workstream at a time**, done to its test contract — not the whole project.

## Read order (do this before writing any code)

1. [MILESTONES.md](MILESTONES.md) — find YOUR assigned milestone; its "Write these tests first"
   list is your acceptance contract.
2. [DESIGN.md](DESIGN.md) — read the sections your milestone references. The invariants
   (I1–I6, §2) and the plan-semantics table (§8.2) are binding.

If you were not told which milestone you're on, ask — do not pick one yourself.

## Binding rules (from MILESTONES.md R1–R8 — summary, the originals govern)

- **Tests first.** Commit failing tests from your milestone's test list before implementation.
- **No network in unit tests.** Fixtures and FakeBackend only; `integration/`-marked tests are
  the only exception (M6+).
- **Golden files** change only via `hassle-dev goldens --update`, and the PR must show the diff.
- **Every bug found becomes a regression test before it is fixed.**
- **Frozen interfaces (F1–F3)** may not change without updating MILESTONES.md in the same PR.
- **Error messages are product surface**: what / where (file:line) / fix, one paragraph,
  snapshot-tested.
- **Determinism**: no wall-clock, no randomness in core logic; compiler/decompiler output must
  be byte-stable.
- Tooling: Python 3.12, `uv`, `ruff`, `pyright --strict` on hassle-core, `pytest`.

## Hard invariants (never violate — from DESIGN.md §2)

- I1: every HA write goes through the APIs the UI uses; never write YAML files directly.
- I2: never change an existing object's HA `id`.
- I3: `compile(decompile(x)) == x` for ANY config (use the `raw` escape hatch, never drop data).
- I5: tests execute compiled IR, not DSL Python.
- I6: no local or UI edit is ever silently lost — surface a conflict instead.

## Workflow

- Branch per work item: `m<N>/<short-topic>` (e.g. `m3/did-you-mean`). Never commit directly
  to `main`.
- Before declaring done: your milestone's new tests green, ALL previously green tests still
  green, `ruff` and `pyright` clean. Run them; do not assume.
- Use the `reviewer` subagent on your diff before proposing a merge.
- If DESIGN.md and reality disagree (an HA API behaves differently, a design detail is
  impossible), do NOT silently work around it: record the finding in `docs/ha-api-notes.md`
  and flag it to the human in your summary.

## Project subagents (in .claude/agents/)

- `implementer` (Sonnet) — milestone work items.
- `reviewer` (Opus) — verifies a diff against the milestone's test contract; read/run only.
- `fixture-wrangler` (Haiku) — fixture corpus, boilerplate, mechanical edits.
