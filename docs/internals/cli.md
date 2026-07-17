# CLI internals

Design rationale that's too long to keep inline in the source. See DESIGN.md for the
user-facing command semantics; this file is for maintainers of `hassle-cli` and
`hassle-dev`.

## Why click, not typer

Both are solid options; `click` was chosen for three concrete reasons specific to this
command surface:

1. **Testability.** `click.testing.CliRunner` is the framework this whole CLI's test
   suite is written against (exit codes, output snapshots). `typer` is itself built on
   click and exposes the same `CliRunner`, so this alone isn't decisive, but it means
   choosing click adds no indirection between the test harness and the command
   implementation.
2. **Irregular option surface.** Several commands here have option shapes that don't map
   cleanly onto "one Python function signature = one CLI command" (typer's core
   convention): `--accept-local KEY` / `--accept-remote KEY` repeatable options on
   `push`, `run <target> --live
   --skip-conditions`, `--plain`/`NO_COLOR` interacting with a shared root-group option.
   click's explicit `@click.option(...)` decorators and `click.Group` nesting make these
   irregular shapes no harder to write than the regular ones; typer's signature-inference
   sugar buys the most when every command's flags map 1:1 onto simple scalar parameters,
   which is not the common case here.
3. **No extra dependency layer for what we don't use.** typer's main value over raw click
   is rich-powered help/error formatting and signature-based inference; this project
   already depends on `rich` directly for its own plan/diff rendering (with a plain-text
   capture mode for snapshot tests, see `hassle_cli.render`), so typer's rich integration
   is redundant here, not additive.

None of this is a criticism of typer — for a CLI with a more uniform, smaller option
surface it would likely be the simpler choice.

## Rich-markup escaping discipline

`hassle_cli.cli._esc` exists because Rich's `Console.print` parses `[...]`-bracketed
substrings in an f-string as markup tags — silently swallowing them (or raising, for a
malformed tag) if they happen to appear in interpolated data Hassle does not control (a
bundle's own `CATEGORY` name, an object key, an exception message, a validator Finding's
text, decompiled DSL source, ...). Every call site that embeds such data inside a
still-markup-enabled `console.print(f"[style]...{data}...[/style]")` call routes `data`
through `_esc` first. Static, Hassle-authored text (the surrounding `[style]`/`[/style]`
tags and plain English) is never escaped — only the dynamic segment. Call sites that print
a large block of untrusted text (a decompiled DSL diff, a compiled YAML/repr, a rendered
Jinja template) instead pass `markup=False` directly to `console.print`, which is simpler
than escaping the whole block.

This was learned the hard way: an early version of the category-divergence warning
(`hassle_cli.bundle_ops.category_divergence_warnings`) rendered scope names and a
bracketed destination list directly into a `Console.print` call, and the bracketed
content silently vanished from the printed warning. The same bug independently hit the
plan-diff renderer (`hassle_cli.plan_render`) for a decompiled DSL diff containing a list
literal like `triggers=[...]`. Both are now regression-tested and always route through
`_esc` or `markup=False`.

## `hassle pull`'s post-write self-check

After `hassle pull` writes decompiled DSL source to disk, it recompiles the bundle it just
produced before trusting it, comparing the recompiled value against the originally stored
`remote` config via `hassle.sync.pull_apply.values_match` (canonical-JSON value
comparison). This exists because "does it compile" alone cannot catch a decompiler bug
that compiles cleanly but silently changes an object's meaning — an earlier version of
this backstop only checked compilation, and separately used `is_modernization_only_diff`
(which decompiles both sides to DSL text) for the value comparison; that check is not
context-free, since the same value can decompile to different text depending on what else
is in the same batch, and this exact path produced a false negative on a real bundle.
`values_match` is now the single shared comparison both this backstop and pull's
pre-write self-check use, so they can never disagree.

If this check ever fires in practice, the files just written are left in place (never
rolled back) so the user has something to file a bug report with; the fix is always a
`hassle pull --allow-dirty` once a decompiler fix lands.

## Category-first bundle layout (`bundle_ops.py`, `layout_migration.py`)

The bundle layout evolved from three per-kind trees (`automations/`, `scripts/`,
`helpers/`, each internally organized by category) to a single root-level, category-first
layout: every kind's objects land in `<slug(category name)>.py`, and objects with no
UI-assigned category fall back to a shared root-level `misc.py` (replacing the old
`automations/misc.py` / `scripts/misc.py` / `helpers/misc.py` trio).

Placement is always derived from an object's **own** category-registry scope
(`automation`/`script` for those two kinds, the shared `"helpers"` scope for every helper
kind) — never guessed from a sibling. Same category name across scopes naturally lands at
the same file (a slug is just a slug); if HA-side renames make previously-shared scope
names diverge, `bundle_ops.category_divergence_warnings` detects the split (by comparing
each object's previous manifest-recorded path against its freshly computed one) and warns,
naming every scope involved — it never guesses which side is "right". The warning only
fires when the old shared path was itself category-derived; a user's own hand-grouped file
that later happens to gain a category is ordinary per-object re-categorization, not a
"divergence".

`layout_migration.py` is the one-time migration that moves an old-layout bundle (detected
by the presence of any `.py` file under a top-level `automations/`, `scripts/`, or
`helpers/` directory) into the new layout, the moment `hassle pull` sees it. It splices
each managed object out of its old file with the same "remove one top-level statement"
primitive an ordinary DROP uses, and regenerates it at its new destination batched with
every other object landing in the same new file (exactly like a fresh adopt). An old file
is deleted only when nothing but imports would remain — a user's own comment or constant
survives, with just the migrated object's statement removed. Migration never touches HA or
the manifest directly, and the resulting plan is always a no-op: `compute_plan` diffs on
compiled-JSON hash, never on `source_path`, so moving DSL source between files with
byte-identical compiled output changes nothing a plan would report.

## `hassle stubs`: three generated files, one call

`hassle_cli.cli._write_stub_if_changed` generates three files from a registry snapshot in
one pass: the entity stub (`typings/hassle/registry/__init__.pyi`), a typed services stub
(`typings/hassle/services.pyi`), and a top-level re-export stub
(`typings/hassle/__init__.pyi`). The third one exists to guard against pyright treating
`hassle` as a namespace/partial-stub package once submodule stubs exist for it (which
would otherwise hide the real package's own top-level surface) — it re-exports every
`hassle.__all__` name from its true defining module, keyed to whatever the installed
`hassle-core` version's surface currently is. All three are write-if-changed, so an
unchanged registry snapshot never dirties the tree.

An earlier version of this generator wrote to `.hassle/entities.pyi`, a path no
pyright/Pylance configuration (including the one `hassle init` itself scaffolds) ever
pointed at — the generated types were silently never picked up by a real editor. The
current path matches `.vscode/settings.json`'s `python.analysis.stubPath: "typings"`,
verified end-to-end against a real pyright run in `packages/hassle-core/tests/`.

## Bundle-as-uv-project scaffolding (`uv_project.py`)

`hassle init`/`hassle pull` scaffold the bundle root as its own tiny uv project: a
`pyproject.toml` declaring `dependencies = ["hassle-cli"]`, plus a `[tool.uv.sources]`
local-path entry when a toolchain source checkout can be resolved, so `uv run hassle ...`
works standalone inside a bundle directory without the user needing to know whether this
came from a monorepo workspace member.

This never touches an existing `pyproject.toml` — existence is the only thing ever
checked; the content is never parsed, so even a malformed existing file is left
completely alone (matching the "no local or UI edit is ever silently lost" rule elsewhere
in the sync engine).

Toolchain path resolution order (first hit wins):

1. An explicit `toolchain_path` key in `hassle.toml`.
2. Auto-detect: walk up from `hassle_cli.__file__` looking for a directory containing a
   `pyproject.toml` whose `[project].name == "hassle-cli"` — i.e. the running CLI is
   itself an editable install from a source checkout. The `[tool.uv.sources]` path then
   points at that checkout's `packages/hassle-cli`.
3. Neither resolves → no sources table at all (bare dependency — the shape that works
   once `hassle-cli` is published to PyPI).

The auto-detected path is machine-specific by design. Callers that need deterministic,
machine-independent output (`hassle-dev acceptance-bundle`) pass `suppress_sources=True`,
which always emits the bare-dependency shape regardless of what auto-detection would
otherwise find.

## The agent-acceptance harness (`hassle-dev`)

`hassle_dev.acceptance` builds a small harness for evaluating how well an AI coding agent
can work in a Hassle bundle using only the bundle's own generated documentation
(`AGENTS.md`, `docs/DSL.md`, `docs/COOKBOOK.md`) — no other hints. It does not run any
model session itself; it only builds the pieces something else drives:

- `emit_tasks(bundle_dir)` returns 10 representative task prompts (entity swap, add a
  helper and wire it in, add a condition, write a simulator test, diagnose a failing
  test, add a purpose-trigger automation, refactor duplicated logic into a macro, add an
  ignore glob, explain a plan diff, fix a validation finding), each concrete against a
  specific "sample house" bundle shape.
- `hassle_dev.bundle_gen.generate_sample_bundle` builds that sample-house bundle for real,
  by seeding a `FakeBackend` and driving the actual `hassle pull` pipeline in-process — so
  the bundle handed to a session is exactly what a real pull would produce, not a
  hand-written fixture.
- `score_task(bundle_dir)` runs `hassle validate` and `hassle test` as real subprocesses
  against a session's resulting bundle and reports pass/fail. This is a mechanical floor,
  not a correctness grade: a session could produce green-testing nonsense that doesn't
  satisfy the task's actual intent and still "pass" here, so a real evaluation run also
  needs a human (or independent model) spot-check of whether the diff does what the task
  asked.

The intended use: run each of the 10 tasks from its own fresh copy of the same generated
bundle (never sharing edits across tasks), against a fresh model session with no other
context, and track the mechanical pass rate as a regression signal whenever the generated
docs change — the harness's premise is "iterate the docs until this stays green".

One scoring wrinkle worth calling out: the sample bundle deliberately ships one failing
test (`diagnose_failing_test`'s target). If it were a plain failing test, `hassle test`
would never exit 0 for any of the other 9 tasks either, regardless of how well a session
solved its own task. The seeded bug's test is marked `@pytest.mark.xfail(strict=True)`,
so the other 9 tasks' scoring floor is genuinely "did this session's own edit leave the
bundle green" — and `strict=True` means a session that fixes the underlying bug without
also removing the now-inapplicable `xfail` marker still fails the run, so it can't
half-fix the task and score green.
