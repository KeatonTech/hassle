"""Bounded Jinja -> DSL inverter (M13, DESIGN §5.4/§7.3 extension).

Parses **only** the exact grammar :class:`~hassle.compiler.templates.TemplateExpr`
(and :mod:`hassle.compiler.math_expr`) render -- literals, entity reads
(``states('x') | float``, ``state_attr('x', 'a')``), the emitted math
functions/filters, arithmetic/comparison/boolean operators with the
renderer's own precedence and parenthesization rules, ``var(...)`` reads, and
``concat``'s ``~``-joined strings. Nothing else: this is not a general Jinja
parser and never tries to be one (bounded inversion, owner-approved fallback
per MILESTONES M13).

**The acceptance rule is enforced here, not assumed:** :func:`invert_template`
builds an actual runtime value (by calling the SAME builder functions the
compiler would run from the decompiled source) and immediately re-renders it
through the real :class:`TemplateExpr` machinery, comparing the result
BYTE-FOR-BYTE against the original Jinja text. Only on an exact match does it
return a result; any parse failure, unsupported construct, or a successful
parse whose re-rendering doesn't match byte-for-byte returns ``None`` --
the caller (``hassle.decompiler.codegen``) falls back to the unchanged
string-``state=`` call form. I3 holds trivially either way: the fallback is
always available and never drops data.

Two things travel together for every parsed node: the RUNTIME value (a real
:class:`TemplateExpr`, or a plain ``int``/``float``/``str``/``bool`` literal)
used to compute the render-and-compare check, and the PYTHON SOURCE text that
would reproduce it if compiled — both built from the exact same parse, so
they can never disagree with each other (there is no separate
"regenerate source from the value" step that could drift).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, ClassVar, cast

from hassle.compiler import math_expr
from hassle.compiler.helpers import EntityRef
from hassle.compiler.templates import TemplateExpr
from hassle.compiler.templates import var as var_builder
from hassle.decompiler.exprs import render_entity_ref

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<number>\d+\.\d+|\d+)
  | (?P<string>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>==|!=|>=|<=|\*\*|//|[-+*/%()\[\],.|<>~])
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class _Token:
    kind: str  # "number" | "string" | "name" | "op" | "end"
    text: str


class _LexError(Exception):
    pass


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if m is None:
            raise _LexError(f"unrecognized character at position {pos}: {text[pos : pos + 10]!r}")
        pos = m.end()
        if m.lastgroup == "ws":
            continue
        assert m.lastgroup is not None
        tokens.append(_Token(m.lastgroup, m.group()))
    tokens.append(_Token("end", ""))
    return tokens


# ---------------------------------------------------------------------------
# Parse result: a runtime value paired with the Python source that builds it.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Node:
    value: Any  # TemplateExpr, or a plain int/float/str/bool literal
    source: str  # Python source text reproducing `value` when compiled
    # M16: set only by `_call("states", ...)`, to the entity id, for a still-
    # undecided bare `states('x')` read (source defaults to `state_of(...)`).
    # `_filtered`'s `| float` handling checks this to upgrade the SAME node to
    # `expr(...)` (M1's original mapping) when the filter immediately
    # follows; every other consumer just uses `.source`/`.value` as-is, so a
    # non-`None` value here never leaks into a final result.
    bare_states_entity_id: str | None = None


class _ParseError(Exception):
    pass


# Bare Jinja global function names -> the hassle.compiler.math_expr builder
# with the same name (1:1, math_expr.py's own docstring table).
_MATH_FUNCTIONS: dict[str, Any] = {
    "sin": math_expr.sin,
    "cos": math_expr.cos,
    "tan": math_expr.tan,
    "asin": math_expr.asin,
    "acos": math_expr.acos,
    "atan": math_expr.atan,
    "atan2": math_expr.atan2,
    "sqrt": math_expr.sqrt,
    "log": math_expr.log,
    "as_datetime": math_expr.as_datetime,
    "as_timestamp": math_expr.as_timestamp,
    "today_at": math_expr.today_at,
    # NOTE: `timedelta(unit=value, ...)` is deliberately NOT in this table --
    # `timedelta_`'s Jinja spelling is always keyword args
    # (`timedelta(minutes=30)`), which this parser's positional-only
    # `_arg_list` cannot parse at all; a template using it falls back to the
    # string call form (documented grammar boundary, module docstring).
}
_MATH_FUNCTION_SOURCE_NAMES: dict[str, str] = {
    "sin": "sin",
    "cos": "cos",
    "tan": "tan",
    "asin": "asin",
    "acos": "acos",
    "atan": "atan",
    "atan2": "atan2",
    "sqrt": "sqrt",
    "log": "log",
    "as_datetime": "as_datetime",
    "as_timestamp": "as_timestamp",
    "today_at": "today_at",
}

# Jinja constant globals -> the math_expr constant leaf + its DSL source name.
_CONSTANTS: dict[str, tuple[Any, str]] = {
    "pi": (math_expr.PI, "PI"),
    "e": (math_expr.E_, "E_"),
    "tau": (math_expr.TAU, "TAU"),
}

# Trailing-filter names -> (builder, dsl_source_name). `round`/`abs`/`min`/`max`
# match math_expr.py's filter set 1:1.
_FILTER_SOURCE_NAMES: dict[str, str] = {
    "round": "round_",
    "abs": "abs_",
    "min": "min_",
    "max": "max_",
}


class _Parser:
    """Recursive-descent (Pratt-style for binops) parser over the exact
    grammar `TemplateExpr`/`math_expr` emit. Grammar (loosest to tightest):

        or_expr    := and_expr ("or" and_expr)*
        and_expr   := not_expr ("and" not_expr)*
        not_expr   := "not" not_expr | concat_expr
        concat_expr:= cmp_expr ("~" cmp_expr)*
        cmp_expr   := add_expr (("==" | "!=" | ">" | "<" | ">=" | "<=") add_expr)?
        add_expr   := mul_expr (("+" | "-") mul_expr)*
        mul_expr   := pow_expr (("*" | "/" | "//" | "%") pow_expr)*
        pow_expr   := unary ("**" pow_expr)?         # right-assoc
        unary      := "-" unary | filtered
        filtered   := atom ("|" filter_call)*
        atom       := NUMBER | STRING | "(" or_expr ")" | "[" list "]" | call | name
        call       := NAME "(" args ")"
        filter_call:= NAME ["(" args ")"]

    `concat_expr`'s `~` sits looser than comparisons/arithmetic and tighter
    than and/or/not, matching Jinja's real precedence -- `concat(...)` is the
    only DSL builder that emits it (M1.1: "`+` is not concat"), always with
    plain string/leaf operands in every golden case, so this parser accepts
    it at that slot without needing to be exhaustively precedence-tested
    against arithmetic mixed with `~` (the render-and-compare check catches
    any case where that assumption doesn't hold and falls back safely).
    """

    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> _Token:
        return self._tokens[self._pos]

    def _advance(self) -> _Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect_op(self, text: str) -> None:
        tok = self._advance()
        if tok.kind != "op" or tok.text != text:
            raise _ParseError(f"expected {text!r}, got {tok.kind} {tok.text!r}")

    def parse_full(self) -> _Node:
        node = self._or_expr()
        if self._peek().kind != "end":
            raise _ParseError(f"unexpected trailing token {self._peek().text!r}")
        return node

    # -- boolean --------------------------------------------------------
    def _or_expr(self) -> _Node:
        left = self._and_expr()
        while self._peek().kind == "name" and self._peek().text == "or":
            self._advance()
            right = self._and_expr()
            left = _Node(left.value | right.value, f"({left.source} | {right.source})")
        return left

    def _and_expr(self) -> _Node:
        left = self._not_expr()
        while self._peek().kind == "name" and self._peek().text == "and":
            self._advance()
            right = self._not_expr()
            left = _Node(left.value & right.value, f"({left.source} & {right.source})")
        return left

    def _not_expr(self) -> _Node:
        if self._peek().kind == "name" and self._peek().text == "not":
            self._advance()
            inner = self._not_expr()
            return _Node(~inner.value, f"(~{inner.source})")
        return self._concat_expr()

    # -- concat (~) -------------------------------------------------------
    def _concat_expr(self) -> _Node:
        left = self._cmp_expr()
        parts = [left]
        while self._peek().kind == "op" and self._peek().text == "~":
            self._advance()
            parts.append(self._cmp_expr())
        if len(parts) == 1:
            return left
        values = [p.value for p in parts]
        sources = ", ".join(p.source for p in parts)
        rendered = TemplateExpr(" ~ ".join(_operand_repr(v) for v in values), compound=True)
        return _Node(rendered, f"concat({sources})")

    # -- comparisons ------------------------------------------------------
    _CMP_OPS: ClassVar[dict[str, str]] = {
        "==": "eq",
        "!=": "ne",
        ">": "gt",
        "<": "lt",
        ">=": "ge",
        "<=": "le",
    }

    def _cmp_expr(self) -> _Node:
        left = self._add_expr()
        if self._peek().kind == "op" and self._peek().text in self._CMP_OPS:
            op_tok = self._advance()
            method = self._CMP_OPS[op_tok.text]
            right = self._add_expr()
            if not isinstance(left.value, TemplateExpr):
                raise _ParseError("comparison left operand is not a template expression")
            value = getattr(left.value, method)(right.value)
            if method in ("eq", "ne"):
                src = f"{left.source}.{method}({right.source})"
            else:
                src = f"({left.source} {op_tok.text} {right.source})"
            return _Node(value, src)
        if self._peek().kind == "name" and self._peek().text == "in":
            # `states('x') in ['a', 'b']` -- M16's `.in_([...])` membership.
            # The right side is always a literal list in the renderer's own
            # grammar (`TemplateExpr.in_`'s only emitted shape); a bare list
            # atom is exactly what `_atom`'s `[` branch already parses.
            self._advance()
            right = self._add_expr()
            if not isinstance(left.value, TemplateExpr):
                raise _ParseError("`in` left operand is not a template expression")
            right_value: Any = right.value
            if not isinstance(right_value, list):
                raise _ParseError("`in` right operand is not a list literal")
            value = left.value.in_(cast("list[Any]", right_value))
            src = f"{left.source}.in_({right.source})"
            return _Node(value, src)
        return left

    # -- arithmetic ---------------------------------------------------------
    def _add_expr(self) -> _Node:
        left = self._mul_expr()
        while self._peek().kind == "op" and self._peek().text in ("+", "-"):
            op_tok = self._advance()
            right = self._mul_expr()
            value = left.value + right.value if op_tok.text == "+" else left.value - right.value
            left = _Node(value, f"({left.source} {op_tok.text} {right.source})")
        return left

    def _mul_expr(self) -> _Node:
        left = self._pow_expr()
        while self._peek().kind == "op" and self._peek().text in ("*", "/", "//", "%"):
            op_tok = self._advance()
            right = self._pow_expr()
            if op_tok.text == "*":
                value = left.value * right.value
            elif op_tok.text == "/":
                value = left.value / right.value
            elif op_tok.text == "//":
                value = left.value // right.value
            else:
                value = left.value % right.value
            left = _Node(value, f"({left.source} {op_tok.text} {right.source})")
        return left

    def _pow_expr(self) -> _Node:
        left = self._unary()
        if self._peek().kind == "op" and self._peek().text == "**":
            self._advance()
            right = self._pow_expr()  # right-associative
            return _Node(left.value**right.value, f"({left.source} ** {right.source})")
        return left

    def _unary(self) -> _Node:
        if self._peek().kind == "op" and self._peek().text == "-":
            self._advance()
            inner = self._unary()
            return _Node(-inner.value, f"(-{inner.source})")
        return self._filtered()

    # -- filters (bind tighter than arithmetic) ------------------------------
    def _filtered(self) -> _Node:
        node = self._atom()
        while self._peek().kind == "op" and self._peek().text == "|":
            self._advance()
            node = self._filter_call(node)
        return node

    def _filter_call(self, operand: _Node) -> _Node:
        name_tok = self._advance()
        if name_tok.kind != "name":
            raise _ParseError(f"expected filter name, got {name_tok.kind} {name_tok.text!r}")
        name = name_tok.text
        if name == "float":
            if operand.bare_states_entity_id is not None:
                # `states('x') | float` immediately after a bare `states(...)`
                # call -- the numeric-read leaf `expr`/`.value` emit (M1's
                # original mapping), NOT `state_of(...)` (M16's default for
                # an unfiltered bare `states(...)` read).
                entity_id = operand.bare_states_entity_id
                return _Node(
                    TemplateExpr(f"states({entity_id!r}) | float"),
                    f"expr({_entity_source(entity_id)})",
                )
            # `| float` anywhere else (an already-filtered/combined operand):
            # not part of the renderer's grammar (`| float` only ever
            # follows a bare `states(...)` call in emitted output) -- reject
            # rather than silently accept a construct that can't round-trip.
            raise _ParseError("`| float` only valid directly after states(...)")
        args: list[_Node] = []
        if self._peek().kind == "op" and self._peek().text == "(":
            self._advance()
            args = self._arg_list()
            self._expect_op(")")
        if name not in _FILTER_SOURCE_NAMES:
            raise _ParseError(f"unsupported filter {name!r}")
        builder = getattr(math_expr, _FILTER_SOURCE_NAMES[name])
        value = builder(operand.value, *[a.value for a in args])
        dsl_name = _FILTER_SOURCE_NAMES[name]
        arg_src = ", ".join(a.source for a in args)
        src = (
            f"{dsl_name}({operand.source}, {arg_src})" if args else f"{dsl_name}({operand.source})"
        )
        return _Node(value, src)

    def _arg_list(self) -> list[_Node]:
        args: list[_Node] = []
        if self._peek().kind == "op" and self._peek().text == ")":
            return args
        args.append(self._or_expr())
        while self._peek().kind == "op" and self._peek().text == ",":
            self._advance()
            args.append(self._or_expr())
        return args

    def _atom(self) -> _Node:
        tok = self._peek()
        if tok.kind == "number":
            self._advance()
            if "." in tok.text:
                return _Node(float(tok.text), tok.text)
            return _Node(int(tok.text), tok.text)
        if tok.kind == "string":
            self._advance()
            py_value = _jinja_string_literal(tok.text)
            return _Node(py_value, repr(py_value))
        if tok.kind == "op" and tok.text == "(":
            self._advance()
            inner = self._or_expr()
            self._expect_op(")")
            # No extra parens added around `inner.source` here: every binop
            # node below already wraps its OWN emitted source in `(...)`
            # (`_add_expr`/`_mul_expr`/`_pow_expr`/`_and_expr`/`_or_expr`/
            # `_not_expr`/unary `-`), so a parenthesized Jinja sub-expression's
            # source is already exactly as parenthesized as it needs to be --
            # doubling it here would just be cosmetic noise (the
            # render-and-compare check governs correctness, not this).
            return inner
        if tok.kind == "op" and tok.text == "[":
            self._advance()
            items = self._arg_list()
            self._expect_op("]")
            return _Node([i.value for i in items], "[" + ", ".join(i.source for i in items) + "]")
        if tok.kind == "name":
            return self._name_or_call()
        raise _ParseError(f"unexpected token {tok.kind} {tok.text!r}")

    def _name_or_call(self) -> _Node:
        name_tok = self._advance()
        name = name_tok.text
        if self._peek().kind == "op" and self._peek().text == "(":
            self._advance()
            args = self._arg_list()
            self._expect_op(")")
            return self._call(name, args)
        if name in _CONSTANTS:
            value, src = _CONSTANTS[name]
            return _Node(value, src)
        if name in ("true", "false"):
            py_value = name == "true"
            return _Node(py_value, repr(py_value))
        # Bare name: a `var("name")` runtime variables: read.
        return _Node(var_builder(name), f"var({name!r})")

    def _call(self, name: str, args: list[_Node]) -> _Node:
        if name == "states":
            if len(args) != 1 or not isinstance(args[0].value, str):
                raise _ParseError("states(...) needs exactly one string arg")
            entity_id = args[0].value
            # Bare `states('x')` (M16: `state_of(...)`'s own grammar) is the
            # DEFAULT interpretation; `_filter_call`'s `float` branch upgrades
            # this specific node to `expr(...)` (numeric read) when a `| float`
            # filter immediately follows, via `bare_states_entity_id`.
            return _Node(
                TemplateExpr(f"states({entity_id!r})"),
                f"state_of({_entity_source(entity_id)})",
                bare_states_entity_id=entity_id,
            )
        if name == "state_attr":
            if (
                len(args) != 2
                or not isinstance(args[0].value, str)
                or not isinstance(args[1].value, str)
            ):
                raise _ParseError("state_attr(...) needs two string args")
            entity_id, attribute = args[0].value, args[1].value
            value = TemplateExpr(f"state_attr({entity_id!r}, {attribute!r})")
            src = f"{_entity_source(entity_id)}.attr({attribute!r})"
            return _Node(value, src)
        if name in _MATH_FUNCTIONS:
            builder = _MATH_FUNCTIONS[name]
            value = builder(*[a.value for a in args])
            dsl_name = _MATH_FUNCTION_SOURCE_NAMES[name]
            arg_src = ", ".join(a.source for a in args)
            return _Node(value, f"{dsl_name}({arg_src})")
        raise _ParseError(f"unsupported function call {name!r}")


def _entity_source(entity_id: str) -> str:
    if re.match(r"^[a-z_]+\.(?!_)[a-z0-9_]+(?<!_)$", entity_id):
        return render_entity_ref(entity_id)
    return repr(entity_id)


def _jinja_string_literal(token_text: str) -> str:
    """Decode a quoted Jinja/Python string literal token to its Python value."""
    quote = token_text[0]
    body = token_text[1:-1]
    # Reverse repr()'s own escaping: the renderer always produces these via
    # Python's repr(), so unescaping with the matching quote character via
    # `ast.literal_eval` is exact and avoids hand-rolling escape handling.
    import ast

    return ast.literal_eval(f"{quote}{body}{quote}")  # type: ignore[no-any-return]


def _operand_repr(value: Any) -> str:
    if isinstance(value, TemplateExpr):
        return value.render_as_operand()
    return repr(value)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InvertedTemplate:
    """A successfully inverted Jinja template: the Python source text that
    reproduces it (an expression, no ``return`` keyword) plus the exact
    original Jinja text it was checked against (for the caller's own
    diagnostics/logging, never re-checked again)."""

    source: str


def invert_template(jinja_text: str) -> InvertedTemplate | None:
    """Attempt to invert one ``{{ ... }}`` (or bare-inner) Jinja template to
    DSL Python source.

    Returns ``None`` for anything outside the bounded grammar (`_Parser`'s
    docstring), OR when parsing nominally succeeds but the render-and-compare
    check fails (belt-and-suspenders -- should not happen if the grammar
    coverage above is accurate, but this is the actual acceptance gate, not
    the grammar coverage itself; MILESTONES M13: "verified AT DECOMPILE TIME
    (compute, compare, choose branch) -- never emit decorator form on
    faith").
    """
    text = jinja_text.strip()
    is_wrapped = text.startswith("{{") and text.endswith("}}")
    inner = text[2:-2].strip() if is_wrapped else text
    try:
        tokens = _tokenize(inner)
        node = _Parser(tokens).parse_full()
    except (_LexError, _ParseError, ZeroDivisionError, TypeError, ValueError):
        return None

    rendered = _render_result(node.value)
    if rendered is None:
        return None
    # Compare against the ORIGINAL, unstripped text (bug found while adding
    # M16's bare-`states(...)` grammar coverage: comparing against
    # `jinja_text.strip()` instead treats surrounding whitespace -- e.g. a
    # leading/trailing newline around the `{{ ... }}` block, matched by real
    # `template_sensor(state=...)` fixture data -- as a match even though the
    # renderer never reproduces it, silently dropping it on inversion and
    # violating I3. `render()`/`_render_result` always emits the canonical,
    # unpadded form, so only a `jinja_text` with no such padding can ever
    # legitimately match here.
    if rendered != jinja_text:
        return None
    return InvertedTemplate(source=node.source)


def _render_result(value: Any) -> str | None:
    """Render a parsed root value back to its ``{{ ... }}`` Jinja text, the
    same way the compiler would if this were the return value of a decorator
    body (`_render_state` in `hassle.compiler.template_helpers`)."""
    if isinstance(value, TemplateExpr):
        return value.to_template()
    if isinstance(value, str) and not isinstance(value, EntityRef):
        return value
    return None
