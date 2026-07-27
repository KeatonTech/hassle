"""DB3c (energy half): the 12 built-in Energy dashboard cards.

Test contract (docs/internals/dashboards-design.md §5.3, §6.1.1 -- the frozen
F5 card-builder protocol): every builder in `cards/energy.py` is a leaf card,
option-free apart from `collection_key=` (`energy_distribution` also takes
`link_dashboard=`, `energy_sankey` also takes `title=`), built on the shared
`put`/`merge_extra`/`normalize_visibility` conventions and the `record_card`
seam, registered exactly once in `CARD_REGISTRY` with an empty
`entity_params` (none of these cards read from an entity of their own -- they
read the dashboard's shared Energy data collection).
"""

from __future__ import annotations

from typing import Any

import pytest

from hassle.cards import cond
from hassle.compiler.dashboards.card_registry import CARD_REGISTRY
from hassle.compiler.dashboards.cards import energy as en
from hassle.compiler.dashboards.errors import ExtraShadowsKwargError
from hassle.compiler.dashboards.recorder import dashboard_recording
from hassle.compiler.dashboards.structure import view

ENERGY_TYPES: tuple[str, ...] = (
    "energy-date-selection",
    "energy-usage-graph",
    "energy-solar-graph",
    "energy-gas-graph",
    "energy-water-graph",
    "energy-distribution",
    "energy-sources-table",
    "energy-grid-neutrality-gauge",
    "energy-solar-consumed-gauge",
    "energy-carbon-consumed-gauge",
    "energy-self-sufficiency-gauge",
    "energy-sankey",
)

# The eleven builders sharing the plain `{type, collection_key?, visibility?}`
# shape (every builder except `energy_distribution`, which alone also takes
# `link_dashboard=`; `energy_sankey` is exercised separately below for its
# extra `title=`).
_SIMPLE_BUILDERS: tuple[tuple[Any, str], ...] = (
    (en.energy_date_selection, "energy-date-selection"),
    (en.energy_usage_graph, "energy-usage-graph"),
    (en.energy_solar_graph, "energy-solar-graph"),
    (en.energy_gas_graph, "energy-gas-graph"),
    (en.energy_water_graph, "energy-water-graph"),
    (en.energy_sources_table, "energy-sources-table"),
    (en.energy_grid_neutrality_gauge, "energy-grid-neutrality-gauge"),
    (en.energy_solar_consumed_gauge, "energy-solar-consumed-gauge"),
    (en.energy_carbon_consumed_gauge, "energy-carbon-consumed-gauge"),
    (en.energy_self_sufficiency_gauge, "energy-self-sufficiency-gauge"),
)


def _cards(build: Any) -> list[dict[str, Any]]:
    """Record cards directly in a `masonry` view (no `section()` needed)."""
    with dashboard_recording(url_path="a-b") as rec:
        with view(title="V", type="masonry"):
            build()
        return rec.build_config()["views"][0]["cards"]


# ---------------------------------------------------------------------------
# The eleven simple-shaped builders
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("builder", "card_type"), _SIMPLE_BUILDERS)
def test_simple_energy_card_omits_collection_key_when_absent(builder: Any, card_type: str) -> None:
    def build() -> None:
        builder()

    assert _cards(build) == [{"type": card_type}]


@pytest.mark.parametrize(("builder", "card_type"), _SIMPLE_BUILDERS)
def test_simple_energy_card_collection_key_typed_option(builder: Any, card_type: str) -> None:
    def build() -> None:
        builder(collection_key="energy_secondary")

    assert _cards(build) == [{"type": card_type, "collection_key": "energy_secondary"}]


@pytest.mark.parametrize(("builder", "card_type"), _SIMPLE_BUILDERS)
def test_simple_energy_card_extra_merges_verbatim(builder: Any, card_type: str) -> None:
    def build() -> None:
        builder(extra={"card_mod": {"a": 1}})

    assert _cards(build) == [{"type": card_type, "card_mod": {"a": 1}}]


@pytest.mark.parametrize(("builder", "card_type"), _SIMPLE_BUILDERS)
def test_simple_energy_card_extra_shadowing_declared_kwarg_raises(
    builder: Any, card_type: str
) -> None:
    with dashboard_recording(url_path="a-b"), view(title="V", type="masonry"):  # noqa: SIM117
        with pytest.raises(ExtraShadowsKwargError):
            builder(extra={"collection_key": "other"})


@pytest.mark.parametrize(("builder", "card_type"), _SIMPLE_BUILDERS)
def test_simple_energy_card_visibility_normalizes_conditions(builder: Any, card_type: str) -> None:
    def build() -> None:
        builder(visibility=cond.state("input_boolean.on", "on"))

    assert _cards(build)[0]["visibility"] == [
        {"condition": "state", "entity": "input_boolean.on", "state": "on"}
    ]


# ---------------------------------------------------------------------------
# energy_distribution -- extra `link_dashboard=`
# ---------------------------------------------------------------------------


def test_energy_distribution_typed_options() -> None:
    def build() -> None:
        en.energy_distribution(collection_key="energy_secondary", link_dashboard=True)

    assert _cards(build) == [
        {
            "type": "energy-distribution",
            "collection_key": "energy_secondary",
            "link_dashboard": True,
        }
    ]


def test_energy_distribution_omits_options_that_were_never_passed() -> None:
    def build() -> None:
        en.energy_distribution()

    assert _cards(build) == [{"type": "energy-distribution"}]


def test_energy_distribution_extra_shadowing_a_declared_kwarg_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V", type="masonry"):  # noqa: SIM117
        with pytest.raises(ExtraShadowsKwargError):
            en.energy_distribution(extra={"link_dashboard": False})


# ---------------------------------------------------------------------------
# energy_sankey -- extra `title=`
# ---------------------------------------------------------------------------


def test_energy_sankey_typed_options() -> None:
    def build() -> None:
        en.energy_sankey(collection_key="energy_secondary", title="Flows")

    assert _cards(build) == [
        {
            "type": "energy-sankey",
            "collection_key": "energy_secondary",
            "title": "Flows",
        }
    ]


def test_energy_sankey_omits_options_that_were_never_passed() -> None:
    def build() -> None:
        en.energy_sankey()

    assert _cards(build) == [{"type": "energy-sankey"}]


def test_energy_sankey_extra_shadowing_a_declared_kwarg_raises() -> None:
    with dashboard_recording(url_path="a-b"), view(title="V", type="masonry"):  # noqa: SIM117
        with pytest.raises(ExtraShadowsKwargError):
            en.energy_sankey(extra={"title": "other"})


# ---------------------------------------------------------------------------
# CARD_REGISTRY -- each builder registered exactly once, with correct wiring
# ---------------------------------------------------------------------------


def test_every_energy_card_type_is_registered_exactly_once() -> None:
    for card_type in ENERGY_TYPES:
        assert card_type in CARD_REGISTRY, f"{card_type!r} missing from CARD_REGISTRY"
    present = [t for t in CARD_REGISTRY if t in ENERGY_TYPES]
    assert sorted(present) == sorted(ENERGY_TYPES)


@pytest.mark.parametrize(
    ("card_type", "builder"),
    [
        ("energy-date-selection", "c.energy_date_selection"),
        ("energy-usage-graph", "c.energy_usage_graph"),
        ("energy-solar-graph", "c.energy_solar_graph"),
        ("energy-gas-graph", "c.energy_gas_graph"),
        ("energy-water-graph", "c.energy_water_graph"),
        ("energy-distribution", "c.energy_distribution"),
        ("energy-sources-table", "c.energy_sources_table"),
        ("energy-grid-neutrality-gauge", "c.energy_grid_neutrality_gauge"),
        ("energy-solar-consumed-gauge", "c.energy_solar_consumed_gauge"),
        ("energy-carbon-consumed-gauge", "c.energy_carbon_consumed_gauge"),
        ("energy-self-sufficiency-gauge", "c.energy_self_sufficiency_gauge"),
        ("energy-sankey", "c.energy_sankey"),
    ],
)
def test_card_spec_wiring(card_type: str, builder: str) -> None:
    spec = CARD_REGISTRY[card_type]
    assert spec.builder == builder
    assert spec.entity_params == ()
    assert spec.container == "leaf"
    assert spec.context_manager is False
