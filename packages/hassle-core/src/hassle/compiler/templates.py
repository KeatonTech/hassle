"""Template expression builder: operator overloading -> Jinja strings (DESIGN §5.4).

``state(x).value`` / ``expr(x)`` wrap an entity reference in a numeric-context
Jinja read (``states('x') | float``); comparisons, arithmetic, and boolean
operators on those build up a nested Jinja expression string. ``template(...)``
is the raw-Jinja passthrough (validated later by tier-3 lint, §9 -- out of
scope here).

This is a **sibling builder module** (docs/m1-internal-api.md's "may you edit"
column): it does not modify ``hassle.compiler.builders``. It reuses the
documented extension seam for the ``__bool__`` trap -- subclassing
``builders._NoBool`` and overriding ``_branch_repr`` is explicitly sanctioned by
docs/m1-internal-api.md section 5. Comparison results (``TemplateExpr``
instances produced by ``>``, ``==``, ...) inherit that trap, so a native Python
``if`` on a template comparison fails loudly exactly like a state condition
does (DESIGN §5.5).

``TemplateExpr`` is a ``str`` subclass (its value IS the rendered ``{{ ... }}``
text) so it serializes natively wherever a plain string value is expected --
e.g. as a service-call kwarg (``ServiceAction`` in the frozen ``builders.py``
just stores whatever value it is given; a ``TemplateExpr`` needs no special
handling there because it already *is* the JSON-serializable string) or inside
a script's fields. Only the operators are overridden; everything else about
being a string (equality with a plain str of the same text, hashing, repr for
debugging) still works via the ``str`` base.

Supported operator surface (kept documented here -- M4's simulator and the docs
generator (M9) consume this table so a template can be interpreted/documented
without re-deriving it from the operator overloads). ``a``/``b`` stand for
either a ``TemplateExpr`` or a bare Python literal (``int``/``float``/``str``/
``bool``, rendered with ``repr()`` -- so ``25`` -> ``25``, ``"on"`` -> ``'on'``,
matching Jinja literal syntax). A *simple* operand (a literal, or a
non-compound ``TemplateExpr`` such as ``expr(x)``/``state(x).value`` itself)
renders bare; a *compound* operand (the result of an earlier operator) is
wrapped in parens to preserve grouping:

| Python            | Jinja (simple operands) | Notes                    |
|--------------------|---------------------------|----------------------------|
| ``state(x).value`` / ``expr(x)`` | ``states('x') \\| float`` | numeric read |
| ``state_of(x)`` | ``states('x')`` | string read (M16) |
| ``a > b`` / ``a < b`` | ``a > b`` / ``a < b`` | also ``>=``/``<=`` |
| ``a == b`` / ``a != b`` | ``a == b`` / ``a != b`` | via ``.eq()``/``.ne()`` |
| ``a.in_(["x", "y"])`` | ``a in ['x', 'y']`` | membership (M16) |
| ``a + b`` / ``a - b`` | ``a + b`` / ``a - b`` | also ``*``/``/`` |
| ``a // b`` | ``a // b`` | floor division (M1.1) |
| ``a % b`` | ``a % b`` | modulo (M1.1) |
| ``a ** b`` | ``a ** b`` | power (M1.1) |
| ``-a`` | ``-a`` (``-(a)`` if compound) | unary negation (M1.1) |
| ``a & b`` | ``a and b`` | boolean and |
| ``a \\| b`` | ``a or b`` | boolean or |
| ``~a`` | ``not a`` (``not (a)`` if compound) | boolean not |
| ``template("{{ ... }}")`` | ``{{ ... }}`` verbatim | raw passthrough |
| ``var("name")`` | ``name`` | runtime ``variables:`` read (M1.1) |
| ``x.attr("a")`` (entity ref) | ``state_attr('x', 'a')`` | attribute read (M1.1) |

Note on ``==``/``!=``: ``TemplateExpr`` is a ``str`` subclass, and Python/pytest
rely on plain ``==`` for equality and container membership everywhere (dict
keys, ``assert a == b``, ...). Overriding ``__eq__`` to build a template would
break that silently. So ``==``/``!=`` keep their normal string-equality meaning;
the Jinja comparison is spelled ``.eq(other)`` / ``.ne(other)`` instead.

M1.1 adds one more trap alongside the ``__bool__``/``CompileTimeBranchError``
one: ``__float__``/``__int__`` raise :class:`PythonMathMisuseError` so Python's
stdlib ``math.*`` (which calls ``float()`` on its argument) fails loudly and
teaches the fix (``hassle.compiler.math_expr``) instead of raising a bare
``TypeError`` or silently coercing to something meaningless. Expression sugar
here is one-way: the M2 decompiler always reconstructs Jinja as a raw
``template("...")`` string, never re-derives the builder call chain that
produced it (MILESTONES M1.1 test 5).
"""

from __future__ import annotations

from typing import Any

# `_NoBool` is private to builders.py, but docs/m1-internal-api.md §5
# explicitly sanctions subclassing it for the `__bool__` trap ("subclass
# `builders._NoBool`, override `_branch_repr`"): pyright's cross-module
# private-access check is silenced here for that one documented reason.
from hassle.compiler.builders import StateExpr, _NoBool  # pyright: ignore[reportPrivateUsage]
from hassle.compiler.errors import CompileError
from hassle.compiler.spans import capture_span

# `.value` reads the entity id through StateExpr's public `entity_id` accessor
# (added in the M1 integration pass; the earlier private-`_entity_id` coupling
# is gone). `.value` itself is attached to StateExpr as an additive property
# from this sibling module (see the bottom of this file) — a purely additive
# extension, not a rewrite of builders.py.


class PythonMathMisuseError(CompileError):
    """Python's stdlib ``math``/numeric-coercion machinery was called on a
    runtime ``TemplateExpr``.

    ``math.cos(x)`` (and every other ``math.*`` function) calls ``float(x)`` on
    its argument before doing anything else; ``round(x)`` calls ``__round__``;
    ``math.trunc(x)`` calls ``__trunc__``. A ``TemplateExpr`` has no runtime
    value at compile time -- it is Jinja text under construction -- so this is
    the same class of mistake DESIGN §5.5 traps for a Python ``if`` on a state
    expression: it looks like it should work, and would either raise a bare
    ``TypeError`` or (worse) silently coerce to something meaningless. M1.1
    (MILESTONES M1.1 test 3) traps it at the same boundary (``__float__``/
    ``__int__``/``__round__``/``__trunc__``) with the same what/where/fix shape.
    """

    def __init__(self, expr_repr: str, span: Any) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        super().__init__(
            f"You called Python's `math`/`float()`/`int()`/`round()`/`math.trunc()` on "
            f"the runtime expression `{expr_repr}`{where}. Those stdlib functions call "
            f"`float()`/`__round__`/`__trunc__` on their argument, but a Hassle template "
            f"expression has no value until it renders inside Home Assistant -- it is "
            f"Jinja text under construction, not a number. "
            f"Fix: use Hassle's own math builders instead, e.g. "
            f"`from hassle.compiler.math_expr import cos, round_` and call "
            f"`cos({expr_repr})` / `round_({expr_repr})`, which stay inside the template "
            f"and render to Jinja's `cos(...)` / `| round`."
        )


class TemplateEntityRefError(CompileError):
    """`expr()`/`state(...).value`/`state_of()` was given something that
    doesn't name exactly one entity (R6: what/where/fix -- M9 error-message
    audit finding. Previously a bare `TypeError` with no file:line, reachable
    from ordinary bundle authoring, e.g. `expr(state(["light.a", "light.b"]))`
    or `expr(123)`. `state_of()` (M16) reuses this same check -- it mirrors
    `expr()`'s argument handling exactly, so the same misuse is reachable
    from it too)."""

    def __init__(self, detail: str, span: Any) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        super().__init__(
            f"`expr()`/`state(...).value`/`state_of()`{where}: {detail} Fix: pass a "
            f"single entity id string (or a `state(...)` builder built from one) -- a "
            f"template read always names exactly one entity."
        )


class TemplateComparisonOperandError(CompileError):
    """`.eq()`/`.ne()` was given something that is neither a `TemplateExpr`
    nor a bare Jinja-literal-compatible Python value (`int`/`float`/`str`/
    `bool`) -- e.g. a list or dict (M16 test 5: what/where/fix, R6). Without
    this check, `TemplateExpr._render_operand` would silently `repr()` the
    value into nonsense Jinja (a Python list's repr happens to look like a
    Jinja list literal for simple cases, but a dict, custom object, or nested
    structure would not -- and even the list case is not the DSL's documented
    membership spelling, `.in_([...])`, so letting it through `.eq()` would
    be confusing either way)."""

    def __init__(self, value: Any, method: str, span: Any) -> None:
        where = f" at {span.file}:{span.line}" if span is not None else ""
        if method == "in_":
            # Polish-batch item 5: `.in_([...])` applies this SAME check to
            # EACH element -- the generic "use `.in_([...])` instead" fix
            # text (below, for `.eq()`/`.ne()`) would be self-referential
            # nonsense here, so state the per-element requirement directly.
            super().__init__(
                f"`.in_([..., {value!r}, ...])`{where}: every element of `.in_([...])` must "
                f"be a template expression or a bare int/float/str/bool literal, not "
                f"{type(value).__name__}. Fix: pass only literal values or template "
                f"expressions as elements (e.g. `.in_(['on', 'off'])`)."
            )
            return
        super().__init__(
            f"`.{method}({value!r})`{where}: comparison operands must be a template "
            f"expression or a bare int/float/str/bool literal, not {type(value).__name__}. "
            f"Fix: pass a literal value (e.g. `.{method}('on')`), another template "
            f"expression, or -- for membership against a list of strings -- use "
            f"`.in_([...])` instead of `.{method}(...)`."
        )


def _check_comparison_operand(value: Any, method: str) -> None:
    if isinstance(value, (TemplateExpr, int, float, str, bool)):
        return
    raise TemplateComparisonOperandError(value, method, capture_span(depth=0))


def _entity_ref_str(value: Any) -> str:
    """Coerce an entity reference (a plain entity_id string, or a StateExpr) to
    its ``domain.object_id`` string.

    A template read always names exactly one entity, so a ``StateExpr`` built
    from a list ``entity_id`` (real-world smoke-test addition: the HA UI's
    list-valued trigger fields, ``state([...])``) is rejected here with a
    what/where/fix error (:class:`TemplateEntityRefError`) rather than
    silently stringifying the list.
    """
    if isinstance(value, StateExpr):
        entity_id = value.entity_id
        if isinstance(entity_id, str):
            return entity_id
        raise TemplateEntityRefError(
            f"this `state(...)` builder was constructed with a list entity_id "
            f"({entity_id!r}), not a single entity id.",
            capture_span(depth=0),
        )
    if isinstance(value, str):
        return value
    raise TemplateEntityRefError(
        f"expected an entity id string or a `state(...)` builder, got "
        f"{value!r} ({type(value).__name__}).",
        capture_span(depth=0),
    )


class TemplateExpr(_NoBool, str):
    """A Jinja expression under construction -- IS the rendered ``{{ ... }}`` text.

    Being a ``str`` subclass means a ``TemplateExpr`` serializes natively
    anywhere a plain string is accepted (service-call data, script fields, ...)
    with no coercion step. Operators build a *new* ``TemplateExpr`` by joining
    operands with the Jinja spelling (see the module docstring table),
    parenthesizing only compound (already-combined) operands. Comparisons
    (``>``/``<``/``.eq``/``.ne``/...) inherit the ``__bool__`` trap (DESIGN
    §5.5): a native Python ``if`` on one raises ``CompileTimeBranchError``
    naming the offending expression.
    """

    _inner: str
    _compound: bool
    _prec: int | None

    def __new__(
        cls, inner: str, *, compound: bool = False, prec: int | None = None
    ) -> TemplateExpr:
        obj = str.__new__(cls, f"{{{{ {inner} }}}}")
        obj._inner = inner
        # `compound` marks "the result of a previous operator" so a later
        # operator knows to parenthesize this expression when nesting it.
        obj._compound = compound
        # `prec` (M1.1 addition) is set only by the arithmetic binops
        # (+ - * / // % **); `None` means "always parenthesize when compound"
        # -- the original M1 behavior, preserved for every other operator
        # family (comparisons, boolean and/or/not, filters, calls, ...).
        # Arithmetic operators tag their precedence level so same-or-higher
        # precedence children can render flat (`a * b / c`, not
        # `(a * b) / c`) -- matches Python/Jinja's own binding rules and is
        # what the `shade_tracks_sun` golden (MILESTONES M1.1 test 4) pins
        # (`state_attr(...) * pi / 180`, no redundant parens).
        obj._prec = prec
        return obj

    def _branch_repr(self) -> str:
        return self.to_template()

    def to_template(self) -> str:
        """The full ``{{ ... }}`` Jinja template string (same as ``str(self)``)."""
        return str(self)

    # A raw-Jinja ``template(...)`` is also usable as a template trigger/condition
    # (DESIGN §5.4 lists ``template()`` among the trigger builders). One name, one
    # object: inside ``when``/``only_if`` it serializes to the template block; as a
    # bare value it IS the ``{{ ... }}`` string.
    def to_trigger(self) -> dict[str, str]:
        return {"trigger": "template", "value_template": self.to_template()}

    def to_condition(self) -> dict[str, str]:
        return {"condition": "template", "value_template": self.to_template()}

    def __repr__(self) -> str:
        return f"TemplateExpr({self._inner!r})"

    @staticmethod
    def _render_operand(value: Any, *, min_prec: int | None = None) -> str:
        """Render one operand: a compound TemplateExpr in parens, a simple
        TemplateExpr or Python literal bare (matches the DESIGN §5.4 examples,
        which have no redundant parens around a plain comparison/subtraction).

        ``min_prec`` (M1.1 addition) is the calling arithmetic operator's
        precedence level; an operand tagged with a precedence >= ``min_prec``
        renders flat (``a * b / c``, matching Python/Jinja's own left-to-right,
        same-precedence binding) instead of parenthesized. ``None`` (the
        default, and every non-arithmetic operator family) keeps the original
        M1 behavior: any compound operand is always parenthesized.
        """
        if isinstance(value, TemplateExpr):
            return value._as_operand(min_prec=min_prec)
        return repr(value)

    @staticmethod
    def _binop(
        left: Any, right: Any, op: str, *, prec: int | None = None, right_assoc: bool = False
    ) -> TemplateExpr:
        """Build a binary-op ``TemplateExpr``, respecting associativity.

        A same-precedence child on the operator's "loose" side (the side
        Python/Jinja fold left-to-right without needing parens) may render
        flat; a same-precedence child on the "tight" side needs its own
        precedence to be strictly *higher* to render flat, or grouping would
        silently change -- ``a - (b - c)`` is not ``a - b - c`` (which reads as
        ``(a - b) - c``). Left-associative operators (default, ``prec`` set
        and ``right_assoc=False``: ``+ - * / // %``) treat the left operand as
        loose (``min_prec=prec``) and the right as tight (``min_prec=prec+1``).
        ``**`` (``right_assoc=True``) is the mirror image: Python/Jinja fold it
        right-to-left, so the right operand is loose and the left is tight.
        """
        if prec is None:
            left_min = right_min = None
        elif right_assoc:
            left_min, right_min = prec + 1, prec
        else:
            left_min, right_min = prec, prec + 1
        rendered_left = TemplateExpr._render_operand(left, min_prec=left_min)
        rendered_right = TemplateExpr._render_operand(right, min_prec=right_min)
        return TemplateExpr(f"{rendered_left} {op} {rendered_right}", compound=True, prec=prec)

    # -- comparisons producing a new template (DESIGN §5.5 trap applies) ------
    # `eq`/`ne` are named methods, not `__eq__`/`__ne__` overrides: TemplateExpr
    # IS a str, and normal string equality/ordering (dict keys, `assert x == y`,
    # sorting, ...) must keep working everywhere else in the codebase.
    #
    # `__gt__`/`__lt__`/`__ge__`/`__le__` ARE overridden, on purpose, to return
    # a TemplateExpr rather than str's `bool` -- that is the entire point of
    # this DSL (`state(x).value > 25` must build a template, not compare two
    # strings). This is an intentional, load-bearing violation of str's typed
    # contract (typeshed declares these as `-> bool`); pyright's LSP check is
    # correctly flagging it, so it is silenced explicitly per method rather
    # than for the whole class.
    def gt(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, ">")

    def lt(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, "<")

    def ge(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, ">=")

    def le(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, "<=")

    def eq(self, other: Any) -> TemplateExpr:
        _check_comparison_operand(other, "eq")
        return TemplateExpr._binop(self, other, "==")

    def ne(self, other: Any) -> TemplateExpr:
        _check_comparison_operand(other, "ne")
        return TemplateExpr._binop(self, other, "!=")

    def in_(self, values: list[Any]) -> TemplateExpr:
        """``.in_(["a", "b"])`` -- Jinja membership (M16): ``in ['a', 'b']``.

        Renders the list literal with the same call-argument style
        ``hassle.compiler.math_expr``'s ``min_``/``max_`` use for their
        list-literal collection (``", ".join`` of each rendered operand,
        wrapped in ``[...]``) -- the canonical spacing every other DSL list
        literal in this codebase already uses.

        Polish-batch item 5: each element gets the SAME
        :func:`_check_comparison_operand` check ``.eq()``/``.ne()`` already
        apply to their single operand -- without it, a bad element (a dict, a
        custom object, ...) would silently ``repr()`` into nonsense Jinja
        inside the ``in [...]`` list, same failure mode those two methods are
        already protected against.
        """
        for value in values:
            _check_comparison_operand(value, "in_")
        rendered = ", ".join(TemplateExpr._render_operand(v, min_prec=0) for v in values)
        return TemplateExpr(f"{self._as_operand()} in [{rendered}]", compound=True)

    def __gt__(self, other: Any) -> TemplateExpr:  # type: ignore[override]
        return self.gt(other)

    def __lt__(self, other: Any) -> TemplateExpr:  # type: ignore[override]
        return self.lt(other)

    def __ge__(self, other: Any) -> TemplateExpr:  # type: ignore[override]
        return self.ge(other)

    def __le__(self, other: Any) -> TemplateExpr:  # type: ignore[override]
        return self.le(other)

    # -- arithmetic --------------------------------------------------------
    # Precedence levels (M1.1): `+`/`-` = 1, `*`/`/`/`//`/`%` = 2 -- matches
    # Python/Jinja's own binding so a chain of same-or-higher-precedence
    # operators renders flat (`a * b / c`, `a + b - c`), while a lower-
    # precedence child (`(a + b) * c`) still gets its necessary parens (its
    # tagged precedence, 1, is below the multiplication's min_prec, 2).
    _PREC_ADD = 1
    _PREC_MUL = 2

    def __add__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, "+", prec=TemplateExpr._PREC_ADD)

    def __radd__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(other, self, "+", prec=TemplateExpr._PREC_ADD)

    def __sub__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, "-", prec=TemplateExpr._PREC_ADD)

    def __rsub__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(other, self, "-", prec=TemplateExpr._PREC_ADD)

    def __mul__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, "*", prec=TemplateExpr._PREC_MUL)

    def __rmul__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(other, self, "*", prec=TemplateExpr._PREC_MUL)

    def __truediv__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, "/", prec=TemplateExpr._PREC_MUL)

    def __rtruediv__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(other, self, "/", prec=TemplateExpr._PREC_MUL)

    # -- M1.1 additions: the rest of the reflected-operator set (MILESTONES
    # M1.1 "full reflected-operator set"). Jinja supports `//`/`%`/`**` and
    # unary `-` with the same precedence as Python. ``**`` gets its own
    # (higher) level rather than joining ``_PREC_MUL`` since it binds tighter.
    def __floordiv__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, "//", prec=TemplateExpr._PREC_MUL)

    def __rfloordiv__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(other, self, "//", prec=TemplateExpr._PREC_MUL)

    def __mod__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, "%", prec=TemplateExpr._PREC_MUL)

    def __rmod__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(other, self, "%", prec=TemplateExpr._PREC_MUL)

    def __pow__(self, other: Any) -> TemplateExpr:
        # ** is right-associative in both Python and Jinja (a ** b ** c means
        # a ** (b ** c)): the RIGHT operand is the "loose" side here, the LEFT
        # is "tight" -- the mirror of +/-/*// etc. -- so (a ** b) ** c must
        # keep its parens (it is a strictly different value from a ** b ** c).
        return TemplateExpr._binop(
            self, other, "**", prec=TemplateExpr._PREC_MUL + 1, right_assoc=True
        )

    def __rpow__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(
            other, self, "**", prec=TemplateExpr._PREC_MUL + 1, right_assoc=True
        )

    def __neg__(self) -> TemplateExpr:
        return TemplateExpr(f"-{self._as_operand()}", compound=True)

    # -- boolean (Python has no overloadable `and`/`or`/`not`, so `&`/`|`/`~`
    # are the DSL spelling, same convention pandas/SQLAlchemy use) ------------
    def __and__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, "and")

    def __rand__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(other, self, "and")

    def __or__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, "or")

    def __ror__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(other, self, "or")

    def __invert__(self) -> TemplateExpr:
        rendered = self._as_operand()
        return TemplateExpr(f"not {rendered}", compound=True)

    def _as_operand(self, *, min_prec: int | None = None) -> str:
        if not self._compound:
            return self._inner
        # M1.1: a compound operand tagged with an arithmetic precedence >=
        # the caller's own precedence renders flat -- same rule Python/Jinja
        # apply for same-precedence, left-to-right binops (`a * b / c`, not
        # `(a * b) / c`). Every other case (non-arithmetic caller, or an
        # untagged/lower-precedence compound operand) keeps the original
        # always-parenthesize behavior.
        if min_prec is not None and self._prec is not None and self._prec >= min_prec:
            return self._inner
        return f"({self._inner})"

    def render_as_operand(self, *, min_prec: int | None = None) -> str:
        """Public seam for sibling builder modules (M1.1 addition, same
        convention as subclassing ``builders._NoBool``): render this
        expression as it would appear nested inside another operator/call,
        without building a whole new ``TemplateExpr``. See :func:`_as_operand`
        for the parenthesization rule ``min_prec`` controls.
        """
        return self._as_operand(min_prec=min_prec)

    # -- M1.1 trap: Python's stdlib `math`/`float()`/`int()`/`round()`/
    # `math.trunc()` on a runtime expression (MILESTONES M1.1 test 3).
    # `math.cos(x)` etc. call `float(x)` on their argument, `round(x)` calls
    # `__round__`, `math.trunc(x)` calls `__trunc__` -- all before doing
    # anything else; without this, each would either raise a bare TypeError or
    # (for other stdlib consumers) silently coerce to something meaningless.
    # `math.pi` (a plain Python float, not something that touches this class
    # at all) is unaffected -- it just folds in as a literal, which is exactly
    # the point: it is not a trap.
    def __float__(self) -> float:
        raise PythonMathMisuseError(self._branch_repr(), capture_span(depth=0))

    def __int__(self) -> int:
        raise PythonMathMisuseError(self._branch_repr(), capture_span(depth=0))

    def __round__(self, ndigits: int | None = None) -> float:
        raise PythonMathMisuseError(self._branch_repr(), capture_span(depth=0))

    def __trunc__(self) -> int:
        raise PythonMathMisuseError(self._branch_repr(), capture_span(depth=0))


def var(name: str) -> TemplateExpr:
    """``var("name")`` -- a runtime reference to an action-level ``variables:``
    key (MILESTONES M1.1 deliverables): ``{{ name }}``.

    Unlike :func:`hassle.compiler.scripts.param`, ``variables:`` keys are
    freeform (not bound to a function signature), so ``var()`` never validates
    the name against a known set -- any string is accepted. Composes with every
    operator like any other :class:`TemplateExpr` leaf.
    """
    return TemplateExpr(name)


def expr(entity: Any) -> TemplateExpr:
    """``expr(entity_ref)`` -- numeric-context template read (DESIGN §5.4).

    Equivalent to ``state(entity).value``; accepts a plain entity id string or a
    ``state(...)`` builder.
    """
    entity_id = _entity_ref_str(entity)
    return TemplateExpr(f"states({entity_id!r}) | float")


def state_of(entity: Any) -> TemplateExpr:
    """``state_of(entity_ref)`` -- bare string-context template read (M16,
    DESIGN §5.4 extension).

    Mirrors :func:`expr`'s argument handling exactly (accepts a plain entity
    id string, an ``e.``-registry ref, or a ``state(...)`` builder built from
    one entity), but renders the bare ``states('x')`` call with no ``| float``
    filter -- a string-state read, not a numeric one. Compose with
    ``.eq()``/``.ne()``/``.in_([...])`` for string comparisons/membership, and
    ``&``/``|``/``~`` for boolean composition, exactly like any other
    :class:`TemplateExpr`.
    """
    entity_id = _entity_ref_str(entity)
    return TemplateExpr(f"states({entity_id!r})")


def template(raw: str) -> TemplateExpr:
    """Raw Jinja passthrough (DESIGN §5.4): ``template("{{ ... }}")``.

    Strips one layer of ``{{ }}`` if present (so the stored inner text matches
    any other ``TemplateExpr``, and re-wrapping via
    :meth:`TemplateExpr.to_template` reproduces the input verbatim); otherwise
    the given text is used as-is as the inner expression.
    """
    text = raw.strip()
    is_wrapped = text.startswith("{{") and text.endswith("}}")
    inner = text[2:-2].strip() if is_wrapped else text
    return TemplateExpr(inner, compound=True)


def _state_value(state_expr: StateExpr) -> TemplateExpr:
    """Implements ``state(x).value`` -- see the deviation note above."""
    entity_id = _entity_ref_str(state_expr)
    return TemplateExpr(f"states({entity_id!r}) | float")


# `.value` on the existing StateExpr type: builders.py is frozen for this
# workstream and does not define `.value`, so it is attached here as a
# read-only property -- an additive attribute, never touching builders.py's
# source (see the deviation note above and docs/ha-api-notes.md).
StateExpr.value = property(_state_value)  # type: ignore[attr-defined]
