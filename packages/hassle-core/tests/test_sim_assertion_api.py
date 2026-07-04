"""hassle.testing assertion API surface: assert_called/assert_not_called/calls,
set_state with attributes, the `stop` action, parallel action primitive, and
partial-kwarg matching semantics on assert_called.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _sim_helpers import build_sim


def test_assert_called_matches_on_subset_of_kwargs(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service("light.turn_on", entity_id="light.hallway", brightness_pct=60, color_name="red")
        """,
    )
    sim.state_change("button.go", "off", "on")
    # A caller who only cares about entity_id shouldn't have to spell out
    # every other data field.
    sim.assert_called("light.turn_on", entity_id="light.hallway")


def test_assert_called_fails_on_mismatched_kwarg(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service("light.turn_on", entity_id="light.hallway", brightness_pct=60)
        """,
    )
    sim.state_change("button.go", "off", "on")
    with pytest.raises(AssertionError):
        sim.assert_called("light.turn_on", entity_id="light.hallway", brightness_pct=99)


def test_assert_not_called_for_wrong_action_name(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service("light.turn_on", entity_id="light.hallway")
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_not_called("light.turn_off")


def test_assert_not_called_raises_when_actually_called(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service("light.turn_on", entity_id="light.hallway")
        """,
    )
    sim.state_change("button.go", "off", "on")
    with pytest.raises(AssertionError):
        sim.assert_not_called("light.turn_on")


def test_calls_property_returns_recorded_calls_in_order(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service("light.turn_on", entity_id="light.hallway")
            service("light.turn_on", entity_id="light.porch")
        """,
    )
    sim.state_change("button.go", "off", "on")
    calls = sim.calls("light.turn_on")
    assert [c.data["entity_id"] for c in calls] == ["light.hallway", "light.porch"]


def test_set_state_with_attributes(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service(
                "notify.mobile_app",
                message=template("{{ state_attr('climate.living', 'temperature') }}"),
            )
        """,
    )
    sim.set_state("climate.living", "heat", attributes={"temperature": 21})
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="21")


def test_stop_action_halts_the_sequence(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, stop, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            stop("done early")
            service("light.turn_on", entity_id="light.hallway")
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_not_called("light.turn_on")


def test_parallel_action_runs_all_branches(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, parallel, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            with parallel():
                service("light.turn_on", entity_id="light.a")
                service("light.turn_on", entity_id="light.b")
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.a")
    sim.assert_called("light.turn_on", entity_id="light.b")


def test_variables_action_recorded_but_not_a_service_call(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, template, variables, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            variables(level=7)
            service("notify.mobile_app", message=template("{{ level }}"))
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_called("notify.mobile_app", message="7")
    assert sim.calls("variables") == []
