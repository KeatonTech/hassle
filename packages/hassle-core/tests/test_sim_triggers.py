"""M4 test 1: trigger semantics per type (DESIGN §10.1 v1 set).

state (incl. for_: must hold, reset on flap), to/from filters, numeric_state
crossing (only on cross, not while above), time, time_pattern, sun (configured
times), template (fires false->true only), event, zone.

Every test is wall-clock free (a fake clock, R8) and must run in well under 1s
(CI-enforced marker, per-test).
"""

from __future__ import annotations

from pathlib import Path

from _sim_helpers import build_sim

# ---------------------------------------------------------------------------
# state trigger
# ---------------------------------------------------------------------------


def test_state_trigger_fires_on_change(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("binary_sensor.motion").to("on"))
            service("light.turn_on", entity_id="light.hallway")
        """,
    )
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.hallway")


def test_state_trigger_to_filter_ignores_other_transitions(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("binary_sensor.motion").to("on"))
            service("light.turn_on", entity_id="light.hallway")
        """,
    )
    sim.state_change("binary_sensor.motion", "on", "off")
    sim.assert_not_called("light.turn_on")


def test_state_trigger_from_filter(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("binary_sensor.motion").is_("off").to("on"))
            service("light.turn_on", entity_id="light.hallway")
        """,
    )
    # from a state other than "off" -> "on" must not fire.
    sim.set_state("binary_sensor.motion", "unknown")
    sim.state_change("binary_sensor.motion", "unknown", "on")
    sim.assert_not_called("light.turn_on")
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.assert_called("light.turn_on")


def test_state_trigger_for_must_hold(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, minutes, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("binary_sensor.motion").to("on").with_options(for_=minutes(5)))
            service("light.turn_on", entity_id="light.hallway")
        """,
    )
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.assert_not_called("light.turn_on")
    sim.advance(minutes=4)
    sim.assert_not_called("light.turn_on")
    sim.advance(minutes=1)
    sim.assert_called("light.turn_on")


def test_state_trigger_for_resets_on_flap(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, minutes, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("binary_sensor.motion").to("on").with_options(for_=minutes(5)))
            service("light.turn_on", entity_id="light.hallway")
        """,
    )
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.advance(minutes=3)
    # flap back off then on again -- the for_ timer must restart from zero.
    sim.state_change("binary_sensor.motion", "on", "off")
    sim.state_change("binary_sensor.motion", "off", "on")
    sim.advance(minutes=3)
    sim.assert_not_called("light.turn_on")
    sim.advance(minutes=2)
    sim.assert_called("light.turn_on")


# ---------------------------------------------------------------------------
# numeric_state trigger -- only fires on cross, not while above/below
# ---------------------------------------------------------------------------


def test_numeric_state_fires_on_cross_above(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, numeric_state, service, when

        @automation(id="a", alias="a")
        def a():
            when(numeric_state("sensor.temp", above=25))
            service("notify.mobile_app", message="hot")
        """,
    )
    sim.set_state("sensor.temp", "20")
    sim.state_change("sensor.temp", "20", "26")
    sim.assert_called("notify.mobile_app")


def test_numeric_state_does_not_refire_while_above(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, numeric_state, service, when

        @automation(id="a", alias="a")
        def a():
            when(numeric_state("sensor.temp", above=25))
            service("notify.mobile_app", message="hot")
        """,
    )
    sim.set_state("sensor.temp", "20")
    sim.state_change("sensor.temp", "20", "26")
    sim.assert_called("notify.mobile_app", times=1)
    sim.state_change("sensor.temp", "26", "27")
    sim.assert_called("notify.mobile_app", times=1)


def test_numeric_state_does_not_fire_when_starting_above(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, numeric_state, service, when

        @automation(id="a", alias="a")
        def a():
            when(numeric_state("sensor.temp", above=25))
            service("notify.mobile_app", message="hot")
        """,
    )
    sim.set_state("sensor.temp", "30")
    sim.state_change("sensor.temp", "30", "31")
    sim.assert_not_called("notify.mobile_app")


def test_numeric_state_below_crossing(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, numeric_state, service, when

        @automation(id="a", alias="a")
        def a():
            when(numeric_state("sensor.battery", below=10))
            service("notify.mobile_app", message="low battery")
        """,
    )
    sim.set_state("sensor.battery", "50")
    sim.state_change("sensor.battery", "50", "9")
    sim.assert_called("notify.mobile_app")
    sim.state_change("sensor.battery", "9", "5")
    sim.assert_called("notify.mobile_app", times=1)


# ---------------------------------------------------------------------------
# time trigger
# ---------------------------------------------------------------------------


def test_time_trigger_fires_at_configured_time(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, time, when

        @automation(id="a", alias="a")
        def a():
            when(time(at="22:30:00"))
            service("light.turn_off", entity_id="light.hallway")
        """,
    )
    sim.at("2026-07-03 22:29:00")
    sim.assert_not_called("light.turn_off")
    sim.advance(minutes=1)
    sim.assert_called("light.turn_off")


def test_time_trigger_does_not_fire_twice_same_minute(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, time, when

        @automation(id="a", alias="a")
        def a():
            when(time(at="22:30:00"))
            service("light.turn_off", entity_id="light.hallway")
        """,
    )
    sim.at("2026-07-03 22:30:00")
    sim.assert_called("light.turn_off", times=1)
    sim.advance(seconds=1)
    sim.assert_called("light.turn_off", times=1)


# ---------------------------------------------------------------------------
# time_pattern trigger
# ---------------------------------------------------------------------------


def test_time_pattern_fires_every_n_minutes(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, time_pattern, when

        @automation(id="a", alias="a")
        def a():
            when(time_pattern(minutes="/5"))
            service("homeassistant.update_entity", entity_id="sensor.uptime")
        """,
    )
    sim.at("2026-07-03 12:00:00")
    sim.advance(minutes=5)
    sim.assert_called("homeassistant.update_entity", times=1)
    sim.advance(minutes=5)
    sim.assert_called("homeassistant.update_entity", times=2)


def test_time_pattern_every_n_minutes_skips_non_multiples(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, time_pattern, when

        @automation(id="a", alias="a")
        def a():
            when(time_pattern(minutes="/5"))
            service("homeassistant.update_entity", entity_id="sensor.uptime")
        """,
    )
    sim.at("2026-07-03 12:00:00")
    sim.advance(minutes=3)
    sim.assert_not_called("homeassistant.update_entity")


# ---------------------------------------------------------------------------
# sun trigger with configured sunrise/sunset times
# ---------------------------------------------------------------------------


def test_sun_trigger_fires_at_configured_sunset(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, sun, when

        @automation(id="a", alias="a")
        def a():
            when(sun(event="sunset"))
            service("light.turn_on", entity_id="light.porch")
        """,
    )
    sim.set_sun_times(sunrise="06:00:00", sunset="20:00:00")
    sim.at("2026-07-03 19:59:00")
    sim.assert_not_called("light.turn_on")
    sim.advance(minutes=1)
    sim.assert_called("light.turn_on")


def test_sun_trigger_with_offset(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, sun, when

        @automation(id="a", alias="a")
        def a():
            when(sun(event="sunset", offset="-00:30:00"))
            service("light.turn_on", entity_id="light.porch")
        """,
    )
    sim.set_sun_times(sunrise="06:00:00", sunset="20:00:00")
    sim.at("2026-07-03 19:29:00")
    sim.assert_not_called("light.turn_on")
    sim.advance(minutes=1)
    sim.assert_called("light.turn_on")


# ---------------------------------------------------------------------------
# template trigger -- fires only on false->true edge
# ---------------------------------------------------------------------------


def test_template_trigger_fires_on_false_to_true_edge(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, template, when

        @automation(id="a", alias="a")
        def a():
            when(template("{{ states('sensor.temp') | float > 25 }}"))
            service("notify.mobile_app", message="hot")
        """,
    )
    sim.set_state("sensor.temp", "20")
    sim.state_change("sensor.temp", "20", "30")
    sim.assert_called("notify.mobile_app")


def test_template_trigger_does_not_refire_while_true(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, template, when

        @automation(id="a", alias="a")
        def a():
            when(template("{{ states('sensor.temp') | float > 25 }}"))
            service("notify.mobile_app", message="hot")
        """,
    )
    sim.set_state("sensor.temp", "20")
    sim.state_change("sensor.temp", "20", "30")
    sim.assert_called("notify.mobile_app", times=1)
    sim.state_change("sensor.temp", "30", "31")
    sim.assert_called("notify.mobile_app", times=1)


def test_template_trigger_does_not_fire_on_true_to_true(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, template, when

        @automation(id="a", alias="a")
        def a():
            when(template("{{ states('sensor.temp') | float > 25 }}"))
            service("notify.mobile_app", message="hot")
        """,
    )
    sim.set_state("sensor.temp", "30")
    sim.state_change("sensor.temp", "30", "35")
    sim.assert_not_called("notify.mobile_app")


# ---------------------------------------------------------------------------
# event trigger
# ---------------------------------------------------------------------------


def test_event_trigger_fires_on_matching_event(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, event, service, when

        @automation(id="a", alias="a")
        def a():
            when(event("my_custom_event"))
            service("notify.mobile_app", message="event!")
        """,
    )
    sim.fire_event("my_custom_event")
    sim.assert_called("notify.mobile_app")


def test_event_trigger_ignores_other_event_types(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, event, service, when

        @automation(id="a", alias="a")
        def a():
            when(event("my_custom_event"))
            service("notify.mobile_app", message="event!")
        """,
    )
    sim.fire_event("other_event")
    sim.assert_not_called("notify.mobile_app")


# ---------------------------------------------------------------------------
# zone trigger
# ---------------------------------------------------------------------------


def test_zone_trigger_fires_on_enter(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, when, zone

        @automation(id="a", alias="a")
        def a():
            when(zone("person.keaton", zone="zone.home", event="enter"))
            service("notify.mobile_app", message="welcome home")
        """,
    )
    sim.set_state("person.keaton", "not_home")
    sim.state_change("person.keaton", "not_home", "zone.home")
    sim.assert_called("notify.mobile_app")


def test_zone_trigger_ignores_leave_when_configured_for_enter(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, when, zone

        @automation(id="a", alias="a")
        def a():
            when(zone("person.keaton", zone="zone.home", event="enter"))
            service("notify.mobile_app", message="welcome home")
        """,
    )
    sim.set_state("person.keaton", "zone.home")
    sim.state_change("person.keaton", "zone.home", "not_home")
    sim.assert_not_called("notify.mobile_app")
