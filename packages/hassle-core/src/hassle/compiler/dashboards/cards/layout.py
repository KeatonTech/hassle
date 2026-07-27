"""Layout & container cards (``hassle.cards``) — DB3a's container batch.

docs/internals/dashboards-design.md §5.3 (builder conventions) / §6.1.1 (F5,
the frozen card-builder protocol). Five container cards, each a
``@contextlib.contextmanager`` generator built on the F5 ``push_container``
seam:

- :func:`vertical_stack` / :func:`horizontal_stack` / :func:`grid` — an
  ordinary ``cards:`` list container, any number of children.
- :func:`conditional` — EXACTLY one child card under a ``card:`` key
  (:class:`~hassle.compiler.dashboards.errors.ConditionalCardArityError` on any
  other count).
- :func:`entity_filter` — ZERO or ONE child card under a ``card:`` key (the
  presentation card its filtered entities render through).

``grid`` deliberately shares its stored ``type`` string (``"grid"``) with
``STRUCTURE_REGISTRY["structure:section"]`` (DB2's ``section()``) — §6.1.1's
grid-vs-section disambiguation is POSITIONAL, not a naming concern of this
module: a ``grid`` card in a view's ``sections`` list is a section, one in
another card's ``cards`` list is this ``c.grid``. The two registries stay
separate tables, so this module never touches ``STRUCTURE_REGISTRY``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Generator, Iterable, Mapping
from typing import Any

from hassle.compiler.dashboards.builders import (
    VisibilityArg,
    merge_extra,
    normalize_rows,
    normalize_visibility,
    put,
    put_copy,
)
from hassle.compiler.dashboards.card_registry import CardSpec, register_card
from hassle.compiler.dashboards.conditions import DashboardConditionLike, normalize_condition
from hassle.compiler.dashboards.errors import ConditionalCardArityError
from hassle.compiler.dashboards.recorder import (
    _CM_DEPTH,  # pyright: ignore[reportPrivateUsage]
    RecordedNode,
    push_container,
)
from hassle.compiler.spans import capture_span

#: Every declared `vertical_stack()` keyword — what `extra=` may not shadow.
_STACK_DECLARED: frozenset[str] = frozenset({"type", "title", "visibility", "cards"})
#: `horizontal_stack()` has no `title` option — HA's horizontal-stack card
#: does not support one (unlike `vertical-stack`).
_HSTACK_DECLARED: frozenset[str] = frozenset({"type", "visibility", "cards"})
_GRID_DECLARED: frozenset[str] = frozenset(
    {"type", "columns", "square", "title", "visibility", "cards"}
)
_CONDITIONAL_DECLARED: frozenset[str] = frozenset({"type", "conditions", "visibility", "card"})
_ENTITY_FILTER_DECLARED: frozenset[str] = frozenset(
    {"type", "entities", "state_filter", "show_empty", "visibility", "card"}
)


@contextlib.contextmanager
def vertical_stack(
    *,
    title: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Generator[None]:
    """``with c.vertical_stack(...):`` — stacks its children top to bottom."""
    span = capture_span(depth=_CM_DEPTH)
    body: dict[str, Any] = {"type": "vertical-stack"}
    put(body, "title", title)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.vertical_stack", declared=_STACK_DECLARED, span=span)
    with push_container(body, label="a `vertical-stack` card", span=span):
        yield


@contextlib.contextmanager
def horizontal_stack(
    *,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Generator[None]:
    """``with c.horizontal_stack():`` — lays out its children left to right."""
    span = capture_span(depth=_CM_DEPTH)
    body: dict[str, Any] = {"type": "horizontal-stack"}
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.horizontal_stack", declared=_HSTACK_DECLARED, span=span)
    with push_container(body, label="a `horizontal-stack` card", span=span):
        yield


@contextlib.contextmanager
def grid(
    *,
    columns: Any = None,
    square: Any = None,
    title: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Generator[None]:
    """``with c.grid(columns=..., square=...):`` — a `cards`-list grid card.

    NOT the same DSL construct as a sections-view `section()` (§6.1.1): both
    store `{"type": "grid", ...}`, but POSITION disambiguates — a `grid` inside
    a view's `sections` list is `with section():`; one inside another card's
    `cards` list (or a view's flat `cards` list) is `with c.grid(...):`.
    """
    span = capture_span(depth=_CM_DEPTH)
    body: dict[str, Any] = {"type": "grid"}
    put(body, "columns", columns)
    put(body, "square", square)
    put(body, "title", title)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.grid", declared=_GRID_DECLARED, span=span)
    with push_container(body, label="a `grid` card", span=span):
        yield


@contextlib.contextmanager
def conditional(
    *conditions: DashboardConditionLike,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Generator[None]:
    """``with c.conditional(cond.state(...)):`` — shows one card conditionally.

    Takes its Lovelace `cond.*` conditions as positional varargs (mirroring
    `cond.any`/`cond.all`, §5.4). Must wrap EXACTLY one child card — HA's
    conditional card has a single `card:` key, not a list — so recording zero
    or more than one raises `ConditionalCardArityError` (§5.6); nest a stack
    card (`with c.vertical_stack():`) to hold more than one.

    ``child_is_list=False`` (review-round fix SF-2) is what gives the nested
    card a bare `…cards[0].card` span path instead of an unresolvable
    `…cards[0].card[0]`. `push_container` itself raises `ValueError` for more
    than one child recorded into a single-child slot; the `try`/`except`
    below turns that into this builder's own `ConditionalCardArityError` (the
    "zero" case is checked directly afterwards, since `push_container` only
    objects to MORE than one).
    """
    span = capture_span(depth=_CM_DEPTH)
    body: dict[str, Any] = {"type": "conditional"}
    body["conditions"] = [normalize_condition(c, span=span) for c in conditions]
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.conditional", declared=_CONDITIONAL_DECLARED, span=span)
    node: RecordedNode | None = None
    try:
        with push_container(
            body, label="a `conditional` card", span=span, child_key="card", child_is_list=False
        ) as node:
            yield
    except ValueError:
        count = len(node.children) if node is not None else 0
        raise ConditionalCardArityError("c.conditional(...)", count, "exactly one", span) from None
    if len(node.children) != 1:
        raise ConditionalCardArityError(
            "c.conditional(...)", len(node.children), "exactly one", span
        )


@contextlib.contextmanager
def entity_filter(
    *,
    entities: Iterable[Any],
    state_filter: Any = None,
    show_empty: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Generator[None]:
    """``with c.entity_filter(entities=[...]):`` — filters entities through a presentation card.

    Holds ZERO or ONE child card (§5.2) — the card its filtered entities render
    through; recording more than one raises `ConditionalCardArityError` (the
    same "how many cards in this `card:` slot" question `c.conditional` asks,
    just with `"zero or one"` instead of `"exactly one"`). HA falls back to a
    bare entity list when the `card:` key is entirely absent, which is exactly
    what an empty block produces -- `push_container`'s own `child_is_list=False`
    handling now leaves the key absent for zero children and fills it in for
    one, so this builder no longer assigns `body["card"]` itself.
    """
    span = capture_span(depth=_CM_DEPTH)
    body: dict[str, Any] = {"type": "entity-filter"}
    body["entities"] = normalize_rows(
        entities, builder="c.entity_filter", param="entities", span=span
    )
    put_copy(body, "state_filter", state_filter)
    put(body, "show_empty", show_empty)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.entity_filter", declared=_ENTITY_FILTER_DECLARED, span=span)
    node: RecordedNode | None = None
    try:
        with push_container(
            body,
            label="an `entity-filter` card",
            span=span,
            child_key="card",
            child_is_list=False,
        ) as node:
            yield
    except ValueError:
        count = len(node.children) if node is not None else 0
        raise ConditionalCardArityError(
            "c.entity_filter(...)", count, "zero or one", span
        ) from None


# ---------------------------------------------------------------------------
# F5 registration (card_registry.py) — one append-only row per builder.
# ---------------------------------------------------------------------------
register_card(
    CardSpec(
        type="vertical-stack",
        declared=frozenset({"type", "title", "visibility", "cards"}),
        builder="c.vertical_stack",
        container="cards",
        context_manager=True,
    )
)
register_card(
    CardSpec(
        type="horizontal-stack",
        declared=frozenset({"type", "visibility", "cards"}),
        builder="c.horizontal_stack",
        container="cards",
        context_manager=True,
    )
)
register_card(
    CardSpec(
        type="grid",
        declared=frozenset({"type", "columns", "square", "title", "visibility", "cards"}),
        builder="c.grid",
        container="cards",
        context_manager=True,
    )
)
register_card(
    CardSpec(
        type="conditional",
        declared=frozenset({"type", "conditions", "visibility", "card"}),
        builder="c.conditional",
        container="card",
        context_manager=True,
    )
)
register_card(
    CardSpec(
        type="entity-filter",
        declared=frozenset(
            {"type", "entities", "state_filter", "show_empty", "visibility", "card"}
        ),
        builder="c.entity_filter",
        entity_params=("entities",),
        container="card",
        context_manager=True,
    )
)
