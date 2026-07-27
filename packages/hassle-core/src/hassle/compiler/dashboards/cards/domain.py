"""DB3c (domain half) -- alarm/area/light/climate/media/plant/todo/weather
card builders.

docs/internals/dashboards-design.md §5.3 (leaf card builders) and §6.1.1 (the
frozen F5 card-builder protocol): every builder here is a plain function
(``capture_span(depth=0)``, no ``with`` block -- every card in this family is
a HA **leaf** card, §2.3), built on the shared ``put``/``merge_extra``/
``normalize_visibility`` conventions (``hassle.compiler.dashboards.builders``)
and the ``record_card`` seam (``hassle.compiler.dashboards.recorder``), and
registered into ``CARD_REGISTRY`` (``hassle.compiler.dashboards.card_registry``)
at import time. Same conventions as ``cards/visual.py``/``cards/media.py``
(DB3b) -- that module's docstring has the fuller rationale.

Two cards in this family need a flag beyond "one entity-bearing param":

- ``area``'s entity-shaped parameter (``area=``) is an HA **area id**, not an
  entity id -- ``CardSpec.entity_params`` is therefore left empty (``()``) so
  DB4's ``e.<domain>.<object_id>`` rewrite and DB7's unknown-entity lint never
  touch it. Area-id reference validation (did-you-mean against the registry's
  area list) is a real gap this leaves open -- it is out of this batch's scope
  and is flagged in the DB3c report as a DB7 follow-up, not worked around here.
- ``shopping_list`` is the legacy alias for the ``todo-list`` card family: it
  stores its own ``"shopping-list"`` type string and is never silently
  upgraded to ``todo-list`` (§5.3) -- byte-stability (compile(decompile(x)) ==
  x) wins over "normalizing" an author's or the UI's choice of card.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hassle.compiler.dashboards.builders import (
    VisibilityArg,
    merge_extra,
    normalize_visibility,
    put,
)
from hassle.compiler.dashboards.card_registry import CardSpec, register_card
from hassle.compiler.dashboards.recorder import record_card
from hassle.compiler.helpers import EntityRef
from hassle.compiler.spans import capture_span

EntityArg = EntityRef | str

# ---------------------------------------------------------------------------
# alarm_panel
# ---------------------------------------------------------------------------
_ALARM_PANEL_DECLARED = frozenset({"type", "entity", "name", "states", "visibility"})


def alarm_panel(
    entity: EntityArg,
    *,
    name: Any = None,
    states: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.alarm_panel(entity, ...)`` -- an ``alarm_control_panel.*`` keypad.

    ``states`` is HA's list of arm-mode buttons to show (e.g. ``["arm_home",
    "arm_away"]``); omitted, HA shows its own default set.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "alarm-panel", "entity": str(entity)}
    put(body, "name", name)
    put(body, "states", states)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.alarm_panel", declared=_ALARM_PANEL_DECLARED, span=span)
    record_card(body, span=span, what="`c.alarm_panel()`")


register_card(CardSpec(type="alarm-panel", builder="c.alarm_panel", entity_params=("entity",)))


# ---------------------------------------------------------------------------
# area
# ---------------------------------------------------------------------------
_AREA_DECLARED = frozenset(
    {
        "type",
        "area",
        "navigation_path",
        "show_camera",
        "display_type",
        "alert_classes",
        "sensor_classes",
        "visibility",
    }
)


def area(
    area: str,
    *,
    navigation_path: Any = None,
    show_camera: Any = None,
    display_type: Any = None,
    alert_classes: Any = None,
    sensor_classes: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.area(area, ...)`` -- an area overview card.

    ``area`` is an HA **area id**, not an entity id (an ``area_registry``
    identifier, e.g. ``"living_room"``) -- unlike every other single-target
    leaf builder in this family, so it is deliberately NOT in
    :attr:`~hassle.compiler.dashboards.card_registry.CardSpec.entity_params`
    (see the module docstring). ``alert_classes``/``sensor_classes`` are HA's
    lists of device classes to surface as alerts/sensor readouts on the card;
    ``display_type`` is ``"compact"`` or ``"standard"``.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "area", "area": area}
    put(body, "navigation_path", navigation_path)
    put(body, "show_camera", show_camera)
    put(body, "display_type", display_type)
    put(body, "alert_classes", alert_classes)
    put(body, "sensor_classes", sensor_classes)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.area", declared=_AREA_DECLARED, span=span)
    record_card(body, span=span, what="`c.area()`")


register_card(CardSpec(type="area", builder="c.area", entity_params=()))


# ---------------------------------------------------------------------------
# light
# ---------------------------------------------------------------------------
_LIGHT_DECLARED = frozenset({"type", "entity", "name", "icon", "visibility"})


def light(
    entity: EntityArg,
    *,
    name: Any = None,
    icon: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.light(entity, ...)`` -- a single ``light.*`` brightness/color card."""
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "light", "entity": str(entity)}
    put(body, "name", name)
    put(body, "icon", icon)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.light", declared=_LIGHT_DECLARED, span=span)
    record_card(body, span=span, what="`c.light()`")


register_card(CardSpec(type="light", builder="c.light", entity_params=("entity",)))


# ---------------------------------------------------------------------------
# thermostat
# ---------------------------------------------------------------------------
_THERMOSTAT_DECLARED = frozenset({"type", "entity", "features", "visibility"})


def thermostat(
    entity: EntityArg,
    *,
    features: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.thermostat(entity, ...)`` -- a ``climate.*`` control card.

    ``features`` is HA's passthrough-in-v1 card-features sub-vocabulary
    (§5.3), a list of feature-config dicts (e.g. ``{"type":
    "climate-hvac-mode-select"}``).
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "thermostat", "entity": str(entity)}
    put(body, "features", features)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.thermostat", declared=_THERMOSTAT_DECLARED, span=span)
    record_card(body, span=span, what="`c.thermostat()`")


register_card(CardSpec(type="thermostat", builder="c.thermostat", entity_params=("entity",)))


# ---------------------------------------------------------------------------
# humidifier
# ---------------------------------------------------------------------------
_HUMIDIFIER_DECLARED = frozenset({"type", "entity", "features", "visibility"})


def humidifier(
    entity: EntityArg,
    *,
    features: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.humidifier(entity, ...)`` -- a ``humidifier.*`` control card.

    ``features`` is the same passthrough-in-v1 card-features sub-vocabulary
    ``thermostat`` uses (§5.3).
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "humidifier", "entity": str(entity)}
    put(body, "features", features)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.humidifier", declared=_HUMIDIFIER_DECLARED, span=span)
    record_card(body, span=span, what="`c.humidifier()`")


register_card(CardSpec(type="humidifier", builder="c.humidifier", entity_params=("entity",)))


# ---------------------------------------------------------------------------
# media_control
# ---------------------------------------------------------------------------
_MEDIA_CONTROL_DECLARED = frozenset({"type", "entity", "visibility"})


def media_control(
    entity: EntityArg,
    *,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.media_control(entity, ...)`` -- a ``media_player.*`` transport card."""
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "media-control", "entity": str(entity)}
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.media_control", declared=_MEDIA_CONTROL_DECLARED, span=span)
    record_card(body, span=span, what="`c.media_control()`")


register_card(CardSpec(type="media-control", builder="c.media_control", entity_params=("entity",)))


# ---------------------------------------------------------------------------
# plant_status
# ---------------------------------------------------------------------------
_PLANT_STATUS_DECLARED = frozenset({"type", "entity", "name", "visibility"})


def plant_status(
    entity: EntityArg,
    *,
    name: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.plant_status(entity, ...)`` -- a ``plant.*`` care-status card."""
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "plant-status", "entity": str(entity)}
    put(body, "name", name)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.plant_status", declared=_PLANT_STATUS_DECLARED, span=span)
    record_card(body, span=span, what="`c.plant_status()`")


register_card(CardSpec(type="plant-status", builder="c.plant_status", entity_params=("entity",)))


# ---------------------------------------------------------------------------
# todo_list
# ---------------------------------------------------------------------------
_TODO_LIST_DECLARED = frozenset({"type", "entity", "title", "display_order", "visibility"})


def todo_list(
    entity: EntityArg,
    *,
    title: Any = None,
    display_order: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.todo_list(entity, ...)`` -- a ``todo.*`` list card.

    ``display_order`` is HA's per-item sort mode (e.g. ``"alphabetical"``,
    ``"due_date"``).
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "todo-list", "entity": str(entity)}
    put(body, "title", title)
    put(body, "display_order", display_order)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.todo_list", declared=_TODO_LIST_DECLARED, span=span)
    record_card(body, span=span, what="`c.todo_list()`")


register_card(CardSpec(type="todo-list", builder="c.todo_list", entity_params=("entity",)))


# ---------------------------------------------------------------------------
# shopping_list -- legacy alias, its own type string, never upgraded
# ---------------------------------------------------------------------------
_SHOPPING_LIST_DECLARED = frozenset({"type", "title", "display_order", "visibility"})


def shopping_list(
    *,
    title: Any = None,
    display_order: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.shopping_list(...)`` -- the legacy shopping-list card.

    Stores its own ``"shopping-list"`` type string (§5.3) -- there is exactly
    one Home Assistant shopping list, so unlike ``todo_list`` this builder
    takes no ``entity=`` at all. Never silently upgraded to ``"todo-list"``:
    byte-stability (``compile(decompile(x)) == x``) wins over normalizing an
    author's or the UI's choice of card.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "shopping-list"}
    put(body, "title", title)
    put(body, "display_order", display_order)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(body, extra, builder="c.shopping_list", declared=_SHOPPING_LIST_DECLARED, span=span)
    record_card(body, span=span, what="`c.shopping_list()`")


register_card(CardSpec(type="shopping-list", builder="c.shopping_list", entity_params=()))


# ---------------------------------------------------------------------------
# weather_forecast
# ---------------------------------------------------------------------------
_WEATHER_FORECAST_DECLARED = frozenset(
    {
        "type",
        "entity",
        "show_current",
        "show_forecast",
        "forecast_type",
        "name",
        "visibility",
    }
)


def weather_forecast(
    entity: EntityArg,
    *,
    show_current: Any = None,
    show_forecast: Any = None,
    forecast_type: Any = None,
    name: Any = None,
    visibility: VisibilityArg | None = None,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """``c.weather_forecast(entity, ...)`` -- a ``weather.*`` forecast card.

    ``forecast_type`` is HA's ``"daily"``/``"hourly"``/``"twice_daily"`` mode.
    """
    span = capture_span(depth=0)
    body: dict[str, Any] = {"type": "weather-forecast", "entity": str(entity)}
    put(body, "show_current", show_current)
    put(body, "show_forecast", show_forecast)
    put(body, "forecast_type", forecast_type)
    put(body, "name", name)
    put(body, "visibility", normalize_visibility(visibility, span=span))
    merge_extra(
        body, extra, builder="c.weather_forecast", declared=_WEATHER_FORECAST_DECLARED, span=span
    )
    record_card(body, span=span, what="`c.weather_forecast()`")


register_card(
    CardSpec(type="weather-forecast", builder="c.weather_forecast", entity_params=("entity",))
)
