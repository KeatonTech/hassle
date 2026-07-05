"""Hassle CLI (MILESTONES M7): the daily-driver tool wiring the compiler,
decompiler, validator, simulator, and sync engine (all built in earlier
milestones) into `hassle init|login|pull|status|plan|push|validate|test|run|
fmt|stubs|explain|render|mirror|doctor`.

## Framework choice: `click` (not `typer`)

Both are solid options; `click` was chosen for three concrete reasons specific
to this command surface:

1. **Testability.** `click.testing.CliRunner` is the framework this whole
   milestone's test contract is written against (MILESTONES M7 test 1: "CLI-
   level tests ... exit codes, output snapshots"). `typer` is itself built on
   click and exposes the same `CliRunner`, so this alone isn't decisive, but
   it means choosing click adds no indirection between the test harness and
   the command implementation.
2. **Irregular option surface.** Several commands here have option shapes
   that don't map cleanly onto "one Python function signature = one CLI
   command" (typer's core convention): `--accept-local KEY` / `--accept-remote
   KEY` repeatable options on `push`, a `mirror` sub-group with its own
   subcommands, `run <target> --live --skip-conditions`, `--plain`/`NO_COLOR`
   interacting with a shared root-group option. click's explicit
   `@click.option(...)` decorators and `click.Group` nesting make these
   irregular shapes no harder to write than the regular ones; typer's
   signature-inference sugar buys the most when every command's flags map
   1:1 onto simple scalar parameters, which is not the common case here.
3. **No extra dependency layer for what we don't use.** typer's main value
   over raw click is rich-powered help/error formatting and signature-based
   inference; this project already depends on `rich` directly for its own
   plan/diff rendering (with a plain-text capture mode this milestone
   requires, see `hassle_cli.render`), so typer's rich integration is
   redundant here, not additive.

None of this is a criticism of typer -- for a CLI with a more uniform,
smaller option surface it would likely be the simpler choice.
"""

from __future__ import annotations
