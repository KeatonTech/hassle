"""Shared builder conventions every dashboard builder is written against (§5.3).

Two helpers, deliberately ONE implementation each, so the structural verbs here
and DB3's ~35 card builders cannot drift apart:

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
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from hassle.compiler.dashboards.conditions import (
    DashboardConditionLike,
    normalize_condition,
)
from hassle.compiler.dashboards.errors import ExtraShadowsKwargError
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
