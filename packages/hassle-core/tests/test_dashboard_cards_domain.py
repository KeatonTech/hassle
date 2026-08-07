"""DB3c (domain half): alarm/area/light/climate/media/plant/todo/weather
card builders.

Test contract (docs/internals/dashboards-design.md §5.3, §6.1.1 -- the frozen
F5 card-builder protocol): every builder in `cards/domain.py` is a leaf card
built on the shared `put`/`merge_extra`/`normalize_visibility` conventions and
the `record_card` seam, registered exactly once in `CARD_REGISTRY` with the
right `entity_params` for DB7's table-driven extraction. `area`'s
entity-shaped param is an AREA id, not an entity id, so its `entity_params` is
empty; `shopping_list` keeps its own `"shopping-list"` type string and is
never silently upgraded to `todo-list`.
"""

from __future__ import annotations

from typing import Any

import pytest

from hassle.cards import cond
from hassle.compiler.dashboards.card_registry import CARD_REGISTRY
from hassle.compiler.dashboards.cards import domain as d
from hassle.compiler.dashboards.errors import ExtraShadowsKwargError
from hassle.compiler.dashboards.recorder import dashboard_recording
from hassle.compiler.dashboards.structure import view

DOMAIN_TYPES: tuple[str, ...] = (
    "alarm-panel",
    "area",
    "light",
    "thermostat",
    "humidifier",
    "media-control",
    "plant-status",
    "todo-list",
    "shopping-list",
    "weather-forecast",
)


def _cards(build: Any) -> list[dict[str, Any]]:
    """Record cards directly in a `masonry` view (no `section()` needed)."""
    with dashboard_recording(url_path="a-b") as rec:
        with view(title="V", type="masonry"):
            build()
        return rec.build_config()["views"][0]["cards"]


# ---------------------------------------------------------------------------
# alarm_panel
# ---------------------------------------------------------------------------


def test_alarm_panel_typed_options() -> None:
    def build() -> None:
        d.alarm_panel(
            "alarm_control_panel.home",
            name="Home Alarm",
            states=["arm_home", "arm_away"],
        )

    assert _cards(build) == [
        {
            "type": "alarm-panel",
            "entity": "alarm_control_panel.home",
            "name": "Home Alarm",
            "states": ["arm_home", "arm_away"],
        }
    ]


def test_alarm_panel_omits_options_that_were_never_passed() -> None:
    def build() -> None:
        d.alarm_panel("alarm_control_panel.home")

    assert _cards(build) == [{"type": "alarm-panel", "entity": "alarm_control_panel.home"}]


def test_alarm_panel_extra_merges_verbatim() -> None:
    def build() -> None:
        d.alarm_panel("alarm_control_panel.home", extra={"card_mod": {"a": 1}})

    assert _cards(build) == [
        {"type": "alarm-panel", "entity": "alarm_control_panel.home", "card_mod": {"a": 1}}
    ]


def test_alarm_panel_extra_shadowing_a_declared_kwarg_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V", type="masonry"):  # noqa: SIM117
        with pytest.raises(ExtraShadowsKwargError):
            d.alarm_panel("alarm_control_panel.home", extra={"name": "other"})


def test_alarm_panel_visibility_normalizes_conditions() -> None:
    def build() -> None:
        d.alarm_panel("alarm_control_panel.home", visibility=cond.state("input_boolean.on", "on"))

    assert _cards(build)[0]["visibility"] == [
        {"condition": "state", "entity": "input_boolean.on", "state": "on"}
    ]


# ---------------------------------------------------------------------------
# area -- entity-shaped param is an AREA id, not an entity id
# ---------------------------------------------------------------------------


def test_area_typed_options() -> None:
    def build() -> None:
        d.area(
            "living_room",
            navigation_path="/lovelace/living-room",
            show_camera=True,
            display_type="compact",
            alert_classes=["motion", "smoke"],
            sensor_classes=["temperature", "humidity"],
        )

    assert _cards(build) == [
        {
            "type": "area",
            "area": "living_room",
            "navigation_path": "/lovelace/living-room",
            "show_camera": True,
            "display_type": "compact",
            "alert_classes": ["motion", "smoke"],
            "sensor_classes": ["temperature", "humidity"],
        }
    ]


def test_area_omits_options_that_were_never_passed() -> None:
    def build() -> None:
        d.area("living_room")

    assert _cards(build) == [{"type": "area", "area": "living_room"}]


def test_area_extra_shadowing_a_declared_kwarg_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V", type="masonry"):  # noqa: SIM117
        with pytest.raises(ExtraShadowsKwargError):
            d.area("living_room", extra={"area": "other"})


# ---------------------------------------------------------------------------
# light / thermostat / humidifier / media_control / plant_status
# ---------------------------------------------------------------------------


def test_light_typed_options() -> None:
    def build() -> None:
        d.light("light.living_room", name="Living Room", icon="mdi:ceiling-light")

    assert _cards(build) == [
        {
            "type": "light",
            "entity": "light.living_room",
            "name": "Living Room",
            "icon": "mdi:ceiling-light",
        }
    ]


def test_thermostat_typed_options() -> None:
    def build() -> None:
        d.thermostat(
            "climate.living_room",
            features=[{"type": "climate-hvac-mode-select"}],
        )

    assert _cards(build) == [
        {
            "type": "thermostat",
            "entity": "climate.living_room",
            "features": [{"type": "climate-hvac-mode-select"}],
        }
    ]


def test_humidifier_typed_options() -> None:
    def build() -> None:
        d.humidifier(
            "humidifier.living_room",
            features=[{"type": "humidifier-toggle"}],
        )

    assert _cards(build) == [
        {
            "type": "humidifier",
            "entity": "humidifier.living_room",
            "features": [{"type": "humidifier-toggle"}],
        }
    ]


def test_media_control_typed_options() -> None:
    def build() -> None:
        d.media_control("media_player.living_room")

    assert _cards(build) == [{"type": "media-control", "entity": "media_player.living_room"}]


def test_media_control_extra_shadowing_a_declared_kwarg_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V", type="masonry"):  # noqa: SIM117
        with pytest.raises(ExtraShadowsKwargError):
            d.media_control("media_player.living_room", extra={"entity": "other"})


def test_plant_status_typed_options() -> None:
    def build() -> None:
        d.plant_status("plant.tomato", name="Tomato")

    assert _cards(build) == [{"type": "plant-status", "entity": "plant.tomato", "name": "Tomato"}]


# ---------------------------------------------------------------------------
# todo_list / shopping_list -- shopping_list is the legacy alias
# ---------------------------------------------------------------------------


def test_todo_list_typed_options() -> None:
    def build() -> None:
        d.todo_list("todo.groceries", title="Groceries", display_order="alphabetical")

    assert _cards(build) == [
        {
            "type": "todo-list",
            "entity": "todo.groceries",
            "title": "Groceries",
            "display_order": "alphabetical",
        }
    ]


def test_shopping_list_typed_options_and_no_entity_field() -> None:
    def build() -> None:
        d.shopping_list(title="Shopping", display_order="alphabetical")

    cards = _cards(build)
    assert cards == [
        {"type": "shopping-list", "title": "Shopping", "display_order": "alphabetical"}
    ]
    assert "entity" not in cards[0]


def test_shopping_list_never_upgrades_to_todo_list_type() -> None:
    def build() -> None:
        d.shopping_list()

    assert _cards(build) == [{"type": "shopping-list"}]


def test_shopping_list_extra_shadowing_a_declared_kwarg_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V", type="masonry"):  # noqa: SIM117
        with pytest.raises(ExtraShadowsKwargError):
            d.shopping_list(extra={"title": "other"})


# ---------------------------------------------------------------------------
# weather_forecast
# ---------------------------------------------------------------------------


def test_weather_forecast_typed_options() -> None:
    def build() -> None:
        d.weather_forecast(
            "weather.home",
            show_current=True,
            show_forecast=True,
            forecast_type="daily",
            name="Weather",
        )

    assert _cards(build) == [
        {
            "type": "weather-forecast",
            "entity": "weather.home",
            "show_current": True,
            "show_forecast": True,
            "forecast_type": "daily",
            "name": "Weather",
        }
    ]


def test_weather_forecast_extra_shadowing_a_declared_kwarg_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V", type="masonry"):  # noqa: SIM117
        with pytest.raises(ExtraShadowsKwargError):
            d.weather_forecast("weather.home", extra={"forecast_type": "hourly"})


# ---------------------------------------------------------------------------
# CARD_REGISTRY -- each builder registered exactly once, with correct wiring
# ---------------------------------------------------------------------------


def test_every_domain_card_type_is_registered_exactly_once() -> None:
    for card_type in DOMAIN_TYPES:
        assert card_type in CARD_REGISTRY, f"{card_type!r} missing from CARD_REGISTRY"
    present = [t for t in CARD_REGISTRY if t in DOMAIN_TYPES]
    assert sorted(present) == sorted(DOMAIN_TYPES)


@pytest.mark.parametrize(
    ("card_type", "builder", "entity_params"),
    [
        ("alarm-panel", "c.alarm_panel", ("entity",)),
        ("area", "c.area", ()),
        ("light", "c.light", ("entity",)),
        ("thermostat", "c.thermostat", ("entity",)),
        ("humidifier", "c.humidifier", ("entity",)),
        ("media-control", "c.media_control", ("entity",)),
        ("plant-status", "c.plant_status", ("entity",)),
        ("todo-list", "c.todo_list", ("entity",)),
        ("shopping-list", "c.shopping_list", ()),
        ("weather-forecast", "c.weather_forecast", ("entity",)),
    ],
)
def test_card_spec_wiring(card_type: str, builder: str, entity_params: tuple[str, ...]) -> None:
    spec = CARD_REGISTRY[card_type]
    assert spec.builder == builder
    assert spec.entity_params == entity_params
    assert spec.container == "leaf"
    assert spec.context_manager is False
