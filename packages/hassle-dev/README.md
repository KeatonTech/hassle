# hassle-dev

Internal development tooling for this repository. Nothing here ships to
users; it exists to keep the fixture corpus, golden files, and generated docs
honest. If you are packaging Hassle, skip this distribution entirely.

## In scope

- `hassle-dev goldens [--update]` — regenerate/verify the DSL ↔ IR golden
  pairs under `fixtures/`. Goldens are never hand-edited; changes must come
  from this command so the diff is reviewable.
- `hassle-dev corpus-stats` — the fixture-corpus contract (how many real
  config shapes are covered, per kind/domain).
- `hassle-dev decompile-coverage` — what fraction of the corpus decompiles
  with zero `raw_*` fallback nodes (CI gate: ≥ 90%).
- `hassle-dev docs` — regenerate and gate the generated docs
  (`docs/DSL.md`, `docs/COOKBOOK.md`): every DSL construct documented from a
  real compiled golden pair, every cookbook recipe compiled and
  simulator-tested.
- `hassle-dev acceptance` — a harness that turns the cookbook into task
  prompts and checks generated results, for evaluating how well
  code-generation tools do against the docs.
- `bundle_gen.py` — deterministic scratch-bundle generation for tests.
- `hassle_dev.snapshots` — the snapshot-assertion helpers shared by all three
  packages' test suites (`check_snapshot`, `normalize_error`).

## Out of scope

- Anything a user of the `hassle` CLI would run: user-facing behavior belongs
  in `hassle-cli` or `hassle-core`.
- CI configuration itself (`.github/workflows/` at the repo root) — this
  package only provides the commands CI invokes.
