"""``cond`` — the Lovelace condition vocabulary (§5.4).

Lovelace visibility/conditional conditions are a **different schema** from
automation conditions: ``entity``/``state``/``state_not`` keys instead of
``entity_id``/``condition`` shapes, plus the two UI-only kinds ``screen`` and
``user``. Mapping one onto the other would compile a condition HA stores and
then never evaluates, so they get their own small vocabulary and the confusion
is trap-caught in BOTH directions (the ``CompileTimeBranchError`` tradition):

- an automation ``ConditionBuilder`` passed to ``visibility=`` /
  ``c.conditional(...)`` raises
  :class:`~hassle.compiler.dashboards.errors.DashboardConditionTypeError`,
  naming the ``cond.*`` equivalent;
- a ``cond.*`` object passed to ``only_if``/``if_then``/``all_of``/… raises the
  mirror,
  :class:`~hassle.compiler.dashboards.errors.DashboardConditionInAutomationError`.
  The mirror is implemented by giving every ``cond.*`` object a
  ``to_condition()`` that raises -- that is the one method every automation
  condition entry point calls, so all of them are covered without any of them
  knowing dashboards exist.

A verbatim ``dict`` is accepted anywhere a condition is, so a condition kind
Hassle does not model yet round-trips raw (I3).
"""

from __future__ import annotations

from typing import Any, Protocol, cast, runtime_checkable

from hassle.compiler.dashboards.errors import (
    DashboardConditionInAutomationError,
    DashboardConditionTypeError,
)
from hassle.compiler.spans import SourceSpan, capture_span


@runtime_checkable
class DashboardCondition(Protocol):
    """Anything that serializes itself as a Lovelace condition mapping.

    The dashboard sibling of
    :class:`~hassle.compiler.protocols.ConditionBuilder`; DB3's conditional-card
    builder and every ``visibility=`` parameter accept it.
    """

    def to_dashboard_condition(self) -> dict[str, Any]: ...


#: What every condition-accepting dashboard parameter takes.
DashboardConditionLike = DashboardCondition | dict[str, Any]


class _Cond:
    """One Lovelace condition, built by the ``cond.*`` vocabulary."""

    def __init__(self, body: dict[str, Any], repr_: str) -> None:
        self._body = body
        self._repr = repr_

    def to_dashboard_condition(self) -> dict[str, Any]:
        return dict(self._body)

    def to_condition(self) -> dict[str, Any]:
        """The §5.4 mirror trap -- never a real automation condition.

        Every automation condition entry point (``only_if``, ``if_then``,
        ``else_if``, ``choose().when_``, ``repeat_while``/``repeat_until``,
        ``all_of``/``any_of``/``not_``) funnels through this one method, so
        raising here covers all of them without any of them importing anything
        dashboard-shaped.
        """
        raise DashboardConditionInAutomationError(f"`{self._repr}`", capture_span(depth=0))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return self._repr


def _entity_id(entity: Any) -> str:
    """An entity-position argument as HA stores it (``EntityRef`` is a ``str``)."""
    return str(entity)


def normalize_condition(value: Any, *, span: SourceSpan | None) -> dict[str, Any]:
    """One condition (``cond.*`` object or verbatim dict) as its stored mapping.

    The single entry point every dashboard condition slot uses -- ``visibility=``
    here, and DB3's ``c.conditional(*conditions)``.
    """
    if isinstance(value, dict):
        return dict(cast("dict[str, Any]", value))
    to_dashboard = getattr(value, "to_dashboard_condition", None)
    if callable(to_dashboard):
        body: Any = to_dashboard()
        if isinstance(body, dict):
            return dict(cast("dict[str, Any]", body))
    raise DashboardConditionTypeError(_describe(value), _suggest(value), span)


def _describe(value: Any) -> str:
    """A stable, snapshot-safe description of the offending value.

    Never ``repr()`` a builder object: most of them inherit the default
    ``<... object at 0x...>``, whose address would make the error snapshot
    non-deterministic (R8). The class name is the stable, useful part.
    """
    if hasattr(value, "to_condition") or hasattr(value, "to_trigger"):
        return f"An automation condition builder (`{type(value).__name__}`)"
    return f"`{value!r}` (a {type(value).__name__})"


_SUGGESTIONS: dict[str, str] = {
    "state": 'cond.state(entity, "on")',
    "numeric_state": "cond.numeric(entity, above=25, below=30)",
    "and": "cond.all(...)",
    "or": "cond.any(...)",
    "not": "cond.not_(...)",
}


def _suggest(value: Any) -> str:
    """Best-effort ``cond.*`` spelling for the automation condition passed by mistake.

    Reads the built condition's own discriminator when the object will produce
    one; anything that refuses (a bare value, a builder that raises) falls back
    to the most common form. Never lets a diagnostic helper turn into a second
    failure.
    """
    to_condition = getattr(value, "to_condition", None)
    if callable(to_condition):
        try:
            body = to_condition()
        except Exception:
            return _SUGGESTIONS["state"]
        if isinstance(body, dict):
            kind: Any = cast("dict[str, Any]", body).get("condition")
            if isinstance(kind, str) and kind in _SUGGESTIONS:
                return _SUGGESTIONS[kind]
    return _SUGGESTIONS["state"]


class _CondNamespace:
    """``cond`` -- the Lovelace condition builders (``from hassle.cards import cond``)."""

    @staticmethod
    def state(entity: Any, value: Any = None, *, not_: Any = None) -> _Cond:
        """``{"condition": "state", "entity": ..., "state"|"state_not": ...}``.

        ``cond.state(x, "on")`` is the positive form, ``cond.state(x,
        not_="off")`` the negative one. Both may be given (HA accepts a state
        condition carrying both keys) and both may be omitted -- the builder
        emits exactly what it was told, never a materialized default.
        """
        body: dict[str, Any] = {"condition": "state", "entity": _entity_id(entity)}
        if value is not None:
            body["state"] = value
        if not_ is not None:
            body["state_not"] = not_
        return _Cond(body, f"cond.state({entity!r}, {value!r})")

    @staticmethod
    def numeric(entity: Any, *, above: Any = None, below: Any = None) -> _Cond:
        """``{"condition": "numeric_state", "entity": ..., "above": ..., "below": ...}``."""
        body: dict[str, Any] = {"condition": "numeric_state", "entity": _entity_id(entity)}
        if above is not None:
            body["above"] = above
        if below is not None:
            body["below"] = below
        return _Cond(body, f"cond.numeric({entity!r})")

    @staticmethod
    def screen(media_query: str) -> _Cond:
        """``{"condition": "screen", "media_query": ...}`` -- a UI-only kind."""
        return _Cond(
            {"condition": "screen", "media_query": media_query},
            f"cond.screen({media_query!r})",
        )

    @staticmethod
    def user(*user_ids: str) -> _Cond:
        """``{"condition": "user", "users": [...]}`` -- a UI-only kind.

        User ids are HA's opaque per-user hex ids; the registry snapshot does
        not contain users, so they are validated for shape only (§8).
        """
        return _Cond(
            {"condition": "user", "users": [str(u) for u in user_ids]},
            f"cond.user({', '.join(repr(u) for u in user_ids)})",
        )

    @staticmethod
    def any(*conditions: DashboardConditionLike) -> _Cond:
        """``{"condition": "or", "conditions": [...]}``."""
        return _Cond(_combine("or", conditions), "cond.any(...)")

    @staticmethod
    def all(*conditions: DashboardConditionLike) -> _Cond:
        """``{"condition": "and", "conditions": [...]}``."""
        return _Cond(_combine("and", conditions), "cond.all(...)")

    @staticmethod
    def not_(*conditions: DashboardConditionLike) -> _Cond:
        """``{"condition": "not", "conditions": [...]}``.

        Varargs (rather than one condition) to mirror ``hassle.not_`` exactly;
        the stored shape is a ``conditions`` list either way.
        """
        return _Cond(_combine("not", conditions), "cond.not_(...)")


def _combine(keyword: str, conditions: tuple[DashboardConditionLike, ...]) -> dict[str, Any]:
    span = capture_span(depth=1)
    return {
        "condition": keyword,
        "conditions": [normalize_condition(c, span=span) for c in conditions],
    }


#: The public namespace object (`from hassle.cards import cond`).
cond = _CondNamespace()
