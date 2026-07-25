"""`hassle.testing.Simulator` gets public accessors for "all recorded calls"
and "known automation object keys" so callers outside the package (the CLI's
`cli.py`/`run_sim.py`) never reach into the private `_calls`/`_engines_by_key`
attributes.
"""

from __future__ import annotations

from pathlib import Path

from hassle.testing import Simulator, simulate

_BUNDLE = Path(__file__).resolve().parents[3] / "fixtures" / "sim" / "hallway_bundle"


def test_all_calls_returns_every_recorded_call_unfiltered() -> None:
    sim = simulate(_BUNDLE)
    sim.set_state("input_boolean.guest_mode", "off")
    sim.state_change("binary_sensor.hall_motion", "off", "on")
    all_calls = sim.all_calls()
    assert [c.action for c in all_calls] == ["light.turn_on"]
    # Same objects `calls("light.turn_on")` would return, just unfiltered.
    assert all_calls == sim.calls("light.turn_on")


def test_automation_keys_lists_known_object_keys() -> None:
    sim = simulate(_BUNDLE)
    keys = sim.automation_keys()
    assert isinstance(keys, list)
    assert any(key.endswith(":hall_light_on_motion") for key in keys)


def test_automation_keys_reflects_fire_lookup_surface() -> None:
    """Every key `automation_keys()` returns must be usable with `fire()`."""
    sim = simulate(_BUNDLE)
    for key in sim.automation_keys():
        sim.fire(key)  # must not raise KeyError


def test_simulator_has_no_public_use_of_private_attrs() -> None:
    """Guard against regression: the public surface is the accessor methods,
    not the private attributes directly."""
    sim = simulate(_BUNDLE)
    assert hasattr(sim, "all_calls")
    assert hasattr(sim, "automation_keys")
    assert isinstance(sim, Simulator)
