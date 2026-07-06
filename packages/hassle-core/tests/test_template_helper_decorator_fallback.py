"""MILESTONES M14 -- decorator form is the canonical template-helper output,
both decompile branches.

Owner feedback on M13: the non-invertible fallback branch should ALSO emit
the decorator shape, with the raw Jinja template as the verbatim string body
of the `return` statement -- same IR, same I3 guarantee, but hand-converting
a helper to Python later means rewriting only the `return` expression. The
call form stays valid DSL (F3, unchanged) -- it just stops being canonical
decompiler OUTPUT.

Both decompile branches (`hassle.decompiler.codegen._template_helper_source`)
now emit `@builder(...)` / `def <ident>(): return ...`; the only difference is
the body -- an inverted `TemplateExpr` expression (M13's "nice" branch) vs. a
verbatim raw-string `return "..."` (this milestone's fallback branch).

Test numbering below matches MILESTONES.md's "Write these tests first" list.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from hassle.compiler.bundle import compile_bundle
from hassle.compiler.template_helpers import reset_declared_template_helpers
from hassle.decompiler.codegen import decompile_object

FALLBACK_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "dsl"
    / "template_helper_declarations"
    / "bundle"
)
INVERTIBLE_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "dsl"
    / "template_helper_decorator_form"
    / "bundle"
)


@pytest.fixture(autouse=True)
def _reset():
    reset_declared_template_helpers()
    yield
    reset_declared_template_helpers()


def _ruff_format(source: str) -> str:
    proc = subprocess.run(
        ["ruff", "format", "-"], input=source, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


# ---------------------------------------------------------------------------
# Test 1: golden update -- the non-invertible fixture(s) now decompile to the
# decorator-with-string form; I3 still holds through the fallback branch.
# ---------------------------------------------------------------------------


def test_noninvertible_template_helpers_decompile_to_decorator_form() -> None:
    """The three `template_helper_declarations` objects whose `state=` is
    outside the M13 bounded inverter's grammar (active_hvac_zones,
    any_door_open, house_scene -- see test_decompile_template_helpers.py's
    module docstring) now decompile to the DECORATOR form, not the call form:
    `@builder(...)` / `def <ident>(): return "<verbatim Jinja>"`."""
    result = compile_bundle(FALLBACK_FIXTURE)
    fallback_keys = {
        "template_number:active_hvac_zones": "template_number",
        "template_binary_sensor:any_door_open": "template_binary_sensor",
        "template_select:house_scene": "template_select",
    }
    for key, builder in fallback_keys.items():
        obj = result.objects[key]
        source = decompile_object(key, obj)
        assert source.startswith(f"@{builder}("), source
        assert "def " in source
        assert "return " in source
        # `state=`/`options=` never appear as decorator KWARGS any more --
        # `options=` (template_select's second template) stays a kwarg
        # unchanged (MILESTONES: "template_select options= stays a kwarg"),
        # so only check `state=` is gone from the decorator's own kwargs.
        decorator_line = source.split("\n", 1)[0]
        assert "state=" not in decorator_line


def test_noninvertible_template_helper_fallback_body_is_verbatim_state_string() -> None:
    """The `return` body's string literal, parsed back via `ast`, is
    byte-identical to the stored `state=` Jinja text -- no re-rendering, no
    normalization, just the raw stored string (I3's fallback-branch
    guarantee: the raw escape hatch never drops or alters data)."""
    result = compile_bundle(FALLBACK_FIXTURE)
    obj = result.objects["template_number:active_hvac_zones"]
    stored_state = obj.to_ha()["state"]
    source = decompile_object("template_number:active_hvac_zones", obj)

    module = ast.parse(source)
    (func_def,) = [n for n in module.body if isinstance(n, ast.FunctionDef)]
    (return_stmt,) = [n for n in func_def.body if isinstance(n, ast.Return)]
    assert isinstance(return_stmt.value, ast.Constant)
    assert return_stmt.value.value == stored_state


def test_noninvertible_template_helper_round_trips_byte_stably(tmp_path: Path) -> None:
    """I3 fallback branch: compile(decompile(x)) == x for every object whose
    state falls outside the bounded inverter's grammar."""
    result = compile_bundle(FALLBACK_FIXTURE)
    original_ir = {key: obj.to_ha() for key, obj in result.objects.items()}

    lines = [
        "from hassle import (",
        "    expr,",
        "    template_binary_sensor,",
        "    template_number,",
        "    template_select,",
        "    template_sensor,",
        ")",
        "from hassle.registry import entities as e",
        "",
    ]
    for key, obj in sorted(result.objects.items()):
        lines.append(decompile_object(key, obj))
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "helpers.py").write_text("\n".join(lines), encoding="utf-8")

    recompiled = compile_bundle(bundle_dir)
    recompiled_ir = {key: obj.to_ha() for key, obj in recompiled.objects.items()}
    assert recompiled_ir == original_ir


# ---------------------------------------------------------------------------
# Test 2: quoting torture test -- templates with `"""`, `'''`, backslashes,
# leading/trailing newlines, and both quote characters round-trip
# byte-exactly (through the real `template_sensor`/decompile/recompile path).
# ---------------------------------------------------------------------------

TORTURE_TEMPLATES = [
    pytest.param('{{ "a" }}\n{{ \'"""\' }}\n{{ 1 }}', id="embedded-triple-double-quote"),
    pytest.param("{{ \"a\" }}\n{{ '\\'\\'\\'' }}\n{{ 1 }}", id="embedded-triple-single-quote"),
    pytest.param("{{ states('sensor.a') }}\\\n{{ 1 }}", id="backslash-line-continuation"),
    pytest.param("\n{{ states('sensor.a') }}", id="leading-newline"),
    pytest.param("{{ states('sensor.a') }}\n", id="trailing-newline"),
    pytest.param(
        "{{ states('sensor.a') }}\n{{ \"nested 'both' \\\"quote\\\" kinds\" }}",
        id="both-quote-characters",
    ),
    pytest.param('{{ states("sensor.a") }}"', id="ends-with-quote-char"),
    pytest.param('"{{ states("sensor.a") }}', id="starts-with-quote-char"),
    pytest.param("{{ states('sensor.a') }}\r\n{{ 1 }}", id="crlf-line-ending"),
    pytest.param("{% set x = 1 %}\n{{ x }}\\", id="trailing-backslash"),
]


@pytest.mark.parametrize("gnarly", TORTURE_TEMPLATES)
def test_quoting_torture_round_trips_byte_exactly(gnarly: str, tmp_path: Path) -> None:
    from hassle import template_sensor
    from hassle.compiler.registry import current_registry, fresh

    fresh()
    template_sensor(name="Gnarly Sensor", state=gnarly)
    prebuilt = current_registry().prebuilt
    obj = next(p.obj for p in prebuilt if p.obj.object_key() == "template_sensor:gnarly_sensor")

    source = decompile_object("template_sensor:gnarly_sensor", obj)
    formatted = _ruff_format(
        "from hassle import template_sensor\n\n" + source,
    )

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "helpers.py").write_text(formatted, encoding="utf-8")

    recompiled = compile_bundle(bundle_dir)
    assert recompiled.objects["template_sensor:gnarly_sensor"].to_ha()["state"] == gnarly


@pytest.mark.parametrize("gnarly", TORTURE_TEMPLATES)
def test_quoting_torture_is_ruff_format_stable(gnarly: str) -> None:
    """Emitted source is a fixed point of `ruff format` (R8 determinism +
    hand-editability: the repo's own pull/decompile pipeline formats
    decompiled output, so a second format pass must never change it again)."""
    from hassle import template_sensor
    from hassle.compiler.registry import current_registry, fresh

    fresh()
    template_sensor(name="Gnarly Sensor 2", state=gnarly)
    prebuilt = current_registry().prebuilt
    obj = next(p.obj for p in prebuilt if p.obj.object_key() == "template_sensor:gnarly_sensor_2")
    source = decompile_object("template_sensor:gnarly_sensor_2", obj)
    wrapped = "from hassle import template_sensor\n\n" + source
    once = _ruff_format(wrapped)
    twice = _ruff_format(once)
    assert once == twice


# ---------------------------------------------------------------------------
# Test 3: invertible-branch output unchanged (regression) -- the M13
# decorator-expression golden fixture decompiles BYTE-IDENTICALLY before and
# after M14.
# ---------------------------------------------------------------------------


def test_invertible_branch_golden_fixture_is_byte_identical_to_source() -> None:
    """`fixtures/dsl/template_helper_decorator_form/bundle/helpers.py` is
    the M13 golden DSL source for the invertible branch -- decompiling the IR
    it compiles to must reproduce, for every object, the SAME decorator
    shape (builder decorator + inverted `TemplateExpr` body) M13 already
    produced; this milestone must not touch that branch's output at all."""
    result = compile_bundle(INVERTIBLE_FIXTURE)
    expected_builder = {
        "template_number:active_hvac_zones": "template_number",
        "template_sensor:average_temp": "template_sensor",
        "template_binary_sensor:any_door_open": "template_binary_sensor",
        "template_select:house_scene": "template_select",
    }
    for key, builder in expected_builder.items():
        obj = result.objects[key]
        source = decompile_object(key, obj)
        assert source.startswith(f"@{builder}(")
        # The M13 "nice" branch never returns a bare string literal -- it
        # returns the inverted TemplateExpr source (an expression built from
        # `expr`/`state`/entity refs, never a `return "..."` constant).
        module = ast.parse(source)
        (func_def,) = [n for n in module.body if isinstance(n, ast.FunctionDef)]
        (return_stmt,) = [n for n in func_def.body if isinstance(n, ast.Return)]
        assert not isinstance(return_stmt.value, ast.Constant), (
            f"{key} regressed to the raw-string fallback body; "
            "the M13 invertible branch must stay unchanged"
        )


def test_invertible_branch_average_temp_body_source_is_unchanged() -> None:
    """Pin the exact source text M13 produced for the one object whose state
    IS inside the bounded inverter's grammar -- a byte-for-byte regression
    check for spec test 3."""
    result = compile_bundle(INVERTIBLE_FIXTURE)
    obj = result.objects["template_sensor:average_temp"]
    source = decompile_object("template_sensor:average_temp", obj)
    assert source == (
        "@template_sensor(name='Average Temp', unit_of_measurement='°C', "
        "device_class='temperature')\n"
        "def average_temp():\n"
        "    return ((expr(e.sensor.a) + expr(e.sensor.b)) / 2)\n"
    )


# ---------------------------------------------------------------------------
# Test 5: byte-stable re-decompile (R8 determinism) -- decompiling the same
# IR twice, independently, produces byte-identical source for the fallback
# branch (test 3's own fixture already covers the invertible branch
# elsewhere; this covers the NEW fallback-branch codegen path this milestone
# adds).
# ---------------------------------------------------------------------------


def test_fallback_branch_decompile_is_byte_stable_across_repeated_calls() -> None:
    result = compile_bundle(FALLBACK_FIXTURE)
    for key, obj in result.objects.items():
        first = decompile_object(key, obj)
        second = decompile_object(key, obj)
        assert first == second
