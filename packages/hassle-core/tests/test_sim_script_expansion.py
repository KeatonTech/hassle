"""Simulator script-call expansion (owner request, task #35).

A direct ``script.<slug>`` service call in real HA runs the callee script and
BLOCKS the caller until it finishes -- including when the callee's
``wait_for_trigger`` times out. The simulator previously recorded such calls
as opaque service calls only (documented v1 scope, cookbook test 8), which
made the owner's actual field bug -- "the notification timed out after 12h and
the automation advanced the day phase as if I'd tapped the button" --
inexpressible in a test. These tests pin the expanded semantics:

- the callee's sequence runs inline, with the call's rendered ``data`` as the
  callee's variables (HA: script fields become run variables);
- the opaque ``script.<slug>`` call is STILL recorded (assert_called keeps
  working);
- the caller resumes only when the callee finishes (waits inside the callee
  suspend the whole chain);
- ``wait_for_trigger`` trigger configs are rendered against the run's
  variables when the step executes (HA renders them; a templated
  ``event_data`` filter like ``{{ tag ~ '_ACTION' }}`` must match fired
  events by its rendered value);
- a plain ``stop`` ends the callee only, the caller continues (HA semantics);
- ``stop(..., error=True)`` in the callee aborts the caller chain too;
- ``script.turn_on`` (fire-and-forget in HA) stays opaque;
- runaway script->script recursion raises a clear error instead of hanging.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _sim_helpers import build_sim

_CALLER_AND_GREETER = """
    from hassle import automation, service, shared_script, state, when

    @shared_script(id="greeter", alias="Greeter")
    def greeter():
        service("light.turn_on", brightness="{{ level }}")

    @automation(id="a", alias="a")
    def a():
        when(state("button.go").to("on"))
        service("script.greeter", level=5)
        service("switch.turn_on", entity_id="switch.done")
"""


def test_direct_script_call_expands_callee_with_data_as_variables(tmp_path: Path) -> None:
    sim = build_sim(tmp_path, _CALLER_AND_GREETER)
    sim.state_change("button.go", "off", "on")
    # The opaque call is still recorded (existing assertion surface)...
    sim.assert_called("script.greeter", level=5)
    # ...AND the callee's sequence ran, with `level` visible as a variable
    # (rendered to a string, matching HA template rendering).
    sim.assert_called("light.turn_on", brightness="5")
    # The caller continued past the call.
    sim.assert_called("switch.turn_on", entity_id="switch.done")


_WAITING_SCRIPT = """
    from hassle import automation, event, minutes, service, shared_script, state, wait_for, when

    @shared_script(id="waiter", alias="Waiter")
    def waiter():
        wait_for(
            event("mobile_app_notification_action", event_data={"action": "{{ tag ~ '_ACTION' }}"}),
            timeout=minutes(10),
        )
        service("notify.phone", message="resumed")

    @automation(id="a", alias="a")
    def a():
        when(state("button.go").to("on"))
        service("script.waiter", tag="goodnight")
        service("switch.turn_on", entity_id="switch.after")
"""


def test_caller_blocks_while_callee_waits(tmp_path: Path) -> None:
    sim = build_sim(tmp_path, _WAITING_SCRIPT)
    sim.state_change("button.go", "off", "on")
    # Suspended inside the callee's wait: nothing after the wait has run,
    # in the callee OR the caller.
    sim.assert_not_called("notify.phone")
    sim.assert_not_called("switch.turn_on")


def test_templated_event_data_filter_matches_by_rendered_value(tmp_path: Path) -> None:
    sim = build_sim(tmp_path, _WAITING_SCRIPT)
    sim.state_change("button.go", "off", "on")
    # A different notification's action id must NOT resume the wait.
    sim.fire_event("mobile_app_notification_action", action="other_ACTION")
    sim.assert_not_called("notify.phone")
    sim.assert_not_called("switch.turn_on")
    # The right one (rendered from `{{ tag ~ '_ACTION' }}` with tag=goodnight) does.
    sim.fire_event("mobile_app_notification_action", action="goodnight_ACTION")
    sim.assert_called("notify.phone", message="resumed")
    sim.assert_called("switch.turn_on", entity_id="switch.after")


def test_callee_wait_timeout_releases_the_caller(tmp_path: Path) -> None:
    """The HA-faithful semantics behind the owner's field bug: the callee's
    wait times out (`continue_on_timeout` defaults true), the callee finishes
    normally, and the CALLER's follow-up steps run -- exactly as if the
    button had been tapped. Guarding against this is bundle logic
    (`stop(error=True)` on the timeout path), not simulator magic."""
    sim = build_sim(tmp_path, _WAITING_SCRIPT)
    sim.state_change("button.go", "off", "on")
    sim.advance(minutes=10)
    sim.assert_called("notify.phone", message="resumed")
    sim.assert_called("switch.turn_on", entity_id="switch.after")


def test_plain_stop_in_callee_ends_callee_only(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, shared_script, state, stop, when

        @shared_script(id="early", alias="Early")
        def early():
            stop("done early")
            service("light.turn_on", entity_id="light.never")

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service("script.early")
            service("switch.turn_on", entity_id="switch.after")
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_not_called("light.turn_on")
    # HA semantics: a script's plain `stop` is a normal completion for the
    # caller -- the caller continues.
    sim.assert_called("switch.turn_on", entity_id="switch.after")


def test_error_stop_in_callee_aborts_the_caller_chain(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, shared_script, state, stop, when

        @shared_script(id="bail", alias="Bail")
        def bail():
            stop("timed out", error=True)

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service("script.bail")
            service("switch.turn_on", entity_id="switch.after")
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_called("script.bail")
    # `error: true` propagates: the caller's follow-up never runs.
    sim.assert_not_called("switch.turn_on")


def test_script_turn_on_stays_opaque(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, shared_script, state, when

        @shared_script(id="greeter", alias="Greeter")
        def greeter():
            service("light.turn_on", entity_id="light.inside")

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service("script.turn_on", entity_id="script.greeter")
        """,
    )
    sim.state_change("button.go", "off", "on")
    sim.assert_called("script.turn_on", entity_id="script.greeter")
    # Fire-and-forget in HA; opaque in the simulator (documented v1.1 scope).
    sim.assert_not_called("light.turn_on")


def test_runaway_script_recursion_raises_clear_error(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, shared_script, state, when

        @shared_script(id="ping", alias="Ping")
        def ping():
            service("script.pong")

        @shared_script(id="pong", alias="Pong")
        def pong():
            service("script.ping")

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            service("script.ping")
        """,
    )
    with pytest.raises(Exception, match="recursion"):
        sim.state_change("button.go", "off", "on")
