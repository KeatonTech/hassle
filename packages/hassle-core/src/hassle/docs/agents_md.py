"""`AGENTS.md` generator (DESIGN §12, MILESTONES M9 deliverable 1).

Bundle-specific, short, imperative agent instructions: the workflow contract
(edit -> validate -> test -> plan), hard rules an agent (or a careless human)
would otherwise break, and pointers into the rest of the generated docs.

Written to the bundle root by `hassle init`/`hassle pull` (mirrors the
`lib/README.md`/`tests/README.md` convention in `hassle_cli.init_cmd`).
"""

from __future__ import annotations

from hassle.compiler.errors import CompileTimeBranchError


def generate_agents_md(*, bundle_name: str) -> str:
    """Generate the full contents of a bundle's `AGENTS.md`.

    ``bundle_name`` is typically the bundle directory's own name (or a
    friendlier name from `hassle.toml`, if one is ever added) -- used only to
    make the doc read as belonging to *this* house rather than a generic
    template.
    """
    error_class = CompileTimeBranchError.__name__
    return f"""\
# AGENTS.md — {bundle_name}

This is a [Hassle](https://github.com/hassle-project/hassle) bundle: Python source
that compiles to Home Assistant automations/scripts/helpers. This file is
**generated** by `hassle init`/`hassle pull` — re-run those to refresh it, don't
hand-edit (your own notes belong in `lib/README.md` or a project README instead).

## Workflow contract

Every change to this bundle follows the same loop, in this order:

1. **Edit** the `.py` files under `automations/`, `scripts/`, `helpers/`, `lib/`.
2. **`hassle validate`** — offline; catches unknown entities, bad service params,
   Jinja syntax errors, duplicate ids, and DSL misuse before anything touches HA.
3. **`hassle test`** — runs this bundle's `tests/` against the deterministic
   simulator (no real devices, no network, no wall-clock).
4. **`hassle plan`** — shows exactly what would change in HA; **never** apply
   (`hassle push`) without reading the plan first, especially any deletions.

Do not skip straight to `hassle push`. If `validate` or `test` fails, fix it before
planning/pushing.

## Hard rules

- **Never change an existing object's `id=`.** An object's `id` is its permanent HA
  identity (automation/script `id`, helper's own id) — changing it looks like
  "delete the old one, create a new one" to Hassle and to HA, silently losing the
  entity's history/entity_id stability. Rename the Python function/variable and
  the `alias=` freely; leave `id=` alone.
- **Never hand-edit anything under `.hassle/`** (`manifest.lock`, `registry.json`,
  `plan.json`). These are machine-owned sync state; hand-editing them can corrupt
  the three-way merge between your bundle and live HA. If something in there looks
  wrong, run `hassle pull` (or `hassle stubs --refresh`) instead of editing by hand.
- **Python `if`/`bool()` on a runtime value is a compile time trap, not a bug in
  Hassle.** `if state("light.x").value == "on":` runs once, at compile time —
  not "every time the automation checks" — so it would silently bake in the wrong
  branch forever. Hassle catches this and raises `{error_class}`, which names the
  exact expression and file:line and shows the fix: rewrite it as
  `with if_then(state("light.x").is_("on")):` (and `with else_then():` for the
  else arm). If you see this error, apply that rewrite — do not try to silence it.
- **Commit UI-side pulls separately from your own edits.** `hassle pull` merges
  changes made in the HA UI into this bundle (DESIGN §8.4); `git commit` those by
  themselves (`hassle pull` refuses on a dirty tree by default, precisely so this
  can't get tangled with in-progress work) before starting your own edit.
- **`ignore` globs in `hassle.toml` mean "never touch, ever."** An object key
  matching an `ignore = [...]` glob (fnmatch against `"<domain>:<id>"`, e.g.
  `"input_boolean:material_you_*"`) is filtered out before Hassle even computes a
  plan — it is never adopted, refreshed, updated, or deleted, no matter what
  either side looks like. Don't "fix" an ignored object by editing it locally;
  that edit will never be pushed. Remove the glob first if you actually want to
  manage that object.
- **New helpers: `id=` and the Python name should be the same slug.** When you
  declare a brand-new helper (`input_boolean(id="guest_mode", ...)`), give the
  variable/reference the same slug as `id=` (`guest_mode = input_boolean(id="guest_mode", ...)`)
  — this is what lets the decompiler's helper-declaration check treat the id and
  the Python binding as the same thing on a later pull, and avoids the
  `helper-id-name-mismatch` validator finding.
- **File organization is user-controlled after the first placement.** The
  decompiler only picks a default location (by HA UI category, or `*/misc.py`) for
  an object it has never seen before; after that, an object stays in whatever file
  you put it in. Feel free to reorganize `automations/`/`scripts/`/`helpers/` by
  hand — Hassle tracks each object's file in the manifest, not by convention.
- **A `hassle push` of a legacy-form remote object may show a one-time
  "modernization (one-time)" diff.** That's expected the first time you re-push an
  object that predates Hassle (inner `platform:`, scalar `delay:`, ...) — Hassle
  compiles the modern form and HA stores it that way from then on, so the plan is
  clean on the next run. It is not a sign that something is wrong.

## Consuming validation programmatically

`hassle validate --json` prints exactly one JSON object —
`{{"findings": [{{"code", "severity", "file", "line", "message", "fix"}}, ...]}}`
(paths are bundle-root-relative) — regardless of exit code, with no other output.
Prefer this over parsing the human-readable text output if you need to act on
findings automatically.

## Editor setup (already done for you)

`hassle init`/`hassle pull` generate typed `.pyi` stubs at
`typings/hassle/registry/__init__.pyi` and a `.vscode/settings.json` pointing
Pylance's `python.analysis.stubPath` at `typings` — a bad entity id or service
param is a red squiggle with zero extra configuration, in any editor that uses
Pylance. Run `hassle stubs --refresh` after `hassle pull` if autocomplete looks
stale.

## Where to look next

- `docs/DSL.md` — every DSL construct, each with a real Python-source-to-compiled-YAML
  pair (pattern-match on these instead of guessing syntax).
- `docs/COOKBOOK.md` — ~20+ complete recipes (motion light, presence, thermostat
  schedule, ...), each a working automation plus its passing test.
- `.hassle/registry.json` — the machine-readable entity/service/area/device/label
  inventory (grep this instead of guessing an entity id).
"""
