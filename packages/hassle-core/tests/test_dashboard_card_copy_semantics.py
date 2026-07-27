"""SF-3 (review round): ONE copy-vs-alias posture across all four card-builder
modules -- deep-copy every author-supplied dict/list option value at record
time (`builders.put_copy`), never alias it.

Test contract, in both directions, over a representative dict/list-valued
option from each of `cards/layout.py`, `cards/display.py`, `cards/visual.py`
and `cards/media.py`:

- mutating the author's dict/list AFTER the builder call must never reach the
  already-compiled card body;
- two builder calls that share ONE Python dict/list (a common pattern: build
  the options once, pass them to several cards) must compile to independent
  card bodies -- mutating one compiled card's value must never affect the
  other's.
"""

from __future__ import annotations

from typing import Any

import pytest

from hassle.cards import button, entity, entity_filter, tile
from hassle.compiler.dashboards.cards import media as m
from hassle.compiler.dashboards.cards import visual as v
from hassle.compiler.dashboards.recorder import dashboard_recording
from hassle.compiler.dashboards.structure import section, view


def _leaf_card(build: Any) -> dict[str, Any]:
    """Record one card directly in a `masonry` view (no `section()` needed)."""
    with dashboard_recording(url_path="a-b") as rec:
        with view(title="V", type="masonry"):
            build()
        return rec.build_config()["views"][0]["cards"][0]


def _mutate(value: Any) -> None:
    if isinstance(value, dict):
        value["__mutated__"] = True
    else:
        value.append("__mutated__")


# ---------------------------------------------------------------------------
# One representative dict/list-valued option per module. Each entry is a
# FACTORY (not a literal) -- `_CASES` is module-level and reused by both
# parametrized tests below, so a literal shared across test invocations would
# let one test's `_mutate` call leak into the next (a real bug in an earlier
# draft of this file, not the implementation): every test that needs a value
# must call the factory itself to get its OWN fresh, unmutated copy.
# ---------------------------------------------------------------------------
_CASES: list[tuple[str, str, Any]] = [
    ("layout.entity_filter.state_filter", "state_filter", lambda: ["on", "off"]),
    ("display.tile.features", "features", lambda: [{"type": "climate-hvac-modes"}]),
    ("display.tile.tap_action", "tap_action", lambda: {"action": "toggle"}),
    ("display.entity.tap_action", "tap_action", lambda: {"action": "more-info"}),
    ("display.button.tap_action", "tap_action", lambda: {"action": "toggle"}),
    ("visual.gauge.severity", "severity", lambda: {"green": "#0f0", "red": "#f00"}),
    ("visual.sensor.limits", "limits", lambda: {"min": 0, "max": 100}),
    ("visual.statistic.period", "period", lambda: {"calendar": {"period": "month"}}),
    ("media.picture.tap_action", "tap_action", lambda: {"action": "more-info"}),
    ("media.picture_elements.elements", "elements", lambda: [{"type": "state-icon"}]),
    ("media.map.geo_location_sources", "geo_location_sources", lambda: ["all"]),
]


def _build_for(name: str, value: Any) -> Any:
    if name == "display.tile.features":
        return lambda: tile("light.a", features=value)
    if name == "display.tile.tap_action":
        return lambda: tile("light.a", tap_action=value)
    if name == "display.entity.tap_action":
        return lambda: entity("sensor.a", tap_action=value)
    if name == "display.button.tap_action":
        return lambda: button(entity="light.a", tap_action=value)
    if name == "visual.gauge.severity":
        return lambda: v.gauge("sensor.a", severity=value)
    if name == "visual.sensor.limits":
        return lambda: v.sensor("sensor.a", limits=value)
    if name == "visual.statistic.period":
        return lambda: v.statistic("sensor.a", period=value)
    if name == "media.picture.tap_action":
        return lambda: m.picture("/local/x.png", tap_action=value)
    if name == "media.picture_elements.elements":
        return lambda: m.picture_elements("/local/x.png", elements=value)
    if name == "media.map.geo_location_sources":
        return lambda: m.map(geo_location_sources=value)
    raise AssertionError(name)  # pragma: no cover - table is exhaustive


def _card_for(name: str, value: Any) -> dict[str, Any]:
    if name == "layout.entity_filter.state_filter":
        with (
            dashboard_recording(url_path="a-b") as rec,
            view(title="V"),
            section(),
            entity_filter(entities=["light.a"], state_filter=value),
        ):
            pass
        return rec.build_config()["views"][0]["sections"][0]["cards"][0]
    return _leaf_card(_build_for(name, value))


@pytest.mark.parametrize(("name", "key", "make"), _CASES, ids=[c[0] for c in _CASES])
def test_mutating_the_authors_value_after_the_call_does_not_corrupt_the_card(
    name: str, key: str, make: Any
) -> None:
    value = make()
    original = (
        dict(value) if isinstance(value, dict) else list(value)  # pyright: ignore[reportUnknownArgumentType]
    )
    card = _card_for(name, value)
    _mutate(value)
    assert card[key] == original
    assert card[key] is not value


@pytest.mark.parametrize(("name", "key", "make"), _CASES, ids=[c[0] for c in _CASES])
def test_two_calls_sharing_one_value_compile_independent_cards(
    name: str, key: str, make: Any
) -> None:
    shared = make()
    card_a = _card_for(name, shared)
    card_b = _card_for(name, shared)
    assert card_a[key] == card_b[key]
    assert card_a[key] is not card_b[key]
    _mutate(card_a[key])
    assert card_a[key] != card_b[key]
