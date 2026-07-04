"""M4 test 8 (meta-test): the DESIGN §10.2 example tests run green verbatim
against the example bundle (fixtures/sim/hallway_bundle).

The seeded-logic-bug done-gate lives in a sibling bundle + test file
(fixtures/sim/hallway_bundle_buggy/, test_sim_seeded_bug_caught.py) so this
file stays a clean, green demonstration of the DESIGN §10.2 examples.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler import compile_bundle
from hassle.testing import Simulator

_BUNDLE = Path(__file__).resolve().parents[3] / "fixtures" / "sim" / "hallway_bundle"


def _sim() -> Simulator:
    return Simulator(compile_bundle(_BUNDLE))


# ---------------------------------------------------------------------------
# DESIGN §10.2 examples, verbatim
# ---------------------------------------------------------------------------


def test_motion_turns_on_light_at_night() -> None:
    sim = _sim()
    sim.set_sun_times(sunrise="06:00:00", sunset="20:00:00")
    sim.at("2026-07-03 22:30")  # after sunset (and after the -00:30 offset)
    sim.set_state("input_boolean.guest_mode", "off")
    sim.state_change("binary_sensor.hall_motion", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    sim.advance(minutes=5)
    sim.assert_called("light.turn_off", entity_id="light.hallway")


def test_no_trigger_during_day() -> None:
    """The automation's own `sun(after="sunset", after_offset="-00:30:00")`
    condition (DESIGN §10.2) is the thing under test here -- guest_mode is
    "off" (the condition that *would* let it fire), so a noon trigger not
    firing proves the day/night gate itself, not guest-mode suppression."""
    sim = _sim()
    sim.set_sun_times(sunrise="06:00:00", sunset="20:00:00")
    sim.at("2026-07-03 12:00")  # well before sunset -- the gate must hold
    sim.set_state("input_boolean.guest_mode", "off")
    sim.state_change("binary_sensor.hall_motion", "off", "on")
    sim.assert_not_called("light.turn_on")


def test_no_trigger_when_guest_mode_on_even_at_night() -> None:
    """Separate assertion for guest-mode suppression (kept distinct from the
    day/night gate test above, per review): guest_mode "on" blocks the light
    even well after the sun gate is satisfied."""
    sim = _sim()
    sim.set_sun_times(sunrise="06:00:00", sunset="20:00:00")
    sim.at("2026-07-03 22:30")  # after sunset -- the sun gate alone would pass
    sim.set_state("input_boolean.guest_mode", "on")
    sim.state_change("binary_sensor.hall_motion", "off", "on")
    sim.assert_not_called("light.turn_on")
