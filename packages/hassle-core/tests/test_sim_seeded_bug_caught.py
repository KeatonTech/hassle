"""M4 done-gate: a seeded logic bug in an example bundle is caught by a test
encoding the intended behavior (MILESTONES M4 "Done when" clause).

`fixtures/sim/hallway_bundle_buggy/hallway.py` inverts the guest_mode
condition from the clean example bundle (`.is_("on")` instead of `.is_("off")`).
This file demonstrates the catch two ways:

1. `test_seeded_bug_caught_by_intended_behavior_assertion` writes the test a
   developer would naturally write from the automation's *stated intent*
   ("light turns on for motion, unless guest mode is on") and shows it fails
   against the buggy bundle -- via `pytest.raises(AssertionError)`, so the
   catch is demonstrated without leaving a permanently-red test in CI.
2. `test_buggy_bundle_exhibits_the_inverted_behavior` pins down exactly what
   the bug actually does (fires when guest mode is ON, stays dark when OFF),
   proving the simulator faithfully executes the wrong logic rather than
   masking it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.compiler import compile_bundle
from hassle.testing import Simulator

_BUGGY_BUNDLE = Path(__file__).resolve().parents[3] / "fixtures" / "sim" / "hallway_bundle_buggy"


def _buggy_sim() -> Simulator:
    return Simulator(compile_bundle(_BUGGY_BUNDLE))


def _assert_intended_behavior(sim: Simulator) -> None:
    """The automation's stated intent: motion turns the light on, *unless*
    guest mode is on."""
    sim.set_state("input_boolean.guest_mode", "off")
    sim.state_change("binary_sensor.hall_motion", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.hallway", brightness_pct=60)


def test_seeded_bug_caught_by_intended_behavior_assertion() -> None:
    sim = _buggy_sim()
    with pytest.raises(AssertionError):
        _assert_intended_behavior(sim)


def test_buggy_bundle_exhibits_the_inverted_behavior() -> None:
    sim = _buggy_sim()
    # With the inverted condition, the light fires when guest mode is ON...
    sim.set_state("input_boolean.guest_mode", "on")
    sim.state_change("binary_sensor.hall_motion", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.hallway", brightness_pct=60)


def test_clean_bundle_does_not_exhibit_the_bug() -> None:
    """Sanity check: the same intended-behavior assertion passes cleanly
    against the non-buggy sibling bundle, confirming the failure above is
    specific to the seeded bug and not a simulator defect."""
    clean_bundle = Path(__file__).resolve().parents[3] / "fixtures" / "sim" / "hallway_bundle"
    sim = Simulator(compile_bundle(clean_bundle))
    _assert_intended_behavior(sim)
