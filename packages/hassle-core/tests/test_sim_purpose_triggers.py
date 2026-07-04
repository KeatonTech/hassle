"""DESIGN §10.1 / MILESTONES M4: purpose-specific triggers (2026.7+) are
unsupported for trigger *evaluation* in v1 -- too large a vocabulary to
reimplement faithfully. `sim.fire(automation, trigger_ctx={...})` is the
documented path, so *no automation is untestable*, some just skip trigger
evaluation. This file proves a purpose-trigger automation is fully testable
via `fire`.
"""

from __future__ import annotations

from pathlib import Path

from _sim_helpers import build_sim


def test_purpose_trigger_automation_testable_via_fire(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import area, automation, minutes, on, service, when

        @automation(id="a", alias="a")
        def a():
            when(on("motion.detected", target=area("office"), behavior="first", for_=minutes(5)))
            service("light.turn_on", entity_id="light.office")
        """,
    )
    # The purpose-trigger vocabulary (motion.detected et al.) is instance data
    # HA defines server-side -- the simulator does not evaluate it. `fire`
    # skips straight to running the action sequence as if the trigger had
    # matched, with `trigger_ctx` available under `trigger.*` in templates.
    sim.fire("automation:a", trigger_ctx={"target": {"area_id": "office"}})
    sim.assert_called("light.turn_on", entity_id="light.office")


def test_purpose_trigger_never_fires_from_ordinary_state_changes(tmp_path: Path) -> None:
    """A purpose trigger is *not* evaluated by the simulator's normal trigger
    engine -- only `fire()` runs it. An unrelated state_change must not
    accidentally trigger it (proves v1 correctly treats it as unsupported for
    evaluation rather than silently approximating it as a state trigger)."""
    sim = build_sim(
        tmp_path,
        """
        from hassle import area, automation, on, service, when

        @automation(id="a", alias="a")
        def a():
            when(on("motion.detected", target=area("office")))
            service("light.turn_on", entity_id="light.office")
        """,
    )
    sim.state_change("binary_sensor.office_motion", "off", "on")
    sim.assert_not_called("light.turn_on")


def test_purpose_condition_automation_testable_via_fire(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, event, met, only_if, service, when

        @automation(id="a", alias="a")
        def a():
            when(event("my_event"))
            only_if(met("climate.is_target_temperature"))
            service("notify.mobile_app", message="target reached")
        """,
    )
    # `met(...)` purpose conditions are likewise unevaluated by the simulator
    # in v1; firing directly bypasses trigger AND condition evaluation, since
    # a fired run is meant to exercise the action sequence deterministically.
    sim.fire("automation:a")
    sim.assert_called("notify.mobile_app", message="target reached")
