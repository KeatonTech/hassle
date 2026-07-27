"""Display leaf cards (``hassle.cards``) — DB3a's leaf batch.

docs/internals/dashboards-design.md §5.3 (builder conventions) / §6.1.1 (F5).
Six plain-function leaf builders:

- :func:`entities` / :func:`glance` — rows as POSITIONAL VARARGS
  (`EntityRef | str | dict`), the `entities`-shaped-card convention (§5.3): a
  bare entity id is stored as HA's shorthand string, a `dict` (a per-row
  override or a special row like `{"type": "divider"}`) passes through
  verbatim.
- :func:`tile` / :func:`entity` / :func:`button` — one `entity=` (a `str`
  subclass and reference type both accepted, per the entity-taking-parameter
  convention).
- :func:`heading` — a section/view heading with a `badges=` list.

Every builder is a plain function (span at `depth=0`, no `push_container` —
leaf cards have no children) and shares the `extra=`/`visibility=` contract
via `merge_extra`/`normalize_visibility` (`builders.py`).

**tap_action/hold_action/double_tap_action/icon_tap_action** (§5.3): these are
passthrough-in-v1 — Hassle does not model the Lovelace action-config
sub-vocabulary yet, so a typed parameter simply takes a verbatim `dict`
("dict passthrough"). `tile` deliberately declares `tap_action=`/`hold_action=`/
`double_tap_action=` as typed dict-passthrough kwargs but leaves
`icon_tap_action` UNDECLARED, so it can only reach the stored card through
`extra=` — a concrete example of the two forward-compatibility mechanisms
(§5.3's two "forms") coexisting on one card: a typed kwarg that merely widens
to `dict`, and the `extra=` valve for an option Hassle has not modelled at all.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, cast

from hassle.compiler.dashboards.builders import (
    VisibilityArg,
    merge_extra,
    normalize_visibility,
    put,
)
from hassle.compiler.dashboards.card_registry import CardSpec, register_card
from hassle.compiler.dashboards.recorder import record_card
from hassle.compiler.spans import capture_span

_ENTITIES_DECLARED: frozenset[str] = frozenset(
    {
        "type",
        "entities",
        "title",
        "show_header_toggle",
        "state_color",
        "icon",
        "theme",
        "visibility",
    }
)
_GLANCE_DECLARED: frozenset[str] = frozenset(
    {
        "type",
        "entities",
        "title",
        "show_name",
        "show_icon",
        "show_state",
        "state_color",
        "columns",
        "theme",
        "visibility",
    }
)
_TILE_DECLARED: frozenset[str] = frozenset(
    {
        "type",
        "entity",
        "name",
        "icon",
        "color",
        "show_entity_picture",
        "vertical",
        "features",
        "features_position",
        "state_content",
        "tap_action",
        "hold_action",
        "double_tap_action",
        "visibility",
    }
)
_ENTITY_DECLARED: frozenset[str] = frozenset(
    {
        "type",
        "entity",
        "attribute",
        "name",
        "icon",
        "unit",
        "state_color",
        "format",
        "tap_action",
        "hold_action",
        "double_tap_action",
        "visibility",
    }
)
_BUTTON_DECLARED: frozenset[str] = frozenset(
    {
        "type",
        "entity",
        "name",
        "icon",
        "icon_height",
        "show_name",
        "show_icon",
        "show_state",
        "state_color",
        "theme",
        "tap_action",
        "hold_action",
        "double_tap_action",
        "visibility",
    }
)
_HEADING_DECLARED: frozenset[str] = frozenset(
    {"type", "heading", "heading_style", "icon", "badges", "tap_action", "visibility"}
)


def _normalize_row(row: Any) -> Any:
    """One `entities`/`glance` row: `dict` passthrough (copied), else the bare
    entity-id string HA's shorthand form accepts."""
    if isinstance(row, dict):
        return dict(cast("dict[str, Any]", row))
    return str(row)


def _normalize_badge(item: Any) -> Any:
    """One `heading(badges=...)` item — mirrors `structure.badge()`'s own rule:
    a bare entity id builds the object form, a `dict` passes through verbatim."""
    if isinstance(item, dict):
        return dict(cast("dict[str, Any]", item))
    return {"type": "entity", "entity": str(item)}


def entities(
    *rows: Any,
    title: Any = None,
    show_header_toggle: Any = None,
    state_color: Any = None,
    icon: Any = None,
    theme: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.entities(e.light.a, {"type": "divider"}, e.light.b, title=...)``.

    Rows are positional varargs (§5.3): `EntityRef | str` (stored as HA's bare
    entity-id shorthand) or `dict` (a per-row override or a special row like
    `{"type": "divider"}`, passthrough in v1).
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "entities"}
    body["entities"] = [_normalize_row(row) for row in rows]
    put(body, "title", title)
    put(body, "show_header_toggle", show_header_toggle)
    put(body, "state_color", state_color)
    put(body, "icon", icon)
    put(body, "theme", theme)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.entities", declared=_ENTITIES_DECLARED, span=span)
    record_card(body, span=span, what="`c.entities()`")


def glance(
    *rows: Any,
    title: Any = None,
    show_name: Any = None,
    show_icon: Any = None,
    show_state: Any = None,
    state_color: Any = None,
    columns: Any = None,
    theme: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.glance(e.light.a, e.light.b, title=...)`` — the same rows convention as `c.entities`."""
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "glance"}
    body["entities"] = [_normalize_row(row) for row in rows]
    put(body, "title", title)
    put(body, "show_name", show_name)
    put(body, "show_icon", show_icon)
    put(body, "show_state", show_state)
    put(body, "state_color", state_color)
    put(body, "columns", columns)
    put(body, "theme", theme)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.glance", declared=_GLANCE_DECLARED, span=span)
    record_card(body, span=span, what="`c.glance()`")


def tile(
    entity: Any,
    *,
    name: Any = None,
    icon: Any = None,
    color: Any = None,
    show_entity_picture: Any = None,
    vertical: Any = None,
    features: Any = None,
    features_position: Any = None,
    state_content: Any = None,
    tap_action: Mapping[str, Any] | None = None,
    hold_action: Mapping[str, Any] | None = None,
    double_tap_action: Mapping[str, Any] | None = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.tile(entity, color=..., features=[...], vertical=...)``.

    `features=` is the tile-card-features sub-vocabulary, passthrough-in-v1
    (§5.3: a list of feature dicts, e.g. `{"type": "climate-hvac-modes"}`).
    `icon_tap_action` (a real tile-card option) is deliberately left
    undeclared — an author reaches it through `extra=` — this module's
    docstring explains why.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "tile", "entity": str(entity)}
    put(body, "name", name)
    put(body, "icon", icon)
    put(body, "color", color)
    put(body, "show_entity_picture", show_entity_picture)
    put(body, "vertical", vertical)
    put(body, "features", features)
    put(body, "features_position", features_position)
    put(body, "state_content", state_content)
    put(body, "tap_action", dict(tap_action) if tap_action is not None else None)
    put(body, "hold_action", dict(hold_action) if hold_action is not None else None)
    put(
        body,
        "double_tap_action",
        dict(double_tap_action) if double_tap_action is not None else None,
    )
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.tile", declared=_TILE_DECLARED, span=span)
    record_card(body, span=span, what="`c.tile()`")


def entity(
    entity: Any,
    *,
    attribute: Any = None,
    name: Any = None,
    icon: Any = None,
    unit: Any = None,
    state_color: Any = None,
    format: Any = None,
    tap_action: Mapping[str, Any] | None = None,
    hold_action: Mapping[str, Any] | None = None,
    double_tap_action: Mapping[str, Any] | None = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.entity(entity, attribute=..., name=..., icon=...)``."""
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "entity", "entity": str(entity)}
    put(body, "attribute", attribute)
    put(body, "name", name)
    put(body, "icon", icon)
    put(body, "unit", unit)
    put(body, "state_color", state_color)
    put(body, "format", format)
    put(body, "tap_action", dict(tap_action) if tap_action is not None else None)
    put(body, "hold_action", dict(hold_action) if hold_action is not None else None)
    put(
        body,
        "double_tap_action",
        dict(double_tap_action) if double_tap_action is not None else None,
    )
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.entity", declared=_ENTITY_DECLARED, span=span)
    record_card(body, span=span, what="`c.entity()`")


def button(
    *,
    entity: Any = None,
    name: Any = None,
    icon: Any = None,
    icon_height: Any = None,
    show_name: Any = None,
    show_icon: Any = None,
    show_state: Any = None,
    state_color: Any = None,
    theme: Any = None,
    tap_action: Mapping[str, Any] | None = None,
    hold_action: Mapping[str, Any] | None = None,
    double_tap_action: Mapping[str, Any] | None = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.button(entity=..., tap_action=..., name=..., icon=...)``.

    `entity=` is optional — HA's button card also works as a pure
    navigation/action trigger with no entity at all.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "button"}
    put(body, "entity", str(entity) if entity is not None else None)
    put(body, "name", name)
    put(body, "icon", icon)
    put(body, "icon_height", icon_height)
    put(body, "show_name", show_name)
    put(body, "show_icon", show_icon)
    put(body, "show_state", show_state)
    put(body, "state_color", state_color)
    put(body, "theme", theme)
    put(body, "tap_action", dict(tap_action) if tap_action is not None else None)
    put(body, "hold_action", dict(hold_action) if hold_action is not None else None)
    put(
        body,
        "double_tap_action",
        dict(double_tap_action) if double_tap_action is not None else None,
    )
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.button", declared=_BUTTON_DECLARED, span=span)
    record_card(body, span=span, what="`c.button()`")


def heading(
    *,
    heading: Any = None,
    heading_style: Any = None,
    icon: Any = None,
    badges: Iterable[Any] | None = None,
    tap_action: Mapping[str, Any] | None = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.heading(heading=..., heading_style=..., badges=[...])``."""
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "heading"}
    put(body, "heading", heading)
    put(body, "heading_style", heading_style)
    put(body, "icon", icon)
    put(body, "badges", [_normalize_badge(b) for b in badges] if badges is not None else None)
    put(body, "tap_action", dict(tap_action) if tap_action is not None else None)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.heading", declared=_HEADING_DECLARED, span=span)
    record_card(body, span=span, what="`c.heading()`")


# ---------------------------------------------------------------------------
# F5 registration (card_registry.py) — one append-only row per builder.
# ---------------------------------------------------------------------------
register_card(
    CardSpec(
        type="entities",
        declared=frozenset(
            {
                "type",
                "entities",
                "title",
                "show_header_toggle",
                "state_color",
                "icon",
                "theme",
                "visibility",
            }
        ),
        builder="c.entities",
        entity_params=("entities",),
    )
)
register_card(
    CardSpec(
        type="glance",
        declared=frozenset(
            {
                "type",
                "entities",
                "title",
                "show_name",
                "show_icon",
                "show_state",
                "state_color",
                "columns",
                "theme",
                "visibility",
            }
        ),
        builder="c.glance",
        entity_params=("entities",),
    )
)
register_card(
    CardSpec(
        type="tile",
        declared=frozenset(
            {
                "type",
                "entity",
                "name",
                "icon",
                "color",
                "show_entity_picture",
                "vertical",
                "features",
                "features_position",
                "state_content",
                "tap_action",
                "hold_action",
                "double_tap_action",
                "visibility",
            }
        ),
        builder="c.tile",
        entity_params=("entity",),
    )
)
register_card(
    CardSpec(
        type="entity",
        declared=frozenset(
            {
                "type",
                "entity",
                "attribute",
                "name",
                "icon",
                "unit",
                "state_color",
                "format",
                "tap_action",
                "hold_action",
                "double_tap_action",
                "visibility",
            }
        ),
        builder="c.entity",
        entity_params=("entity",),
    )
)
register_card(
    CardSpec(
        type="button",
        declared=frozenset(
            {
                "type",
                "entity",
                "name",
                "icon",
                "icon_height",
                "show_name",
                "show_icon",
                "show_state",
                "state_color",
                "theme",
                "tap_action",
                "hold_action",
                "double_tap_action",
                "visibility",
            }
        ),
        builder="c.button",
        entity_params=("entity",),
    )
)
register_card(
    CardSpec(
        type="heading",
        declared=frozenset(
            {"type", "heading", "heading_style", "icon", "badges", "tap_action", "visibility"}
        ),
        builder="c.heading",
    )
)
