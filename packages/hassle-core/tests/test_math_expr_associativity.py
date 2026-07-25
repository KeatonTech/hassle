"""Regression: precedence-aware rendering must respect associativity, not
just precedence level.

The bug: ``_binop`` rendered BOTH operands with the same ``min_prec``, so a
same-precedence RIGHT child of a left-associative operator (``-``, ``/``,
``//``, ``%``) silently lost its parens even though it changes the meaning
(``a - (b - c)`` is not ``a - b - c``). The fix: for a left-associative
operator, only the LEFT operand may render flat at the same precedence; the
RIGHT operand needs a strictly higher tagged precedence to render flat (i.e.
the right side renders with ``min_prec = prec + 1``). ``**`` is right-
associative in both Python and Jinja, so the rule mirrors: the RIGHT operand
may render flat at the same precedence, the LEFT operand needs strictly
higher.
"""

from __future__ import annotations

from hassle.compiler.templates import var


def test_subtraction_right_operand_keeps_parens_when_compound() -> None:
    a, b, c = var("a"), var("b"), var("c")
    # a - (b - c) is NOT a - b - c (which means (a - b) - c) -- the right
    # operand of a left-associative `-` must stay grouped.
    result = a - (b - c)
    assert result.to_template() == "{{ a - (b - c) }}"


def test_subtraction_right_operand_lower_precedence_keeps_parens() -> None:
    a, b, c = var("a"), var("b"), var("c")
    result = a - (b + c)
    assert result.to_template() == "{{ a - (b + c) }}"


def test_division_right_operand_same_precedence_keeps_parens() -> None:
    a, b, c = var("a"), var("b"), var("c")
    # a / (b * c) is NOT a / b * c (which means (a / b) * c).
    result = a / (b * c)
    assert result.to_template() == "{{ a / (b * c) }}"


def test_division_right_operand_division_keeps_parens() -> None:
    a, b, c = var("a"), var("b"), var("c")
    # a / (b / c) is NOT a / b / c (which means (a / b) / c).
    result = a / (b / c)
    assert result.to_template() == "{{ a / (b / c) }}"


def test_subtraction_left_operand_same_precedence_still_renders_flat() -> None:
    # Sanity check the fix doesn't over-parenthesize the LEFT side: a
    # left-associative operator's LEFT operand at the same precedence still
    # renders flat, since `(a - b) - c` and `a - b - c` mean the same thing.
    a, b, c = var("a"), var("b"), var("c")
    result = (a - b) - c
    assert result.to_template() == "{{ a - b - c }}"


def test_division_left_operand_same_precedence_still_renders_flat() -> None:
    a, b, c = var("a"), var("b"), var("c")
    result = (a / b) / c
    assert result.to_template() == "{{ a / b / c }}"


def test_pow_is_right_associative_left_operand_keeps_parens() -> None:
    a, b, c = var("a"), var("b"), var("c")
    # (a ** b) ** c is NOT a ** b ** c (which means a ** (b ** c) in both
    # Python and Jinja -- ** is right-associative) -- the LEFT operand of
    # ** must stay grouped when it is itself a ** expression.
    result = (a**b) ** c
    assert result.to_template() == "{{ (a ** b) ** c }}"


def test_pow_right_associative_chain_renders_flat() -> None:
    a, b, c = var("a"), var("b"), var("c")
    result = a ** (b**c)
    assert result.to_template() == "{{ a ** b ** c }}"


def test_pow_left_and_right_chains_are_not_identical() -> None:
    a, b, c = var("a"), var("b"), var("c")
    left_assoc = (a**b) ** c
    right_assoc = a ** (b**c)
    assert left_assoc.to_template() != right_assoc.to_template()
