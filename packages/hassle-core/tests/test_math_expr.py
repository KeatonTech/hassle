"""M1.1 — runtime-math expression surface (MILESTONES M1.1, DESIGN §5.4 extension).

Symbolic-expression extension of the template builder: math builders mirroring
HA's Jinja math set 1:1 (sin/cos/tan/asin/acos/atan/atan2/sqrt/log,
round_/min_/max_/abs_), constants (PI/E_/TAU) rendering to Jinja names (never
folded to a Python float literal), `.attr()` entity-attribute access, `var()`
runtime-variable references, and `param()` upgraded to a composable Expr.
Everything here is an F3 ADDITION (docs/dsl-f3.md); no existing name changes.

Test 1 (acceptance examples, verbatim) and test 2 (reflected-operator/
precedence torture test) live here. Test 3 (trap boundary) lives in
test_math_expr_traps.py. Test 4 (shade_tracks_sun golden) lives in
test_math_expr_golden.py.
"""

from __future__ import annotations

from hassle.compiler.math_expr import (
    E_,
    PI,
    TAU,
    abs_,
    acos,
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
)
from hassle.compiler.scripts import param
from hassle.compiler.templates import TemplateExpr, var

# ---------------------------------------------------------------------------
# Test 1 — acceptance examples verbatim (MILESTONES M1.1 test 1)
# ---------------------------------------------------------------------------


def test_acceptance_example_param_sun_angle() -> None:
    # param("sun_angle") / 360 * 2 * PI
    result = param("sun_angle") / 360 * 2 * PI
    assert isinstance(result, TemplateExpr)
    assert result.to_template() == "{{ sun_angle / 360 * 2 * pi }}"


def test_acceptance_example_var_wakeup_offset() -> None:
    # var("wakeup_time") + var("offset")
    result = var("wakeup_time") + var("offset")
    assert isinstance(result, TemplateExpr)
    assert result.to_template() == "{{ wakeup_time + offset }}"


# ---------------------------------------------------------------------------
# Constants render to Jinja names, never a folded float literal.
# ---------------------------------------------------------------------------


def test_pi_e_tau_render_as_jinja_names() -> None:
    assert PI.to_template() == "{{ pi }}"
    assert E_.to_template() == "{{ e }}"
    assert TAU.to_template() == "{{ tau }}"


def test_constants_compose_with_arithmetic() -> None:
    assert (PI * 2).to_template() == "{{ pi * 2 }}"
    assert (2 * PI).to_template() == "{{ 2 * pi }}"


# ---------------------------------------------------------------------------
# Math builders mirror HA's Jinja set 1:1 — functions vs. filters.
# ---------------------------------------------------------------------------


def test_trig_functions_render_as_jinja_function_calls() -> None:
    assert sin(PI).to_template() == "{{ sin(pi) }}"
    assert cos(PI).to_template() == "{{ cos(pi) }}"
    assert tan(PI).to_template() == "{{ tan(pi) }}"
    assert asin(0.5).to_template() == "{{ asin(0.5) }}"
    assert acos(0.5).to_template() == "{{ acos(0.5) }}"
    assert atan(0.5).to_template() == "{{ atan(0.5) }}"


def test_atan2_two_args() -> None:
    result = atan2(var("north"), var("east"))
    assert result.to_template() == "{{ atan2(north, east) }}"


def test_sqrt_and_log() -> None:
    assert sqrt(var("gust")).to_template() == "{{ sqrt(gust) }}"
    assert log(var("x")).to_template() == "{{ log(x) }}"
    assert log(var("x"), 2).to_template() == "{{ log(x, 2) }}"


def test_round_is_a_filter() -> None:
    assert round_(var("x")).to_template() == "{{ x | round }}"
    assert round_(var("x"), 0).to_template() == "{{ x | round(0) }}"
    assert round_(var("x"), 2).to_template() == "{{ x | round(2) }}"


def test_round_parenthesizes_compound_operand() -> None:
    # A compound (already-combined) expression must be grouped before the
    # filter is appended, or the filter would bind to the wrong sub-expression.
    result = round_(var("x") * 100, 0)
    assert result.to_template() == "{{ (x * 100) | round(0) }}"


def test_abs_is_a_filter() -> None:
    assert abs_(var("x")).to_template() == "{{ x | abs }}"
    assert abs_(var("x") - var("y")).to_template() == "{{ (x - y) | abs }}"


def test_min_max_are_list_filters() -> None:
    assert min_(var("a"), var("b")).to_template() == "{{ [a, b] | min }}"
    assert max_(var("a"), var("b"), 10).to_template() == "{{ [a, b, 10] | max }}"


def test_concat_is_explicit_string_join() -> None:
    # `+` is arithmetic, never string concatenation (documented decision) --
    # concatenation is spelled explicitly via `concat(...)`.
    result = concat("Hello, ", var("name"), "!")
    assert result.to_template() == "{{ 'Hello, ' ~ name ~ '!' }}"


# ---------------------------------------------------------------------------
# Test 2 — reflected-operator / precedence torture test (MILESTONES M1.1 test 2)
# ---------------------------------------------------------------------------


def test_reflected_operators_literal_on_left() -> None:
    x = var("x")
    assert (10 - x).to_template() == "{{ 10 - x }}"
    assert (10 / x).to_template() == "{{ 10 / x }}"
    assert (10 // x).to_template() == "{{ 10 // x }}"
    assert (10 % x).to_template() == "{{ 10 % x }}"
    assert (10**x).to_template() == "{{ 10 ** x }}"


def test_reflected_operators_literal_on_right() -> None:
    x = var("x")
    assert (x - 10).to_template() == "{{ x - 10 }}"
    assert (x / 10).to_template() == "{{ x / 10 }}"
    assert (x // 10).to_template() == "{{ x // 10 }}"
    assert (x % 10).to_template() == "{{ x % 10 }}"
    assert (x**10).to_template() == "{{ x ** 10 }}"


def test_unary_negation() -> None:
    x = var("x")
    assert (-x).to_template() == "{{ -x }}"
    # Negating a compound expression must parenthesize it.
    assert (-(x + 1)).to_template() == "{{ -(x + 1) }}"


def test_nested_mixed_ops_precedence_grouping() -> None:
    # param("sun_angle") / 360 * 2 * PI is left-flat (no parens needed since
    # `/` and `*` are same-precedence, left-associative) -- but mixing `+`/`-`
    # with `*`//` must group the lower-precedence sub-expression.
    x = var("x")
    y = var("y")
    result = (x + y) * 2
    assert result.to_template() == "{{ (x + y) * 2 }}"

    result2 = 2 * (x + y)
    assert result2.to_template() == "{{ 2 * (x + y) }}"

    # Wrong grouping would silently drop the parens; extra parens are fine
    # (over-parenthesizing is explicitly acceptable per the milestone), but
    # *missing* parens that change semantics is the failure this test guards.
    result3 = (x - y) / (x + y)
    assert result3.to_template() == "{{ (x - y) / (x + y) }}"


def test_deeply_nested_mixed_ops() -> None:
    x = var("x")
    y = var("y")
    z = var("z")
    result = ((x + y) * z - 1) / 2
    assert result.to_template() == "{{ ((x + y) * z - 1) / 2 }}"


def test_comparison_composes_with_arithmetic_operands() -> None:
    x = var("x")
    result = (x * 2) > 100
    assert result.to_template() == "{{ (x * 2) > 100 }}"
