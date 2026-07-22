# Contributing to Hassle

Thanks for looking under the hood. Hassle manages people's real homes, so the
bar is: **no change lands that could silently lose an edit, corrupt a config,
or break round-tripping.** The rules below exist to make that cheap to uphold.

## Getting set up

```sh
uv sync                              # install the workspace (hassle-core, hassle-cli, hassle-dev)
uv run pytest -m "not integration"   # unit suite — never touches the network
uv run ruff format --check . && uv run ruff check .
uv run pyright                       # strict on hassle-core
```

Extra gates CI also runs:

```sh
uv run hassle-dev corpus-stats         # fixture-corpus contract
uv run hassle-dev goldens              # DSL <-> IR golden pairs unchanged
uv run hassle-dev docs                 # generated docs/DSL.md + docs/COOKBOOK.md in sync
```

Integration tests (`-m integration`) need a live Home Assistant
(`HASSLE_TEST_HA_URL`/`HASSLE_TEST_HA_TOKEN`); CI runs them against Docker
`stable` and `dev` images.

Each package has a README stating what is and isn't in its scope — read
[packages/hassle-core](packages/hassle-core/README.md),
[packages/hassle-cli](packages/hassle-cli/README.md), and
[packages/hassle-dev](packages/hassle-dev/README.md) before deciding where a
change belongs. Deeper module rationale lives in [docs/internals/](docs/internals/).

## Engineering rules

These were the project's global rules from day one (numbered R1–R8 in the
[historical plan](docs/history/milestones.md)); they still govern every PR.

1. **Tests first.** New behavior arrives with tests that fail without it.
   Reviewers reject code-first changes.
2. **No network in unit tests.** Anything touching HA runs against fixtures or
   `FakeBackend`; only `tests/integration/` may talk to a real instance.
3. **Golden files are regenerated, never hand-edited.** Compiler/decompiler
   correctness is expressed as golden pairs under `fixtures/`; change them only
   via `uv run hassle-dev goldens --update` (and `hassle-dev docs --update` for
   the generated docs), with the diff visible in the PR.
4. **Every bug becomes a regression test before it is fixed.**
5. **Compatibility contracts don't drift silently.** The frozen interfaces —
   the IR schema ([docs/internals/ir-format.md](docs/internals/ir-format.md)), the Backend/plan
   seam ([docs/internals/backend-protocol.md](docs/internals/backend-protocol.md)), and the top-level DSL surface
   ([docs/internals/dsl-extensions.md](docs/internals/dsl-extensions.md), i.e. `hassle.__all__`) —
   are additive-only; a change to one must update its contract doc in the same
   PR. `tests/test_package_layering.py` additionally pins the internal
   dependency direction between subpackages.
6. **Error messages are product surface.** State *what* happened, *where*
   (`file:line`), and *the fix*, in one paragraph — and snapshot-test them
   (`hassle_dev.snapshots`; regenerate with `HASSLE_UPDATE_SNAPSHOTS=1`).
7. **Tooling is non-negotiable:** Python 3.12, `uv`, `ruff` (format + lint),
   `pyright --strict` on hassle-core, `pytest`.
8. **Determinism.** No wall clock, no randomness in core logic;
   compiler/decompiler output and canonical hashing must be byte-stable across
   runs and platforms.

And the design invariants ([DESIGN.md](DESIGN.md) §2) that outrank everything
else: every HA write goes through the APIs the UI uses; never change an
existing object's HA `id`; `compile(decompile(x)) == x` for any config (use
the `raw_*` escape hatch, never drop data); tests execute compiled IR, not DSL
Python; and no local or UI edit is ever silently lost.

## Workflow

- Branch per change; don't commit directly to `main`.
- Before calling anything done: new tests green, previously green tests still
  green, `ruff` and `pyright` clean. Run them — don't assume.
- If Home Assistant behaves differently than [DESIGN.md](DESIGN.md) or
  [docs/internals/ha-api-notes.md](docs/internals/ha-api-notes.md) claims, don't silently work
  around it: record the finding in `docs/internals/ha-api-notes.md` and flag it in the
  PR description.
- The README's examples are executed by
  `packages/hassle-cli/tests/test_readme_examples.py` — if you change the
  README or the CLI surface, that test tells you whether they still agree.

## Project history

The codebase was built test-first, milestone by milestone, largely by AI
coding agents working against a written plan. That record — including every
milestone's original acceptance-test contract — is preserved in
[docs/history/](docs/history/), with a legend for its internal vocabulary.
