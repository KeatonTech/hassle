# Hassle — rules for all Claude sessions

The milestone build-out is complete; sessions now do maintenance: bug fixes,
features, refactors, docs. Work one scoped change at a time, to a test
contract you write first.

## Read order (do this before writing any code)

1. [CONTRIBUTING.md](CONTRIBUTING.md) — the binding engineering rules and the
   verification gates.
2. [DESIGN.md](DESIGN.md) — the design doc. The invariants (§2) and the
   plan-semantics table (§8.2) are binding.
3. The README of the package you're changing (`packages/*/README.md`) — each
   states what is in and out of its scope.

Context on why things are the way they are: `docs/internals/` (per-area design
notes), `docs/ha-api-notes.md` (empirical HA API findings, §-numbered and
cited from code), and `docs/history/` (the original milestone plan and its
legend).

## Binding rules (summary — CONTRIBUTING.md governs)

- **Tests first.** Commit failing tests before implementation.
- **No network in unit tests.** Fixtures and FakeBackend only;
  `tests/integration/` is the only exception.
- **Golden files** change only via `hassle-dev goldens --update` /
  `hassle-dev docs --update`, and the PR must show the diff.
- **Every bug found becomes a regression test before it is fixed.**
- **Compatibility contracts** (docs/ir-format.md, docs/backend.md,
  docs/dsl-extensions.md) are additive-only; update the contract doc in the
  same PR as any change to its interface.
- **Error messages are product surface**: what / where (file:line) / fix, one
  paragraph, snapshot-tested (`hassle_dev.snapshots`).
- **Determinism**: no wall-clock, no randomness in core logic; compiler/
  decompiler output must be byte-stable.
- Tooling: Python 3.12, `uv`, `ruff`, `pyright --strict` on hassle-core,
  `pytest`.
- **One distribution = one top-level import package**: internals are
  subpackages (`hassle.ir`, `hassle.compiler`), never a sibling or facade
  package (`tests/test_package_layering.py` pins the dependency direction).

## Hard invariants (never violate — from DESIGN.md §2)

- Every HA write goes through the APIs the UI uses; never write YAML files
  directly.
- Never change an existing object's HA `id`.
- `compile(decompile(x)) == x` for ANY config (use the `raw` escape hatch,
  never drop data).
- Tests execute compiled IR, not DSL Python.
- No local or UI edit is ever silently lost — surface a conflict instead.

## Workflow

- Branch per change (e.g. `fix/<short-topic>`, `feat/<short-topic>`). Never
  commit directly to `main`.
- Before declaring done: your new tests green, ALL previously green tests
  still green, `ruff` and `pyright` clean. Run them; do not assume.
- Use the `reviewer` subagent on your diff before proposing a merge.
- If DESIGN.md and reality disagree (an HA API behaves differently, a design
  detail is impossible), do NOT silently work around it: record the finding in
  `docs/ha-api-notes.md` and flag it to the human in your summary.

## Project subagents (in .claude/agents/)

- `implementer` (Sonnet) — scoped implementation work.
- `reviewer` (Opus) — verifies a diff against its test contract and the design
  invariants; read/run only.
- `fixture-wrangler` (Haiku) — fixture corpus, boilerplate, mechanical edits.
