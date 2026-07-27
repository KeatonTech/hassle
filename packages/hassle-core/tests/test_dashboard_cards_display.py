"""`hassle.cards` display leaf builders — DB3a's batch.

Test contract (docs/internals/dashboards-design.md §5.3): `entities`/`glance`
take rows as positional varargs (`EntityRef | str | dict`); `tile`/`entity`/
`button` take one `entity=`; `heading` takes `badges=`. Every builder shares
the `extra=`/`visibility=` contract.
"""

from __future__ import annotations

from typing import Any

import pytest

from hassle.cards import button, cond, entities, entity, glance, heading, tile
from hassle.compiler.dashboards.errors import ExtraShadowsKwargError
from hassle.compiler.dashboards.recorder import dashboard_recording
from hassle.compiler.dashboards.structure import section, view
from hassle.registry import entities as e


def _card(build: Any) -> dict[str, Any]:
    with dashboard_recording(url_path="a-b") as rec, view(title="V"), section():
        build()
    return rec.build_config()["views"][0]["sections"][0]["cards"][0]


# ---------------------------------------------------------------------------
# entities — mixed varargs rows
# ---------------------------------------------------------------------------
def test_entities_card_mixed_rows() -> None:
    def build() -> None:
        entities(
            e.light.kitchen,
            "light.living_room",
            {"type": "divider"},
            title="Lights",
        )

    card = _card(build)
    assert card == {
        "type": "entities",
        "entities": ["light.kitchen", "light.living_room", {"type": "divider"}],
        "title": "Lights",
    }


def test_entities_card_with_no_rows() -> None:
    def build() -> None:
        entities(title="Empty")

    assert _card(build) == {"type": "entities", "entities": [], "title": "Empty"}


def test_entities_extra_shadowing_entities_key_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"), section():  # noqa: SIM117
        with pytest.raises(ExtraShadowsKwargError):
            entities("light.a", extra={"entities": []})


# ---------------------------------------------------------------------------
# glance
# ---------------------------------------------------------------------------
def test_glance_card_rows_and_options() -> None:
    def build() -> None:
        glance(e.light.a, e.light.b, title="Glance", columns=2, show_name=False)

    assert _card(build) == {
        "type": "glance",
        "entities": ["light.a", "light.b"],
        "title": "Glance",
        "columns": 2,
        "show_name": False,
    }


# ---------------------------------------------------------------------------
# tile — features + both tap-action forms
# ---------------------------------------------------------------------------
def test_tile_card_features_and_typed_tap_action() -> None:
    def build() -> None:
        tile(
            e.climate.living_room,
            color="blue",
            vertical=True,
            features=[{"type": "climate-hvac-modes"}],
            tap_action={"action": "more-info"},
        )

    assert _card(build) == {
        "type": "tile",
        "entity": "climate.living_room",
        "color": "blue",
        "vertical": True,
        "features": [{"type": "climate-hvac-modes"}],
        "tap_action": {"action": "more-info"},
    }


def test_tile_card_icon_tap_action_only_reachable_via_extra() -> None:
    # `icon_tap_action` is a real tile-card option Hassle leaves undeclared on
    # purpose (module docstring) -- it must round-trip through `extra=`.
    def build() -> None:
        tile(
            "light.a",
            tap_action={"action": "toggle"},
            extra={"icon_tap_action": {"action": "more-info"}},
        )

    card = _card(build)
    assert card["tap_action"] == {"action": "toggle"}
    assert card["icon_tap_action"] == {"action": "more-info"}


def test_tile_extra_shadowing_tap_action_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V"), section():  # noqa: SIM117
        with pytest.raises(ExtraShadowsKwargError):
            tile("light.a", tap_action={"action": "toggle"}, extra={"tap_action": {}})


# ---------------------------------------------------------------------------
# entity
# ---------------------------------------------------------------------------
def test_entity_card_attribute_and_actions() -> None:
    def build() -> None:
        entity(
            e.sensor.outside_temp,
            attribute="battery_level",
            name="Battery",
            hold_action={"action": "more-info"},
        )

    assert _card(build) == {
        "type": "entity",
        "entity": "sensor.outside_temp",
        "attribute": "battery_level",
        "name": "Battery",
        "hold_action": {"action": "more-info"},
    }


# ---------------------------------------------------------------------------
# button
# ---------------------------------------------------------------------------
def test_button_card_with_entity_and_tap_action() -> None:
    def build() -> None:
        button(
            entity=e.script.movie_time,
            name="Movie time",
            tap_action={"action": "perform-action", "perform_action": "script.movie_time"},
        )

    assert _card(build) == {
        "type": "button",
        "entity": "script.movie_time",
        "name": "Movie time",
        "tap_action": {"action": "perform-action", "perform_action": "script.movie_time"},
    }


def test_button_card_with_no_entity_is_a_pure_action_trigger() -> None:
    def build() -> None:
        button(name="Go", tap_action={"action": "navigate", "navigation_path": "/lovelace/0"})

    card = _card(build)
    assert "entity" not in card
    assert card["tap_action"] == {"action": "navigate", "navigation_path": "/lovelace/0"}


# ---------------------------------------------------------------------------
# heading
# ---------------------------------------------------------------------------
def test_heading_card_with_badges() -> None:
    def build() -> None:
        heading(
            heading="Living room",
            heading_style="title",
            icon="mdi:sofa",
            badges=[e.sensor.outside_temp, {"type": "state-label", "entity": "light.a"}],
        )

    assert _card(build) == {
        "type": "heading",
        "heading": "Living room",
        "heading_style": "title",
        "icon": "mdi:sofa",
        "badges": [
            {"type": "entity", "entity": "sensor.outside_temp"},
            {"type": "state-label", "entity": "light.a"},
        ],
    }


def test_heading_card_visibility() -> None:
    def build() -> None:
        heading(heading="Hidden", visibility=cond.state("input_boolean.guest_mode", "on"))

    assert _card(build)["visibility"] == [
        {"condition": "state", "entity": "input_boolean.guest_mode", "state": "on"}
    ]
