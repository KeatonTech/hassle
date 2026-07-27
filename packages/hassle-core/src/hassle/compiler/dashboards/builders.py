"""Shared builder conventions every dashboard builder is written against (§5.3).

Four helpers, deliberately ONE implementation each, so the structural verbs
here and DB3's 47 card builders cannot drift apart:

- :func:`merge_extra` -- the ``extra: dict | None = None`` verbatim-passthrough
  valve plus its shadow check. Every builder takes ``extra=``: when HA adds a
  card option Hassle does not model yet, the decompiler emits the typed builder
  call PLUS ``extra={...}`` instead of collapsing the whole card to
  ``raw_card``, and an author can use a brand-new option the day HA ships it. A
  typo'd kwarg stays a loud ``TypeError`` (builders never take ``**kwargs``),
  and an ``extra`` key may not shadow a declared kwarg, so every option has
  exactly one spelling.
- :func:`normalize_visibility` -- the ``visibility=`` normalizer, which accepts
  ``cond.*`` objects and verbatim dicts (and traps an automation condition
  builder, §5.4).
- :func:`put_copy` -- like :func:`put`, but DEEP-COPIES a ``dict``/``list``
  value first (the review-round copy-vs-alias fix, SF-3): a bundle is
  re-compiled from scratch on every run, but WITHIN one compile an author-
  supplied option dict/list must never alias into the compiled card body --
  two builder calls sharing one Python dict/list (a common pattern: build the
  options once, pass them to several cards) must stay independent, and
  mutating the author's dict after the call must never reach back into
  already-compiled IR. Every dict/list-valued typed keyword option across
  ``cards/layout.py``/``display.py``/``visual.py``/``media.py`` uses this
  instead of :func:`put` -- the uniform posture the review round asked for
  (picking ONE rule rather than copying in some builders and aliasing in
  others). ``extra=`` keeps its own separate, already-documented reference
  semantics (:func:`merge_extra`) -- unaffected by this fix.
- :func:`normalize_rows` -- the ``entities``-shaped-row convention (§5.3), the
  ONE implementation shared by every row-taking builder (``c.entities``,
  ``c.glance``, ``c.entity_filter``, ``c.heading``'s ``badges=``,
  ``c.history_graph``/``c.statistics_graph``/``c.calendar``/``c.logbook``/
  ``c.map``/``c.picture_glance``'s ``*entities`` varargs) instead of three
  near-identical per-module copies. Also the SF-4 fix: a bare `str`/`EntityRef`
  passed where a LIST of rows was expected, or a row that is not
  `str`/`EntityRef`/`dict`, used to compile clean into garbage (a live bug,
  not a hypothetical) -- both now raise
  :class:`~hassle.compiler.dashboards.errors.EntityRowTypeError` (what/where/
  fix, snapshot-tested).
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable, Mapping
from typing import Any, cast

from hassle.compiler.dashboards.conditions import (
    DashboardConditionLike,
    normalize_condition,
)
from hassle.compiler.dashboards.errors import EntityRowTypeError, ExtraShadowsKwargError
from hassle.compiler.spans import SourceSpan

#: What `visibility=` accepts: one condition or an iterable of them, where a
#: "condition" is a `cond.*` object or a verbatim dict.
VisibilityArg = DashboardConditionLike | Iterable[DashboardConditionLike]


def put(body: dict[str, Any], key: str, value: Any) -> None:
    """Set ``body[key]`` unless ``value`` is ``None`` (the "option omitted" marker).

    The single rule every builder uses to decide whether an option key reaches
    the stored config: Hassle never materializes a default HA did not ask for
    (that would break ``compile(decompile(x)) == x``).
    """
    if value is not None:
        body[key] = value


def put_copy(body: dict[str, Any], key: str, value: Any) -> None:
    """Like :func:`put`, but a ``dict``/``list`` value is deep-copied first.

    Use this instead of :func:`put` for every option whose value CAN be a
    ``dict``/``list`` (``severity=``, ``limits=``, ``period=``, ``features=``,
    ``state_content=``, ``elements=``, ``state_filter=``, ``tap_action=``/
    ``hold_action=``/``double_tap_action=``, …) -- a plain scalar (``str``/
    ``int``/``bool``/``None``) passes through unchanged, so it is always safe
    to reach for this over :func:`put` when in doubt.
    """
    if isinstance(value, dict):
        value = copy.deepcopy(cast("dict[str, Any]", value))
    elif isinstance(value, list):
        value = copy.deepcopy(cast("list[Any]", value))
    put(body, key, value)


def normalize_rows(
    rows: Any,
    *,
    builder: str,
    param: str,
    span: SourceSpan | None,
    row_factory: Callable[[str], Any] | None = None,
) -> list[Any]:
    """Normalize an `entities`-shaped-row argument to HA's stored row list.

    ``rows`` is either a varargs tuple (``c.entities(*rows)``) or a single
    list/iterable value (``c.entity_filter(entities=[...])``,
    ``c.heading(badges=[...])``); either way each item is a bare entity id
    (``str``/``EntityRef``) or a ``dict`` (a per-row option object, or a
    special row like ``{"type": "divider"}``, kept verbatim and deep-copied so
    a caller-owned dict can never alias into the compiled card).

    ``row_factory`` lets a bare-string row build something other than the row
    string itself -- ``c.heading(badges=...)`` turns a bare entity id into the
    object-badge form ``{"type": "entity", "entity": ...}``, mirroring
    ``structure.badge()``'s own rule, while every other row-taking builder
    leaves it ``None`` and keeps the string as-is.

    Two failure modes, both real bugs that used to compile clean into garbage
    (SF-4, a review-round finding) rather than raise
    :class:`~hassle.compiler.dashboards.errors.EntityRowTypeError`:

    - ``rows`` itself is a bare ``str``/``bytes`` (or anything non-iterable) --
      Python happily iterates a string character by character, so
      ``entity_filter(entities="light.hall")`` used to silently become ten
      one-character rows;
    - a row that is neither ``str``/``EntityRef`` nor ``dict`` (e.g. a `list`
      passed as one row because the caller forgot to unpack) -- it used to
      ``str()``-stringify into a single nonsense row instead of failing loudly.
    """
    if isinstance(rows, (str, bytes)):
        raise EntityRowTypeError("bare_string", builder, param, rows, span)
    try:
        iterator = iter(rows)  # pyright: ignore[reportUnknownArgumentType]
    except TypeError as exc:
        raise EntityRowTypeError("bare_string", builder, param, rows, span) from exc
    out: list[Any] = []
    for row in iterator:
        if isinstance(row, dict):
            out.append(copy.deepcopy(cast("dict[str, Any]", row)))
        elif isinstance(row, str):
            out.append(row_factory(row) if row_factory is not None else str(row))
        else:
            raise EntityRowTypeError("bad_row", builder, param, row, span)
    return out


def merge_extra(
    body: dict[str, Any],
    extra: Mapping[str, Any] | None,
    *,
    builder: str,
    declared: Iterable[str],
    span: SourceSpan | None,
) -> dict[str, Any]:
    """Merge ``extra`` into ``body`` verbatim, rejecting shadowed kwargs.

    ``declared`` is the builder's OWN keyword names -- all of them, not just the
    ones that were passed: ``view(extra={"path": "x"})`` is rejected even though
    ``path=`` was omitted, because there must be exactly one spelling of every
    modelled option (otherwise the decompiler could emit either and byte
    stability is gone). Values are stored by reference, exactly as given; the
    caller is responsible for having copied anything author-owned.
    """
    if not extra:
        return body
    declared_set = frozenset(declared)
    for key in extra:
        if key in declared_set:
            raise ExtraShadowsKwargError(builder, key, span)
    body.update(extra)
    return body


def normalize_visibility(
    visibility: VisibilityArg | None, *, span: SourceSpan | None
) -> list[dict[str, Any]] | None:
    """Normalize a ``visibility=`` argument to HA's stored list-of-conditions.

    Accepts a single condition or any iterable of them; each item is a ``cond.*``
    object or a verbatim ``dict`` (so unknown future condition kinds round-trip
    raw). An automation condition builder raises
    :class:`~hassle.compiler.dashboards.errors.DashboardConditionTypeError`
    naming its ``cond.*`` equivalent. Returns ``None`` when nothing was passed,
    so the key is simply absent from the stored body.
    """
    if visibility is None:
        return None
    items: list[Any]
    if isinstance(visibility, dict) or hasattr(visibility, "to_dashboard_condition"):
        items = [visibility]
    elif isinstance(visibility, Iterable):
        items = list(visibility)  # pyright: ignore[reportUnknownArgumentType]
    else:
        items = [visibility]
    return [normalize_condition(item, span=span) for item in items]
