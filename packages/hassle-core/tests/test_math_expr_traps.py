"""M1.1 test 3 -- trap boundary (MILESTONES M1.1 test 3).

`math.cos(state(x).value)` (Python's stdlib `math` module applied to a
TemplateExpr) must raise a CompileTimeBranchError-family teaching error --
stdlib `math.*` calls `float()` on their argument, which without a trap would
either silently misbehave or raise a bare, unhelpful TypeError; using Python's
own `math` module on a runtime expression is exactly the kind of "looks like
it should work" mistake DESIGN §5.5's trap-catching philosophy exists for.

`math.pi` as a plain Python constant is NOT a trap: it folds into a literal
float and composes fine with the DSL's own operators (it is just a number,
same as writing `3.14159` by hand) -- this is a sanity check, not a special
case in the implementation.
"""

from __future__ import annotations

import math

import pytest

from hassle.compiler.errors import CompileError
from hassle.compiler.templates import var


def test_stdlib_math_cos_on_runtime_expr_raises_teaching_error() -> None:
    x = var("x")
    with pytest.raises(CompileError) as excinfo:
        math.cos(x)
    message = str(excinfo.value)
    # what
    assert "math.cos" in message or "float()" in message
    # fix: points at the DSL's own builder
    assert "hassle.compiler.math_expr" in message or "cos(" in message


def test_stdlib_math_sin_on_runtime_expr_raises_teaching_error() -> None:
    x = var("x")
    with pytest.raises(CompileError):
        math.sin(x)


def test_stdlib_math_pi_plain_constant_folds_and_compiles_fine() -> None:
    # math.pi is just a Python float -- multiplying it into an expression is
    # exactly like writing the literal by hand, not a trap.
    x = var("x")
    result = x * math.pi
    assert result.to_template() == f"{{{{ x * {math.pi!r} }}}}"


def test_builtin_round_on_runtime_expr_raises_teaching_error() -> None:
    # round(x) calls __round__, same class of mistake as math.cos(x) calling
    # __float__ -- both are stdlib functions reaching for a Python numeric
    # value a TemplateExpr does not have at compile time.
    x = var("x")
    with pytest.raises(CompileError) as excinfo:
        round(x)
    message = str(excinfo.value)
    assert "round(" in message or "__round__" in message
    assert "hassle.compiler.math_expr" in message or "round_(" in message


def test_stdlib_math_trunc_on_runtime_expr_raises_teaching_error() -> None:
    x = var("x")
    with pytest.raises(CompileError) as excinfo:
        math.trunc(x)
    message = str(excinfo.value)
    assert "trunc(" in message or "__trunc__" in message
