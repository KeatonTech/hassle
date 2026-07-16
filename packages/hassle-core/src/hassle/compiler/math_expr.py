"""Runtime-math expression surface (MILESTONES M1.1, DESIGN §5.4 extension).

Symbolic-expression extension of the template builder (SymPy-style: leaves
return :class:`~hassle.compiler.templates.TemplateExpr` objects, operators
compose, render to Jinja at compile time -- owner-confirmed direction, see
MILESTONES M1.1). Everything here is an F3 ADDITION; no existing name changes.

**Sibling builder module** (same convention as ``templates.py`` itself,
docs/compiler-api.md's "may you edit" column): it does not modify
``hassle.compiler.builders`` or ``hassle.compiler.templates``'s existing
names, only imports :class:`TemplateExpr` and composes with it.

Mirrors HA's Jinja math set 1:1, with the same function-vs-filter split HA/
Jinja2 itself makes:

- **Functions** (HA-added Jinja globals, rendered as bare calls --
  ``sin(x)``, ``atan2(a, b)``): ``sin``/``cos``/``tan``/``asin``/``acos``/
  ``atan``/``atan2``/``sqrt``/``log``, plus the datetime helpers
  ``as_datetime``/``as_timestamp``/``today_at``/``timedelta_``.
- **Filters** (Jinja2 built-ins, rendered as ``| name`` or ``| name(args)``):
  ``round_`` -> ``| round`` / ``| round(n)``; ``abs_`` -> ``| abs``;
  ``min_``/``max_`` -> ``[a, b, ...] | min`` / ``| max`` (Jinja2's ``min``/
  ``max`` filters operate on an iterable, not varargs, so multiple operands
  are collected into a literal list first).

This split is pinned by the ``shade_tracks_sun`` golden (MILESTONES M1.1 test
4, ``fixtures/dsl/shade_tracks_sun``): ``cos``/``state_attr`` are bare function
calls, ``round_`` is a trailing filter.

Constants ``PI``/``E_``/``TAU`` are bare ``TemplateExpr`` leaves rendering to
Jinja's own global names (``pi``/``e``/``tau``) -- never folded to a Python
float literal, so they stay symbolic and compose like any other expression.

``concat(...)`` is the explicit string-join helper for the documented
"``+`` is not concat" decision (MILESTONES M1.1 deliverables): ``+`` is always
arithmetic (Jinja raises at render time if you add incompatible types), so
string joining is spelled with Jinja's ``~`` operator via this helper instead
of overloading ``+`` for two purposes.
"""

from __future__ import annotations

from typing import Any

from hassle.compiler.templates import TemplateExpr


def _render_call_arg(value: Any) -> str:
    """Render one function-call argument.

    A call argument is always fully delimited by the call's own ``(...)`` --
    it never needs extra grouping for precedence (``cos(a * b / c)``, never
    ``cos((a * b / c))``). ``min_prec=0`` tells ``_as_operand`` any arithmetic-
    tagged compound operand may render flat; non-arithmetic operators
    (comparisons, boolean and/or/not, raw templates) are untagged (``_prec is
    None``) and keep their own always-parenthesize rule, matching the
    ``shade_tracks_sun`` golden's bare ``cos(state_attr(...) * pi / 180)``.
    """
    if isinstance(value, TemplateExpr):
        return value.render_as_operand(min_prec=0)
    return repr(value)


def _render_operand(value: Any) -> str:
    """Render one plain operand (filter input, list element): the *original*
    M1 always-parenthesize-if-compound rule, no precedence exception.

    Jinja's ``|`` (filter) binds *tighter* than every arithmetic operator, so
    -- unlike a call argument -- a filter's input operand must stay
    parenthesized when compound, or the filter would silently bind to the
    wrong sub-expression (``100 * cos(...) | round(0)`` would parse as
    ``100 * (cos(...) | round(0))``). Matches the ``shade_tracks_sun``
    golden's ``(100 * cos(...)) | round(0)``.
    """
    if isinstance(value, TemplateExpr):
        return value.render_as_operand()
    return repr(value)


def _call(name: str, *args: Any) -> TemplateExpr:
    """Render a bare Jinja function call: ``name(arg1, arg2, ...)``.

    Marked **not** compound: the call's own parens already delimit it, so it
    never needs an extra wrapping pair when used as an operand of a further
    operator (``cos(x) * 2``, never ``(cos(x)) * 2``) -- matches the
    ``shade_tracks_sun`` golden's ``100 * cos(...)``.
    """
    rendered_args = ", ".join(_render_call_arg(a) for a in args)
    return TemplateExpr(f"{name}({rendered_args})", compound=False)


def _filter(operand: Any, name: str, *args: Any) -> TemplateExpr:
    """Render a trailing Jinja filter: ``operand | name`` or ``operand | name(args)``.

    The *input* operand is parenthesized when compound (an already-combined
    expression) so the filter binds to the whole thing, matching the
    ``shade_tracks_sun`` golden's ``(100 * cos(...)) | round(0)``. The
    *result* is marked not compound: Jinja's ``|`` binds tighter than
    arithmetic, so a filter result needs no extra parens when used as an
    operand of a further operator either. Filter *arguments* (``round_(x, 2)``'s
    ``2``) are call-like (fully delimited by the filter's own ``(...)``), so
    they use the permissive call-argument rendering.
    """
    rendered_operand = _render_operand(operand)
    if args:
        rendered_args = ", ".join(_render_call_arg(a) for a in args)
        return TemplateExpr(f"{rendered_operand} | {name}({rendered_args})", compound=False)
    return TemplateExpr(f"{rendered_operand} | {name}", compound=False)


# ---------------------------------------------------------------------------
# Constants -- bare Jinja-name leaves, never folded to a Python float.
# ---------------------------------------------------------------------------

PI: TemplateExpr = TemplateExpr("pi")
E_: TemplateExpr = TemplateExpr("e")
TAU: TemplateExpr = TemplateExpr("tau")


# ---------------------------------------------------------------------------
# Trig / algebra -- bare Jinja function calls (HA-added globals).
# ---------------------------------------------------------------------------


def sin(x: Any) -> TemplateExpr:
    """``sin(x)`` (HA Jinja global)."""
    return _call("sin", x)


def cos(x: Any) -> TemplateExpr:
    """``cos(x)`` (HA Jinja global)."""
    return _call("cos", x)


def tan(x: Any) -> TemplateExpr:
    """``tan(x)`` (HA Jinja global)."""
    return _call("tan", x)


def asin(x: Any) -> TemplateExpr:
    """``asin(x)`` (HA Jinja global)."""
    return _call("asin", x)


def acos(x: Any) -> TemplateExpr:
    """``acos(x)`` (HA Jinja global)."""
    return _call("acos", x)


def atan(x: Any) -> TemplateExpr:
    """``atan(x)`` (HA Jinja global)."""
    return _call("atan", x)


def atan2(y: Any, x: Any) -> TemplateExpr:
    """``atan2(y, x)`` (HA Jinja global)."""
    return _call("atan2", y, x)


def sqrt(x: Any) -> TemplateExpr:
    """``sqrt(x)`` (HA Jinja global)."""
    return _call("sqrt", x)


def log(x: Any, base: Any = None) -> TemplateExpr:
    """``log(x)`` or, with a base, ``log(x, base)`` (HA Jinja global)."""
    if base is None:
        return _call("log", x)
    return _call("log", x, base)


# ---------------------------------------------------------------------------
# round_/min_/max_/abs_ -- Jinja2 built-in filters.
# ---------------------------------------------------------------------------


def round_(x: Any, precision: int | None = None) -> TemplateExpr:
    """``x | round`` or, with a precision, ``x | round(precision)``."""
    if precision is None:
        return _filter(x, "round")
    return _filter(x, "round", precision)


def abs_(x: Any) -> TemplateExpr:
    """``x | abs``."""
    return _filter(x, "abs")


def min_(*args: Any) -> TemplateExpr:
    """``[a, b, ...] | min`` -- Jinja2's ``min`` filter operates on an
    iterable, not varargs, so the operands are collected into a literal list.
    Not compound (see :func:`_filter`'s note on ``|`` binding tighter than
    arithmetic): a literal list-filter needs no extra parens either. List
    elements are call-like (fully delimited by ``[``/``,``/``]``)."""
    rendered = ", ".join(_render_call_arg(a) for a in args)
    return TemplateExpr(f"[{rendered}] | min", compound=False)


def max_(*args: Any) -> TemplateExpr:
    """``[a, b, ...] | max`` (see :func:`min_`)."""
    rendered = ", ".join(_render_call_arg(a) for a in args)
    return TemplateExpr(f"[{rendered}] | max", compound=False)


# ---------------------------------------------------------------------------
# Datetime helpers -- bare Jinja function calls (HA-added globals).
# ---------------------------------------------------------------------------


def as_datetime(x: Any) -> TemplateExpr:
    """``as_datetime(x)`` (HA Jinja global)."""
    return _call("as_datetime", x)


def as_timestamp(x: Any) -> TemplateExpr:
    """``as_timestamp(x)`` (HA Jinja global)."""
    return _call("as_timestamp", x)


def today_at(time_str: str) -> TemplateExpr:
    """``today_at('HH:MM:SS')`` (HA Jinja global)."""
    return _call("today_at", time_str)


def timedelta_(**units: Any) -> TemplateExpr:
    """``timedelta(unit=value, ...)`` (Jinja2/Python ``timedelta`` global).

    Named ``timedelta_`` (trailing underscore) so it never collides with
    stdlib ``datetime.timedelta`` in a bundle that imports both.
    """
    rendered = ", ".join(f"{unit}={value!r}" for unit, value in units.items())
    return TemplateExpr(f"timedelta({rendered})", compound=False)


# ---------------------------------------------------------------------------
# concat -- explicit string join (the documented "+ is not concat" decision).
# ---------------------------------------------------------------------------


def concat(*parts: Any) -> TemplateExpr:
    """Explicit string concatenation via Jinja's ``~`` operator.

    ``+`` on a :class:`TemplateExpr` is always arithmetic (MILESTONES M1.1
    deliverables: "documented `+`-is-not-concat decision") -- Jinja itself
    raises at render time if you add incompatible types, matching Python's own
    "explicit is better than implicit" string-vs-number distinction. Joining
    text is spelled explicitly with this helper, which renders Jinja's ``~``
    operator (auto-stringifying, unlike ``+``).
    """
    rendered = " ~ ".join(_render_operand(p) for p in parts)
    return TemplateExpr(rendered, compound=True)
