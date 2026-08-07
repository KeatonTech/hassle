"""`sim.dashboard()` / `DashboardQuery` (DESIGN §10; docs/internals/
dashboards-design.md §9.1) -- the bundle author's testing story for
dashboards. The two §9.1 examples are the acceptance test contract, run
near-verbatim against `fixtures/sim/climate_dashboard_bundle` (the exact
§0/§9.1 example dashboard).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.testing import DashboardQuery, Simulator
from hassle.testing.dashboard_query import DashboardNode

_BUNDLE = Path(__file__).resolve().parents[3] / "fixtures" / "sim" / "climate_dashboard_bundle"

pytestmark = pytest.mark.hassle_bundle(_BUNDLE)

HEAT_PUMP_HEADS = ["climate.living_room", "climate.office", "climate.bedroom"]


# --- the §9.1 examples, near-verbatim ---------------------------------------


def test_every_head_gets_a_thermostat(sim: Simulator) -> None:
    dash = sim.dashboard("climate-control")  # DashboardQuery over compiled IR
    tiles = dash.cards(type="thermostat")  # recursive: sections, stacks, ...
    assert [t["entity"] for t in tiles] == HEAT_PUMP_HEADS


def test_guest_banner_is_conditional(sim: Simulator) -> None:
    banner = sim.dashboard("climate-control").cards(type="markdown")[0]
    assert banner.parent["type"] == "conditional"


# --- sim.dashboard(): found / not-found --------------------------------------


def test_sim_dashboard_returns_a_dashboard_query(sim: Simulator) -> None:
    dash = sim.dashboard("climate-control")
    assert isinstance(dash, DashboardQuery)


def test_sim_dashboard_not_found_lists_known_url_paths(sim: Simulator) -> None:
    with pytest.raises(KeyError) as excinfo:
        sim.dashboard("does-not-exist")
    message = str(excinfo.value)
    assert "does-not-exist" in message
    assert "climate-control" in message


# --- DashboardQuery.meta / .config -------------------------------------------


def test_meta_and_config_are_the_stored_envelope_halves(sim: Simulator) -> None:
    dash = sim.dashboard("climate-control")
    assert dash.meta == {
        "url_path": "climate-control",
        "title": "Climate",
        "icon": "mdi:thermostat",
    }
    assert isinstance(dash.config, dict)
    assert "views" in dash.config


# --- DashboardQuery.views / .view(path_or_index) -----------------------------


def test_views_lists_every_top_level_view(sim: Simulator) -> None:
    dash = sim.dashboard("climate-control")
    assert len(dash.views) == 1
    assert dash.views[0]["path"] == "overview"


def test_view_by_path(sim: Simulator) -> None:
    dash = sim.dashboard("climate-control")
    view = dash.view("overview")
    assert isinstance(view, DashboardNode)
    assert view["title"] == "Overview"


def test_view_by_index(sim: Simulator) -> None:
    dash = sim.dashboard("climate-control")
    assert dash.view(0)["path"] == "overview"


def test_view_unknown_path_lists_known_paths(sim: Simulator) -> None:
    dash = sim.dashboard("climate-control")
    with pytest.raises(KeyError) as excinfo:
        dash.view("nonexistent")
    message = str(excinfo.value)
    assert "nonexistent" in message
    assert "overview" in message


def test_view_index_out_of_range(sim: Simulator) -> None:
    dash = sim.dashboard("climate-control")
    with pytest.raises(KeyError):
        dash.view(7)


# --- DashboardQuery.cards(type=, entity=) ------------------------------------


def test_cards_recurses_through_sections(sim: Simulator) -> None:
    dash = sim.dashboard("climate-control")
    types = [c["type"] for c in dash.cards()]
    assert "thermostat" in types
    assert "entities" in types
    assert "conditional" in types
    assert "markdown" in types
    assert "heading" in types


def test_cards_filters_by_entity(sim: Simulator) -> None:
    dash = sim.dashboard("climate-control")
    matches = dash.cards(entity="climate.office")
    assert matches
    # Both the thermostat tile AND the entities-card row reference it.
    assert {c["type"] for c in matches} == {"thermostat", "entities"}


def test_card_node_exposes_the_plain_dict(sim: Simulator) -> None:
    dash = sim.dashboard("climate-control")
    tile = dash.cards(type="thermostat")[0]
    assert tile["type"] == "thermostat"
    assert tile["entity"] == "climate.living_room"


def test_card_parent_chain_reaches_the_section(sim: Simulator) -> None:
    dash = sim.dashboard("climate-control")
    tile = dash.cards(type="thermostat")[0]
    assert tile.parent is not None
    assert tile.parent["type"] == "grid"  # a section, stored as type: grid
