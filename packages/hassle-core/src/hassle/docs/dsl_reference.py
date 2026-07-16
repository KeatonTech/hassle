"""`docs/DSL.md` generator (DESIGN §12, MILESTONES M9 test 1).

Sources every section's DSL<->compiled-YAML pair directly from the golden
fixtures under ``fixtures/dsl/`` (never re-derived/hand-written) so the doc
can never drift from what the compiler actually does -- the whole point of
generating it. The case->name mapping lives in
:mod:`hassle.docs.construct_map`, curated by hand and coverage-checked
against ``hassle.__all__``.

Deterministic (R8): the same fixture corpus always produces byte-identical
output (dict iteration here always walks ``hassle.__all__``'s own order, and
JSON is re-dumped with a fixed ``indent=2, sort_keys=False`` -- the
compiler's own emission order, matching ``hassle-dev goldens``' convention).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hassle.docs.construct_map import EXEMPT_NAMES, NAME_TO_CASES

_ERROR_DOCS: dict[str, str] = {
    "OnlyIfBlockCoverageError": (
        "Raised when `with only_if(...):` is used but an action is recorded "
        "outside the block (before or after). Automation-level conditions "
        "gate *every* action, so a partial block would be visually misleading. "
        "Fix: move all actions inside the `with only_if(...):` block, or use "
        "the bare `only_if(...)` call form."
    ),
    "CompileTimeBranchError": (
        "Raised when a Python `if`/`bool()` is used on a runtime state "
        "expression (DESIGN §5.5) -- Python control flow runs at *compile* "
        "time, so a native branch on a live entity state would be baked in "
        "wrong. Fix: use `with if_then(expr):` / `with else_then():` instead, "
        "which compile to HA's `if`/`choose` action."
    ),
    "ElseWithoutIfError": (
        "`with else_then():`/`with else_if(...):` used where the immediately "
        "preceding action in the same list isn't an `if_then`/`choose`/"
        "`else_if` block. Fix: move it directly after the block it belongs to."
    ),
    "NoParamContextError": (
        "`param(name)` called outside an active `@shared_script` body. Fix: "
        "only call `param(...)` inside the decorated function; use `var(name)` "
        "for a runtime `variables:` reference instead."
    ),
    "UnknownParamError": (
        "`param(name)` named a field absent from the `@shared_script`'s "
        "signature. Fix: add `name` as a parameter of the decorated function, "
        "or correct the spelling."
    ),
    "SharedScriptParamMisuseError": (
        "Python control flow/numeric coercion (`if`/`bool()`/`range()`/"
        "`int()`/`float()`/`round()`/`math.trunc()`) used on a "
        "`@shared_script` signature parameter (MILESTONES M19: every field-"
        "named parameter is bound to its runtime `param(name)` marker when "
        "the body runs, regardless of its declared default). Fix: for a "
        "runtime count/value, use a runtime construct HA itself supports, "
        "e.g. `with repeat_count(times):` (accepts the marker directly, "
        "honoring whatever the caller passes); for a genuinely compile-time "
        "value, it was never a real HA field -- use a module-level constant "
        "or a `@macro` argument instead."
    ),
    "UnknownFieldError": (
        "A `@shared_script` call-site kwarg is not among the script's "
        "declared `fields=` keys (when `fields=` is given explicitly, it is "
        "the superset source of truth even if the signature would otherwise "
        "accept the kwarg). Fix: add the field to `fields=`, or correct the "
        "call-site kwarg's spelling."
    ),
    "PythonMathMisuseError": (
        "Python's stdlib `math.*` (or a bare `float()`/`int()`) called on a "
        "runtime `TemplateExpr`. Fix: use the matching `hassle` math builder "
        "(`sin`/`cos`/`sqrt`/... ) instead of `math.sin`/etc. -- `math.pi` as "
        "a *plain* Python constant is not a trap, it just folds into a "
        "literal."
    ),
    "TemplateHelperDecoratorBodyError": (
        "Raised when a `@template_number`/`@template_sensor`/"
        "`@template_binary_sensor`/`@template_select` decorator (M13) is "
        "applied to a function that doesn't fit the decorator-form contract: "
        "it must take zero parameters and `return` a `TemplateExpr`/`str` -- "
        "no declared parameters, no recording-verb calls (`service`/`when`/"
        "`only_if`/...), no other return type. Fix: remove the parameters, "
        "return a template expression built from the `hassle.compiler."
        "templates`/`hassle.compiler.math_expr` surface (or a plain Jinja "
        "string), and do nothing else in the function body."
    ),
    "DanglingTemplateHelperDeclarationError": (
        "Raised when `template_number`/`template_sensor`/"
        "`template_binary_sensor`/`template_select` is called with no "
        "`state=` (the M13 decorator-form signal) but is never applied as a "
        "decorator over a function -- the call builds and registers "
        "nothing, so without this check it would compile clean with the "
        "object silently absent. Fix: either add `state=...` to make it a "
        "direct call-form declaration, or apply the call as "
        "`@template_number(...)` (etc.) over a zero-arg function that "
        "`return`s the state expression."
    ),
    "InclusiveNumericBoundError": (
        "Raised by `entity.state >= v` / `entity.state <= v` (M20, "
        "entity-first conditions). Home Assistant's `numeric_state` "
        "condition only supports EXCLUSIVE bounds (`above`/`below`) -- there "
        "is no inclusive form to map `>=`/`<=` onto, so compiling one would "
        "silently produce a condition that is wrong right at the boundary "
        "value. Fix: use the exclusive `>`/`<` operator instead (the exact "
        "boundary value is excluded), or pick a value safely past it."
    ),
    "InOperatorTrapError": (
        "Raised by `entity.state in [...]` (M20, entity-first conditions). "
        "Python's `in` always calls `bool()` on each element comparison to "
        "decide membership -- no overload can intercept this, so the natural "
        "`in` spelling can never build a real condition. Fix: use "
        "`entity.state.in_([...])` instead, which builds a real `state` "
        "condition with list (OR) membership."
    ),
    "ConditionArgumentTypeError": (
        "Raised when a condition-accepting entry point (`only_if`, "
        "`if_then`, `else_if`, `choose().when_`, `repeat_while`, "
        "`repeat_until`, `any_of`/`all_of`/`not_`) receives a plain Python "
        "`bool` instead of a condition-builder object (M20) -- almost always "
        "the classic `==`/`!=`-on-a-plain-value mistake. Fix: build a real "
        'condition, e.g. `entity.state == "on"` or `state(entity_id).'
        'is_("on")`, and pass that instead.'
    ),
}


def _load_case(fixtures_root: Path, case: str) -> tuple[str, dict[str, Any]]:
    case_dir = fixtures_root / case
    bundle_dir = case_dir / "bundle"
    py_files = sorted(p for p in bundle_dir.rglob("*.py") if "__pycache__" not in p.parts)
    source = "\n\n".join(p.read_text(encoding="utf-8") for p in py_files)
    ir_path = case_dir / "expected_ir.json"
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    return source, ir


def _pair_section(name: str, fixtures_root: Path) -> str:
    cases = NAME_TO_CASES[name]
    primary = cases[0]
    source, ir = _load_case(fixtures_root, primary)
    ir_text = json.dumps(ir, indent=2, ensure_ascii=False, sort_keys=True)
    lines = [f"### `{name}`", "", f"Golden case: `fixtures/dsl/{primary}/`.", ""]
    lines += ["```python", source.strip(), "```", ""]
    lines += ["Compiles to (canonical IR / stored HA shape):", ""]
    lines += ["```json", ir_text, "```", ""]
    if len(cases) > 1:
        lines.append("See also: " + ", ".join(f"`fixtures/dsl/{c}/`" for c in cases[1:]))
        lines.append("")
    return "\n".join(lines)


_HEADER = """\
# docs/DSL.md — Hassle DSL reference

**Generated** by `hassle.docs.dsl_reference.generate_dsl_reference` from the golden
fixtures under `fixtures/dsl/` — every section below is sourced directly from a real,
compiler-verified DSL<->compiled-YAML pair, so this file can never drift from what
`hassle` actually does. Do not hand-edit; regenerate via `hassle-dev docs --update`
(mirrors `hassle-dev goldens --update`, R3).

Agents and humans alike: pattern-match on the pair (DESIGN §12) — the Python on top,
the exact compiled shape HA stores underneath.

## Validator coverage boundaries

Two `hassle validate` checks are deliberately permissive rather than strict (from
`hassle.registry.validate`'s own docstring, verbatim intent — kept in sync here so
it can't drift):

- A service whose schema has an empty `fields: {}` is never checked for
  unknown/wrong-type params (an incomplete schema capture looks identical to "this
  service genuinely takes no parameters").
- A bare `entity_id=` kwarg to `service(...)` is never flagged as an "unknown
  service param" (HA's own legacy target shorthand and an intentional data field
  merge into the same `data` dict with no residual marker of which one it started
  as).

Everything else is strict: an unrecognized entity/area/floor/label/device id,
purpose-vocabulary type, or (non-empty-schema) service param always produces a
Finding.

## One-way expression sugar

The template expression builder (`expr`/math builders/operators) is **one-way
sugar**: the decompiler always reconstructs a compiled Jinja string as a raw
`template("...")` string. It never re-derives the operator/builder call chain
(`cos(...)`, `.attr(...)`, comparisons, ...) that produced it. This is a deliberate
simplification (dsl-extensions.md), not a bug — round-tripping still holds (I3) because
`template(...)` is itself a first-class, fully-supported DSL construct.

## Scripts-as-functions: when a call rewrites vs. stays `service(...)`

Calling a `@shared_script`-decorated function elsewhere in the bundle records a
`script.<id>`-style call action (DESIGN §5.6), not a re-run of the script's body.
On decompile, the reverse rewrite (a stored `script.<id>` action becomes a real
Python call to the generated wrapper function) only applies when the call site's
`metadata`/`alias`/`enabled`/field kwargs can be represented by that wrapper's
accepted keywords; anything the wrapper doesn't understand falls back to a plain
`service("script.<id>", ...)` action instead of a rewritten call, so no data is
ever silently dropped (I3).

## Category-first file placement

The decompiler only decides file placement for an object it has never seen before:
its default is one **root-level, mixed-kind** file per HA UI category —
`<slug(category)>.py`, from the object's OWN entity-registry category (automations
and scripts each have their own category-registry scope; every helper kind shares
one scope, `"helpers"` — a category named "HVAC" puts the HVAC automation, the
HVAC script, and the HVAC helpers all in the SAME `hvac.py`) — else the single
shared `misc.py` for every uncategorized object of every kind. After that first
placement, **file organization is entirely user-controlled** — an object always
stays in whatever file the user puts it in (tracked by the manifest), never
auto-moved.

An optional module-level `CATEGORY: str = "Automatic HVAC"` in a category-shaped
file supplies the *exact* display name Hassle uses if it ever has to create that
category fresh in HA (an acronym or punctuation choice a slug can't recover, e.g.
`"HVAC"` from `automatic_hvac.py`) — `slugify(CATEGORY)` must equal the file's own
stem, or `hassle validate` flags it and `hassle push` ignores the global (falling
back to a slug-derived guess) rather than guessing which side is right. It is
consulted ONLY when push has to CREATE a brand-new category; matching an existing
HA category is always slug-based, and an existing category is never renamed by
push (the HA UI owns renames). `hassle pull` writes this line itself whenever it
creates a new category file, so display names round-trip through source; refreshing
an already-existing file never duplicates or moves the line.

## Upgrade / plan-labeling note

`hassle push`ing a legacy-form remote object (inner `platform:`, scalar `delay:`,
...) that was previously adopted produces a ONE-TIME "modernization" diff: Hassle
compiles the modern plural/dict form, and HA stores it verbatim thereafter, so the
very next plan is clean. The plan renderer labels this diff class
`modernization (one-time)` specifically so it doesn't read as an unexpected,
recurring drift.

## Trap / error surface

Every compile-time trap below is an exception class in `hassle.__all__`, assertable
by bundles and tests. These don't compile to an HA YAML shape — the error text
*is* the documentation.

"""


def generate_dsl_reference(fixtures_root: Path) -> str:
    """Generate the full contents of `docs/DSL.md`.

    ``fixtures_root`` is the `fixtures/dsl/` directory. Deterministic:
    iterates `NAME_TO_CASES` in its own definition order (a stable dict,
    Python 3.7+) and `EXEMPT_NAMES` sorted.
    """
    parts = [_HEADER]
    for name in NAME_TO_CASES:
        parts.append(_pair_section(name, fixtures_root))
    for name in sorted(EXEMPT_NAMES):
        parts.append(f"### `{name}`\n\n{_ERROR_DOCS[name]}\n")
    return "\n".join(parts)
