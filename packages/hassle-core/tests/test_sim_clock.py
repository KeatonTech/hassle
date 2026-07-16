"""Clock semantics -- advance() fires due time triggers in order;
delays expire exactly once; every test here is asserted to be well under
1s wall-clock time by construction (fake clock, no sleeps, deterministic)."""

from __future__ import annotations

import time as wall_clock
from pathlib import Path

from _sim_helpers import build_sim


def test_advance_fires_due_time_triggers_in_order(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, time, when

        @automation(id="early", alias="early")
        def early():
            when(time(at="10:00:00"))
            service("notify.mobile_app", message="early")

        @automation(id="late", alias="late")
        def late():
            when(time(at="10:05:00"))
            service("notify.mobile_app", message="late")
        """,
    )
    sim.at("2026-07-03 09:59:00")
    sim.advance(minutes=10)
    calls = sim.calls("notify.mobile_app")
    assert [c.data["message"] for c in calls] == ["early", "late"]


def test_advance_across_multiple_time_pattern_boundaries(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, time_pattern, when

        @automation(id="a", alias="a")
        def a():
            when(time_pattern(minutes="/10"))
            service("homeassistant.update_entity", entity_id="sensor.uptime")
        """,
    )
    sim.at("2026-07-03 00:00:00")
    sim.advance(minutes=35)
    # Fires at :10, :20, :30 -- three times, not four (not yet at :40).
    sim.assert_called("homeassistant.update_entity", times=3)


def test_delay_expires_exactly_once(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, delay, service, state, when

        @automation(id="a", alias="a", mode="single")
        def a():
            when(state("binary_sensor.motion").to("on"))
            delay(minutes=5)
            service("light.turn_off", entity_id="light.hallway")
        """,
    )
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.advance(minutes=5)
    sim.assert_called("light.turn_off", times=1)
    sim.advance(hours=1)
    sim.assert_called("light.turn_off", times=1)


def test_advance_exactly_at_boundary_fires(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, delay, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("binary_sensor.motion").to("on"))
            delay(minutes=5)
            service("light.turn_off", entity_id="light.hallway")
        """,
    )
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.advance(minutes=4, seconds=59)
    sim.assert_not_called("light.turn_off")
    sim.advance(seconds=1)
    sim.assert_called("light.turn_off")


def test_no_wall_clock_sleep_used(tmp_path: Path) -> None:
    """Meta-test: advancing 1 full simulated day must take negligible wall-clock
    time -- proves the clock never actually sleeps."""
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, time_pattern, when

        @automation(id="a", alias="a")
        def a():
            when(time_pattern(minutes="/1"))
            service("homeassistant.update_entity", entity_id="sensor.uptime")
        """,
    )
    sim.at("2026-07-03 00:00:00")
    start = wall_clock.monotonic()
    sim.advance(hours=24)
    elapsed = wall_clock.monotonic() - start
    assert elapsed < 1.0
    sim.assert_called("homeassistant.update_entity", times=24 * 60)
