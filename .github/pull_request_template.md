## What this changes

<!-- One or two sentences. If it fixes an issue, link it. -->

## Test contract

<!--
Which tests prove this works? New behavior needs tests that fail without the
change; a bug fix needs a regression test. Name them.
-->

## Checklist

- [ ] Tests added/updated, and they fail without this change
- [ ] `uv run pytest -m "not integration"` passes
- [ ] `uv run ruff format --check . && uv run ruff check .` passes
- [ ] `uv run pyright` passes
- [ ] Golden/generated files, if changed, were regenerated with
      `hassle-dev goldens --update` / `hassle-dev docs --update` (never hand-edited)
- [ ] A change to a compatibility contract (`docs/internals/ir-format.md`,
      `backend-protocol.md`, `dsl-extensions.md`) updates that document here too
- [ ] New user-facing errors state what / where / fix and have snapshot tests

<!-- See CONTRIBUTING.md for the full rules. -->
