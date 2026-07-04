"""Template expression builder: operator overloading -> Jinja strings (DESIGN §5.4).

``state(x).value`` / ``expr(x)`` wrap an entity reference in a numeric-context
Jinja read (``states('x') | float``); comparisons, arithmetic, and boolean
operators on those build up a nested Jinja expression string. ``template(...)``
is the raw-Jinja passthrough (validated later by tier-3 lint, §9 -- out of
scope here).

This is a **sibling builder module** (docs/m1-internal-api.md's "may you edit"
column): it does not modify ``hassle_core.compiler.builders``. It reuses the
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
| ``a > b`` / ``a < b`` | ``a > b`` / ``a < b`` | also ``>=``/``<=`` |
| ``a == b`` / ``a != b`` | ``a == b`` / ``a != b`` | via ``.eq()``/``.ne()`` |
| ``a + b`` / ``a - b`` | ``a + b`` / ``a - b`` | also ``*``/``/`` |
| ``a & b`` | ``a and b`` | boolean and |
| ``a \\| b`` | ``a or b`` | boolean or |
| ``~a`` | ``not a`` (``not (a)`` if compound) | boolean not |
| ``template("{{ ... }}")`` | ``{{ ... }}`` verbatim | raw passthrough |

Note on ``==``/``!=``: ``TemplateExpr`` is a ``str`` subclass, and Python/pytest
rely on plain ``==`` for equality and container membership everywhere (dict
keys, ``assert a == b``, ...). Overriding ``__eq__`` to build a template would
break that silently. So ``==``/``!=`` keep their normal string-equality meaning;
the Jinja comparison is spelled ``.eq(other)`` / ``.ne(other)`` instead.
"""

from __future__ import annotations

from typing import Any

# `_NoBool` is private to builders.py, but docs/m1-internal-api.md §5
# explicitly sanctions subclassing it for the `__bool__` trap ("subclass
# `builders._NoBool`, override `_branch_repr`"): pyright's cross-module
# private-access check is silenced here for that one documented reason.
from hassle_core.compiler.builders import StateExpr, _NoBool  # pyright: ignore[reportPrivateUsage]

# `.value` reads the entity id through StateExpr's public `entity_id` accessor
# (added in the M1 integration pass; the earlier private-`_entity_id` coupling
# is gone). `.value` itself is attached to StateExpr as an additive property
# from this sibling module (see the bottom of this file) — a purely additive
# extension, not a rewrite of builders.py.


def _entity_ref_str(value: Any) -> str:
    """Coerce an entity reference (a plain entity_id string, or a StateExpr) to
    its ``domain.object_id`` string."""
    if isinstance(value, StateExpr):
        return value.entity_id
    if isinstance(value, str):
        return value
    raise TypeError(
        f"expr()/state(...).value expects an entity id string or a state(...) "
        f"builder, got {value!r} ({type(value).__name__})"
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

    def __new__(cls, inner: str, *, compound: bool = False) -> TemplateExpr:
        obj = str.__new__(cls, f"{{{{ {inner} }}}}")
        obj._inner = inner
        # `compound` marks "the result of a previous operator" so a later
        # operator knows to parenthesize this expression when nesting it.
        obj._compound = compound
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
    def _render_operand(value: Any) -> str:
        """Render one operand: a compound TemplateExpr in parens, a simple
        TemplateExpr or Python literal bare (matches the DESIGN §5.4 examples,
        which have no redundant parens around a plain comparison/subtraction)."""
        if isinstance(value, TemplateExpr):
            return value._as_operand()
        return repr(value)

    @staticmethod
    def _binop(left: Any, right: Any, op: str) -> TemplateExpr:
        rendered_left = TemplateExpr._render_operand(left)
        rendered_right = TemplateExpr._render_operand(right)
        return TemplateExpr(f"{rendered_left} {op} {rendered_right}", compound=True)

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
        return TemplateExpr._binop(self, other, "==")

    def ne(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, "!=")

    def __gt__(self, other: Any) -> TemplateExpr:  # type: ignore[override]
        return self.gt(other)

    def __lt__(self, other: Any) -> TemplateExpr:  # type: ignore[override]
        return self.lt(other)

    def __ge__(self, other: Any) -> TemplateExpr:  # type: ignore[override]
        return self.ge(other)

    def __le__(self, other: Any) -> TemplateExpr:  # type: ignore[override]
        return self.le(other)

    # -- arithmetic ------------------------------------------------------------
    def __add__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, "+")

    def __radd__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(other, self, "+")

    def __sub__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, "-")

    def __rsub__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(other, self, "-")

    def __mul__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, "*")

    def __rmul__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(other, self, "*")

    def __truediv__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(self, other, "/")

    def __rtruediv__(self, other: Any) -> TemplateExpr:
        return TemplateExpr._binop(other, self, "/")

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

    def _as_operand(self) -> str:
        return f"({self._inner})" if self._compound else self._inner


def expr(entity: Any) -> TemplateExpr:
    """``expr(entity_ref)`` -- numeric-context template read (DESIGN §5.4).

    Equivalent to ``state(entity).value``; accepts a plain entity id string or a
    ``state(...)`` builder.
    """
    entity_id = _entity_ref_str(entity)
    return TemplateExpr(f"states({entity_id!r}) | float")


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
