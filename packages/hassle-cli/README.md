# hassle-cli

The `hassle` command-line tool. This package is deliberately thin: it parses
arguments, renders plans/diffs/errors for a terminal, stores the HA token in
the OS keyring, scaffolds new bundles, and wires `hassle-core`'s engines
together. See the repo-root README for the full command table and quickstart.

## In scope

- The `click`-based command tree (`hassle init/login/pull/status/plan/push/
  validate/test/run/explain/render/stubs/fmt/doctor`).
- `hassle.toml` bundle configuration (`config.py`) and its format migrations.
- Scaffolding (`init_cmd.py`): bundle directories, `AGENTS.md` + generated
  docs, `.vscode/settings.json`, CI workflow template, gitignore.
- Terminal rendering of plans, three-way conflict diffs, and findings
  (`plan_render.py`, `diffing.py`, `render.py`).
- Token storage/lookup via `keyring` and the committed-secret scan
  (`token.py`, `doctor.py`).
- Git integration (clean-tree gate for `pull`, commit-message helpers).
- The bundle-as-uv-project scaffold (`uv_project.py`) and layout migration
  for bundles created by older versions (`layout_migration.py`).

## Out of scope (lives in `hassle-core`)

- Compiling, decompiling, planning, applying, validating, simulating —
  anything another frontend might need. In particular the pull engine is
  `hassle.sync.pull_apply`; the CLI only constructs the `SourceWriter` and
  reports results.
- Talking to Home Assistant: backends live in `hassle.backend`; the CLI picks
  one via `backend_factory.py`.

A useful smell test: if a function in this package would still make sense
with `click` removed, it probably belongs in `hassle-core`.

## Testing

Unit tests drive the real command tree through `click.testing.CliRunner`
against an in-process `FakeBackend` — no network. `tests/integration/` needs a
live HA (`HASSLE_TEST_HA_URL`/`HASSLE_TEST_HA_TOKEN`). The README quickstart
loop is pinned by `tests/test_quickstart_demo.py`, and the repo-root README's
examples by `tests/test_readme_examples.py`.
