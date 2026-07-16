"""wait_for_trigger timeout vs satisfied paths; continue_on_timeout."""

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


def test_wait_for_trigger_accepts_plain_string_timeout(tmp_path: Path) -> None:
    """Regression: `wait_for(..., timeout="00:10:00")` -- a plain HH:MM:SS
    string, exactly what `fixtures/dsl/wait_for_trigger` golden-compiles and
    what `wait_for`'s own `timeout=` docstring passes through verbatim (no
    `normalize_duration`, unlike `for_=`) -- must simulate the same as the
    equivalent `timeout=minutes(10)` dict form, not crash. Found via the
    cookbook recipe `wait_then_lock_reminder` (`fixtures/cookbook/`).
    """
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, wait_for, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.start").to("on"))
            wait_for(
                state("binary_sensor.door").to("off"),
                timeout="00:10:00",
                continue_on_timeout=True,
            )
            service("notify.mobile_app", message="wait completed")
        """,
    )
    sim.set_state("binary_sensor.door", "on")
    sim.state_change("button.start", "off", "on")
    sim.advance(minutes=10)
    sim.assert_called("notify.mobile_app")


def test_wait_for_trigger_resumes_on_matching_event(tmp_path: Path) -> None:
    """§36.2 gap 1: `wait_for(event(...))` must actually resume when the
    matching event fires -- `on_event` previously only ever started NEW runs
    (`_start_or_queue`) and never checked `self._active` for a suspended
    `wait_for_trigger`, so this would otherwise hang forever (never called)."""
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, event, minutes, service, state, wait_for, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.start").to("on"))
            wait_for(event("my_custom_event"), timeout=minutes(10))
            service("notify.mobile_app", message="wait completed")
        """,
    )
    sim.state_change("button.start", "off", "on")
    sim.assert_not_called("notify.mobile_app")
    sim.fire_event("my_custom_event")
    sim.assert_called("notify.mobile_app")


def test_wait_for_trigger_non_matching_event_does_not_resume(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, event, minutes, service, state, wait_for, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.start").to("on"))
            wait_for(event("my_custom_event"), timeout=minutes(10))
            service("notify.mobile_app", message="wait completed")
        """,
    )
    sim.state_change("button.start", "off", "on")
    sim.fire_event("some_other_event")
    sim.assert_not_called("notify.mobile_app")
    sim.fire_event("my_custom_event")
    sim.assert_called("notify.mobile_app")


def test_wait_for_trigger_event_data_filter_must_match(tmp_path: Path) -> None:
    """The trigger's own `event_data=` filter (a subset match, mirroring a
    top-level event trigger's `event_data:` semantics) must be honored on
    resumption too -- an event of the right type but wrong data doesn't
    satisfy the wait."""
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, event, minutes, service, state, wait_for, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.start").to("on"))
            wait_for(
                event("my_custom_event", event_data={"action": "OPEN"}),
                timeout=minutes(10),
            )
            service("notify.mobile_app", message="wait completed")
        """,
    )
    sim.state_change("button.start", "off", "on")
    sim.fire_event("my_custom_event", action="CLOSE")
    sim.assert_not_called("notify.mobile_app")
    sim.fire_event("my_custom_event", action="OPEN")
    sim.assert_called("notify.mobile_app")


def test_wait_variable_populated_on_event_resumption(tmp_path: Path) -> None:
    """§36.2 gap 2: `wait.trigger.event.*` must be populated in the template
    context after a satisfied event wait -- mirrors HA's real `wait` variable
    shape (event_type + data), plus `wait.completed`."""
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, event, minutes, service, state, var, wait_for, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.start").to("on"))
            wait_for(event("my_custom_event"), timeout=minutes(10))
            service(
                "notify.mobile_app",
                message=var("wait.trigger.event.data.action"),
                completed=var("wait.completed"),
                event_type=var("wait.trigger.event.event_type"),
            )
        """,
    )
    sim.state_change("button.start", "off", "on")
    sim.fire_event("my_custom_event", action="OPEN_BLINDS")
    sim.assert_called(
        "notify.mobile_app",
        message="OPEN_BLINDS",
        completed="True",
        event_type="my_custom_event",
    )


def test_wait_variable_reflects_timeout(tmp_path: Path) -> None:
    """Timeout path: `wait.completed` is false and `wait.trigger` is none,
    honoring `continue_on_timeout`."""
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, event, minutes, service, state, var, wait_for, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.start").to("on"))
            wait_for(event("my_custom_event"), timeout=minutes(10), continue_on_timeout=True)
            service(
                "notify.mobile_app",
                completed=var("wait.completed"),
                trigger_is_none=var("wait.trigger is none"),
            )
        """,
    )
    sim.state_change("button.start", "off", "on")
    sim.advance(minutes=10)
    sim.assert_called("notify.mobile_app", completed="False", trigger_is_none="True")


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
