"""M13 test 2 + test 3 -- the bounded Jinja inverter's acceptance property and
fallback statistics.

Test 2 (inversion property): for EVERY rendered Jinja string the fixture
corpus emits (every `expected_ir.json` under `fixtures/dsl/`, walked
recursively -- the renderer's own test-emitted grammar), whenever
`invert_template` succeeds, `render(invert(t)) == t` byte-for-byte (enforced
BY `invert_template` itself -- this test asserts the enforcement actually
holds, i.e. that a successful result is never a false positive), and the
decompiled decorator source recompiles to the identical `TemplateExpr`
value (I3 through the nice branch: a decorator body built from the inverted
source, run through the real `template_sensor`/`_declare_template_helper`
path, reproduces the exact same `state=` string).

Test 3 (fallback): a hand-written gnarly Jinja template (loops/macros/
whitespace tricks) decompiles to the string-state call form, never raises,
and round-trips byte-stably (I3 through the fallback branch) -- exercised
both directly (`invert_template` returns `None`) and through the full
`_template_helper_source`/`compile_bundle` pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hassle.compiler.bundle import compile_bundle
from hassle.compiler.template_helpers import reset_declared_template_helpers
from hassle.decompiler.codegen import decompile_object
from hassle.decompiler.template_invert import invert_template

FIXTURES_DSL = Path(__file__).resolve().parents[3] / "fixtures" / "dsl"


def _walk_jinja_strings(value: Any, out: list[str]) -> None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{{") and stripped.endswith("}}"):
            out.append(value)
        return
    if isinstance(value, dict):
        for v in value.values():
            _walk_jinja_strings(v, out)
        return
    if isinstance(value, list):
        for v in value:
            _walk_jinja_strings(v, out)


def _corpus_jinja_strings() -> list[str]:
    out: list[str] = []
    for ir_path in sorted(FIXTURES_DSL.glob("*/expected_ir.json")):
        data = json.loads(ir_path.read_text(encoding="utf-8"))
        _walk_jinja_strings(data, out)
    # Deduplicate, preserving first-seen order (deterministic, R8).
    seen: set[str] = set()
    unique: list[str] = []
    for s in out:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


CORPUS = _corpus_jinja_strings()


def test_corpus_has_a_realistic_number_of_jinja_strings() -> None:
    # Sanity floor -- if this drops to near-zero, the corpus walk itself broke
    # (e.g. `expected_ir.json` glob path changed), which would silently make
    # test 2 below vacuous.
    assert len(CORPUS) >= 40, (
        f"only found {len(CORPUS)} Jinja strings in the fixture corpus; "
        "the corpus-walk helper may be broken (see _corpus_jinja_strings)."
    )


@pytest.mark.parametrize("jinja_text", CORPUS)
def test_invert_template_is_byte_stable_when_it_succeeds(jinja_text: str) -> None:
    """Test 2's core property: `invert_template` never returns a false
    positive. Nothing to assert when it returns `None` (the fallback is
    always correct by definition, I3) -- this only checks the SUCCESS case,
    which is exactly where a bug could silently produce wrong DSL source.
    """
    result = invert_template(jinja_text)
    if result is None:
        return
    # Recompile the inverted source through the REAL template_sensor decorator
    # path (not a reimplementation) and check the rendered `state=` matches
    # byte-for-byte -- this is the actual "render(invert(t)) == t" check,
    # run end-to-end through the compiler rather than trusting the inverter's
    # own internal comparison a second time with different code.
    reset_declared_template_helpers()
    from hassle import expr, state, template_sensor, var  # noqa: F401
    from hassle.compiler.math_expr import (  # noqa: F401
        E_,
        PI,
        TAU,
        abs_,
        acos,
        as_datetime,
        as_timestamp,
        asin,
        atan,
        atan2,
        concat,
        cos,
        log,
        max_,
        min_,
        round_,
        sin,
        sqrt,
        tan,
        timedelta_,
        today_at,
    )
    from hassle.registry import entities as e  # noqa: F401

    namespace = {
        "expr": expr,
        "state": state,
        "var": var,
        "e": e,
        "E_": E_,
        "PI": PI,
        "TAU": TAU,
        "abs_": abs_,
        "acos": acos,
        "as_datetime": as_datetime,
        "as_timestamp": as_timestamp,
        "asin": asin,
        "atan": atan,
        "atan2": atan2,
        "concat": concat,
        "cos": cos,
        "log": log,
        "max_": max_,
        "min_": min_,
        "round_": round_,
        "sin": sin,
        "sqrt": sqrt,
        "tan": tan,
        "timedelta_": timedelta_,
        "today_at": today_at,
    }
    rebuilt = eval(result.source, namespace)  # noqa: S307 - trusted, DSL-generated source
    from hassle.compiler.templates import TemplateExpr

    if isinstance(rebuilt, TemplateExpr):
        rendered = rebuilt.to_template()
    else:
        rendered = rebuilt
    assert rendered == jinja_text.strip()


def test_invert_template_corpus_fallback_statistics() -> None:
    """Fallback statistics over the fixture corpus (no silent cap): logs how
    many of the corpus's Jinja strings invert cleanly vs. fall back."""
    inverted = [t for t in CORPUS if invert_template(t) is not None]
    fallback = [t for t in CORPUS if invert_template(t) is None]
    assert len(inverted) + len(fallback) == len(CORPUS)
    # Not a gate (the milestone's bounded-inversion contract makes no promise
    # about WHAT fraction inverts -- only that a fallback never drops data
    # and never errors) -- just visible, uncapped numbers for the report.
    print(
        f"\ntemplate_invert corpus stats: {len(inverted)}/{len(CORPUS)} "
        f"inverted cleanly, {len(fallback)} fell back to the call form."
    )


def test_decorator_form_recompiles_to_identical_ir_for_every_inverted_corpus_entry(
    tmp_path: Path,
) -> None:
    """I3 through the nice branch (test 2's second half): for every corpus
    string that inverts, splice it into a real decorator-form bundle and
    confirm `compile_bundle` reproduces the exact same `state=` text."""
    inverted_cases = [(i, t, invert_template(t)) for i, t in enumerate(CORPUS)]
    inverted_cases = [(i, t, r) for i, t, r in inverted_cases if r is not None]
    assert inverted_cases, "no corpus entries inverted -- test would be vacuous"

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    lines = ["from hassle import *  # noqa: F403", "from hassle.registry import entities as e", ""]
    names: list[tuple[str, str]] = []
    for i, _text, result in inverted_cases:
        name = f"case_{i}"
        names.append((name, result.source))
        lines.append(f"@template_sensor(name={name!r})")
        lines.append(f"def {name}():")
        lines.append(f"    return {result.source}")
        lines.append("")
    (bundle_dir / "helpers.py").write_text("\n".join(lines), encoding="utf-8")

    result = compile_bundle(bundle_dir)
    for i, text, _r in inverted_cases:
        name = f"case_{i}"
        obj = result.objects[f"template_sensor:{name}"]
        assert obj.to_ha()["state"] == text.strip()


# ---------------------------------------------------------------------------
# Test 3: gnarly fallback templates.
# ---------------------------------------------------------------------------

GNARLY_TEMPLATES = [
    # Jinja for-loop -- structurally outside the bounded expression grammar.
    "{{ [1, 2, 3] | map('string') | join(', ') }}",
    # Whitespace-control tags (`{%- -%}`) and a macro-like conditional block.
    "{%- if is_state('binary_sensor.door', 'on') -%}open{%- else -%}closed{%- endif -%}",
    # `selectattr`/`list`/`count` filter chain (already in the corpus, but
    # asserted directly here too as the milestone's own driving example).
    "{{ states.climate | selectattr('state', 'ne', 'off') | list | count }}",
    # Multi-line template with a `set` statement.
    "{% set x = states('sensor.a') | float %}\n{{ x * 2 }}",
]


@pytest.mark.parametrize("gnarly", GNARLY_TEMPLATES)
def test_gnarly_templates_never_error_and_return_none(gnarly: str) -> None:
    assert invert_template(gnarly) is None


@pytest.mark.parametrize("gnarly", GNARLY_TEMPLATES)
def test_gnarly_templates_decompile_to_call_form_and_round_trip(
    gnarly: str, tmp_path: Path
) -> None:
    """End-to-end: a template_sensor whose `state=` is gnarly decompiles to
    the (unchanged) call form, never raises, and recompiling reproduces the
    identical `state=` text byte-for-byte (I3 through the fallback branch)."""
    reset_declared_template_helpers()
    from hassle import template_sensor
    from hassle.compiler.registry import fresh

    fresh()  # isolate this case's registry from other parametrized cases (R8)
    template_sensor(name="Gnarly Sensor", state=gnarly)
    from hassle.compiler.registry import current_registry

    prebuilt = current_registry().prebuilt
    obj = next(p.obj for p in prebuilt if p.obj.object_key() == "template_sensor:gnarly_sensor")

    source = decompile_object("template_sensor:gnarly_sensor", obj)
    assert source.startswith("gnarly_sensor = template_sensor(")
    assert "state=" in source

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "helpers.py").write_text(
        "from hassle import template_sensor\n\n" + source, encoding="utf-8"
    )
    recompiled = compile_bundle(bundle_dir)
    assert recompiled.objects["template_sensor:gnarly_sensor"].to_ha()["state"] == gnarly
