"""M4 test 3: wait_for_trigger timeout vs satisfied paths; continue_on_timeout."""

from __future__ import annotations

from pathlib import Path

from _sim_helpers import build_sim


def test_wait_for_trigger_satisfied_before_timeout(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, minutes, service, state, wait_for, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.start").to("on"))
            wait_for(state("binary_sensor.door").to("off"), timeout=minutes(10))
            service("notify.mobile_app", message="wait completed")
        """,
    )
    sim.set_state("binary_sensor.door", "on")
    sim.state_change("button.start", "off", "on")
    sim.assert_not_called("notify.mobile_app")
    sim.advance(minutes=5)
    sim.state_change("binary_sensor.door", "on", "off")
    sim.assert_called("notify.mobile_app")


def test_wait_for_trigger_times_out_continue_true(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, minutes, service, state, wait_for, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.start").to("on"))
            wait_for(
                state("binary_sensor.door").to("off"),
                timeout=minutes(10),
                continue_on_timeout=True,
            )
            service("notify.mobile_app", message="wait completed")
        """,
    )
    sim.set_state("binary_sensor.door", "on")
    sim.state_change("button.start", "off", "on")
    sim.advance(minutes=10)
    # continue_on_timeout=True: the action sequence continues past the wait.
    sim.assert_called("notify.mobile_app")


def test_wait_for_trigger_times_out_continue_false_stops_sequence(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, minutes, service, state, wait_for, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.start").to("on"))
            wait_for(
                state("binary_sensor.door").to("off"),
                timeout=minutes(10),
                continue_on_timeout=False,
            )
            service("notify.mobile_app", message="wait completed")
        """,
    )
    sim.set_state("binary_sensor.door", "on")
    sim.state_change("button.start", "off", "on")
    sim.advance(minutes=10)
    # continue_on_timeout=False: the sequence stops; the following action never runs.
    sim.assert_not_called("notify.mobile_app")


def test_wait_for_trigger_satisfied_stops_pending_timeout(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, minutes, service, state, wait_for, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.start").to("on"))
            wait_for(state("binary_sensor.door").to("off"), timeout=minutes(10))
            service("notify.mobile_app", message="satisfied")
        """,
    )
    sim.set_state("binary_sensor.door", "on")
    sim.state_change("button.start", "off", "on")
    sim.state_change("binary_sensor.door", "on", "off")
    sim.assert_called("notify.mobile_app", times=1)
    # Once satisfied, the (now-irrelevant) original timeout must not cause a
    # second, spurious continuation.
    sim.advance(minutes=10)
    sim.assert_called("notify.mobile_app", times=1)
