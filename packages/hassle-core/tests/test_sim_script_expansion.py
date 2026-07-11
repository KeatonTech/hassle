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


def test_field_defaults_seed_callee_variables_when_omitted(tmp_path: Path) -> None:
    """HA seeds a script's field `default:`s as run variables when the caller
    omits them -- `adjust_tdbu_blind(position=...)` relying on
    `peek_distance`'s default 30 must render 30, not crash on an undefined
    name. An explicitly-passed value still wins over the default."""
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, shared_script, state, when

        @shared_script(
            id="mover",
            alias="Mover",
            fields={"position": {"selector": {"number": {}}, "default": 30}},
        )
        def mover():
            service("cover.set_cover_position", position="{{ position }}")

        @automation(id="a", alias="a")
        def a():
            when(state("button.default").to("on"))
            service("script.mover")

        @automation(id="b", alias="b")
        def b():
            when(state("button.explicit").to("on"))
            service("script.mover", position=75)
        """,
    )
    sim.state_change("button.default", "off", "on")
    sim.assert_called("cover.set_cover_position", position="30")
    sim.state_change("button.explicit", "off", "on")
    sim.assert_called("cover.set_cover_position", position="75")


def test_time_trigger_at_entity_resolves_the_entitys_state(tmp_path: Path) -> None:
    """HA `time` triggers accept `at: <input_datetime/sensor entity>` (the
    owner's guest-room wakeup automation). The simulator crashed trying to
    parse the entity id as HH:MM; it must resolve the entity's state as the
    trigger time instead, and treat an unset/unparseable state as
    never-firing rather than erroring."""
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, when
        from hassle.compiler.triggers import time

        @automation(id="a", alias="a")
        def a():
            when(time(at="input_datetime.wakeup"))
            service("light.turn_on", entity_id="light.bedroom")
        """,
    )
    # Unset entity: advancing must neither crash nor fire.
    sim.at("2026-07-11 06:00:00")
    sim.advance(minutes=1)
    sim.assert_not_called("light.turn_on")
    sim.set_state("input_datetime.wakeup", "06:30:00")
    sim.advance(minutes=28)
    sim.assert_not_called("light.turn_on")
    sim.advance(minutes=1)
    sim.assert_called("light.turn_on", entity_id="light.bedroom")


def test_state_condition_with_list_of_states_matches_any(tmp_path: Path) -> None:
    """HA state conditions accept `state: [a, b]` (match any) -- exactly what
    M20's `.state.in_([...])` and `state(x).is_([...])` compile to. The
    evaluator compared the current state to the LIST itself, silently false
    forever (owner field report, task #35)."""
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, if_then, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("button.go").to("on"))
            with if_then(state("input_select.phase").is_(["Sleeping", "Unoccupied"])):
                service("light.turn_on", entity_id="light.bedroom")
        """,
    )
    sim.set_state("input_select.phase", "Sleeping")
    sim.state_change("button.go", "off", "on")
    sim.assert_called("light.turn_on", times=1, entity_id="light.bedroom")
    sim.set_state("input_select.phase", "Daytime")
    sim.state_change("button.go", "on", "off")
    sim.state_change("button.go", "off", "on")
    sim.assert_called("light.turn_on", times=1)


def test_parallel_branch_error_stop_fails_the_step_and_plain_stop_stays_isolated(
    tmp_path: Path,
) -> None:
    """PR #27 review finding: `parallel` shares the run ctx and discarded
    branch results, so (a) an error-stop in a branch never failed the caller
    (real HA fails the parallel step) and (b) the sticky flag could turn a
    later PLAIN stop into a spurious error abort."""
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, parallel, service, shared_script, state, stop, when

        @shared_script(id="branch_error", alias="Branch error")
        def branch_error():
            with parallel() as p:
                with p.branch():
                    stop("branch failed", error=True)
                with p.branch():
                    service("light.turn_on", entity_id="light.other_branch")

        @automation(id="a", alias="a")
        def a():
            when(state("button.err").to("on"))
            service("script.branch_error")
            service("switch.turn_on", entity_id="switch.after_error")

        @shared_script(id="branch_plain", alias="Branch plain")
        def branch_plain():
            with parallel() as p:
                with p.branch():
                    stop("branch done")

        @automation(id="b", alias="b")
        def b():
            when(state("button.plain").to("on"))
            service("script.branch_plain")
            service("switch.turn_on", entity_id="switch.after_plain")
        """,
    )
    sim.state_change("button.err", "off", "on")
    # Branch isolation still holds for the OTHER branch...
    sim.assert_called("light.turn_on", entity_id="light.other_branch")
    # ...but a branch's error-stop fails the parallel step, so the caller aborts.
    sim.assert_not_called("switch.turn_on", entity_id="switch.after_error")
    sim.state_change("button.plain", "off", "on")
    # A PLAIN stop in a branch stays isolated (HA parallel semantics): the
    # step succeeds and script b's caller continues normally.
    sim.assert_called("switch.turn_on", entity_id="switch.after_plain")


def test_recursion_error_message_has_what_where_fix() -> None:
    """R6: the error surface is product surface -- pin the full wording, not
    just a substring (PR #27 review finding)."""
    from hassle.testing.errors import ScriptRecursionError

    message = str(ScriptRecursionError("ping", 10))
    assert message == (
        "Simulating this run expanded nested script calls more than 10 levels deep "
        "(last callee: `script.ping`) -- almost certainly scripts calling each other "
        "in a cycle (recursion), which would never terminate in real HA either. "
        "Fix: break the cycle so no script (transitively) calls itself, or "
        "restructure the shared logic into one script both callers use."
    )


def test_state_trigger_with_list_from_to_filters_matches_any(tmp_path: Path) -> None:
    """Decompiled state triggers carry LIST from/to filters
    (`state([x]).is_(["off"]).to(["on"])`); the matcher compared the state
    string to the list itself, so such automations never fired at all
    (owner field report, task #35)."""
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state(["schedule.bedtime"]).is_(["off"]).to(["on"]))
            service("light.turn_on", entity_id="light.bedroom")
        """,
    )
    sim.state_change("schedule.bedtime", "off", "on")
    sim.assert_called("light.turn_on", times=1)
    # A non-matching transition still doesn't fire.
    sim.state_change("schedule.bedtime", "on", "off")
    sim.assert_called("light.turn_on", times=1)
