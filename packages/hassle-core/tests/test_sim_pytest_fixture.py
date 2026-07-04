"""The `sim` pytest fixture (DESIGN §10.2): auto-loads a compiled bundle and
pins the clock. A real bundle's `tests/` directory sits one level below the
bundle root, so the fixture's default bundle-dir resolution is "the parent of
rootdir" -- overridable per test module with the `hassle_bundle(path)` marker
(what this file uses, since the bundle actually lives under `fixtures/sim/`,
not next to this tests directory). The fixture itself is
`hassle.testing.plugin`'s pytest11 entry point, registered on the
`hassle-core` distribution so plain `pytest` picks it up automatically once
hassle-core is installed (DESIGN §10.2: "plain `pytest` works too").
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.testing import Simulator

pytest_plugins = ["hassle.testing.plugin"]

_BUNDLE = Path(__file__).resolve().parents[3] / "fixtures" / "sim" / "hallway_bundle"

pytestmark = pytest.mark.hassle_bundle(_BUNDLE)


def test_sim_fixture_is_a_simulator(sim: Simulator) -> None:
    assert isinstance(sim, Simulator)


def test_sim_fixture_runs_the_configured_bundle(sim: Simulator) -> None:
    sim.set_state("input_boolean.guest_mode", "off")
    sim.state_change("binary_sensor.hall_motion", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.hallway", brightness_pct=60)


def test_sim_fixture_is_fresh_per_test(sim: Simulator) -> None:
    """A previous test's calls must never leak into this one (fresh Simulator
    per test function -- pytest's default fixture scope, "function")."""
    assert sim.calls("light.turn_on") == []
