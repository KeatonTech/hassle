"""The `trigger.*` namespace for state-triggered runs (DESIGN §10.1).

Every state-triggered run used to start with an EMPTY trigger context, so
`trigger.id` was undefined, `condition: trigger` never matched, and downstream
bundles had to ban `trigger.*` in automation bodies outright. Blueprints branch
on `trigger.id` as a matter of idiom, so a state trigger now populates the same
namespace HA does: `id` (the trigger's explicit `id:`, else `str(index)`),
`idx`, `platform`, `entity_id`, and `from_state`/`to_state` as
attribute-accessible objects exposing `.state` and `.attributes`.

`for:`-held triggers carry the SAME context when the hold finally expires --
the context is captured at match time, not rebuilt at fire time.
"""

from __future__ import annotations

from pathlib import Path

from _sim_helpers import build_sim


def test_state_trigger_populates_id_idx_platform_and_entity_id(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service, state, when

        @automation(id="a", alias="a")
        def a():
            when(state("binary_sensor.motion").to("on"))
            service(
                "notify.persistent_notification",
                message="{{ trigger.id }}|{{ trigger.idx }}|"
                "{{ trigger.platform }}|{{ trigger.entity_id }}",
            )
        """,
    )
    sim.state_change("binary_sensor.motion", "off", "on")
    # No explicit `id:` on the trigger -> HA's positional fallback, `"0"`.
    sim.assert_called(
        "notify.persistent_notification",
        message="0|0|state|binary_sensor.motion",
    )


def test_explicit_trigger_id_wins_over_the_positional_fallback(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import raw_automation

        @raw_automation(id="a")
        def a():
            return {
                "alias": "a",
                "triggers": [
                    {"trigger": "state", "entity_id": "binary_sensor.a", "to": "on"},
                    {"trigger": "state", "entity_id": "binary_sensor.b", "to": "on", "id": "beta"},
                ],
                "actions": [
                    {
                        "action": "notify.persistent_notification",
                        "data": {"message": "{{ trigger.id }}/{{ trigger.idx }}"},
                    }
                ],
            }
        """,
    )
    sim.state_change("binary_sensor.b", "off", "on")
    sim.assert_called("notify.persistent_notification", message="beta/1")
    sim.state_change("binary_sensor.a", "off", "on")
    sim.assert_called("notify.persistent_notification", message="0/0")


def test_from_state_and_to_state_expose_state_and_attributes(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import raw_automation

        @raw_automation(id="a")
        def a():
            return {
                "alias": "a",
                "triggers": [{"trigger": "state", "entity_id": "sensor.paddle"}],
                "actions": [
                    {
                        "action": "notify.persistent_notification",
                        "data": {
                            "message": "{{ trigger.from_state.state }}->"
                            "{{ trigger.to_state.state }}:"
                            "{{ trigger.to_state.attributes.event_type }}:"
                            "{{ trigger.to_state.entity_id }}",
                        },
                    }
                ],
            }
        """,
    )
    sim.state_change("sensor.paddle", "idle", "up", {"event_type": "single_press"})
    sim.assert_called(
        "notify.persistent_notification",
        message="idle->up:single_press:sensor.paddle",
    )


def test_condition_trigger_matches_the_firing_trigger_id(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import raw_automation

        @raw_automation(id="a")
        def a():
            return {
                "alias": "a",
                "triggers": [
                    {"trigger": "state", "entity_id": "sensor.p", "to": "up", "id": "up"},
                    {"trigger": "state", "entity_id": "sensor.p", "to": "down", "id": "down"},
                ],
                "actions": [
                    {
                        "choose": [
                            {
                                "conditions": [{"condition": "trigger", "id": "up"}],
                                "sequence": [{"action": "light.turn_on"}],
                            },
                            {
                                "conditions": [{"condition": "trigger", "id": "down"}],
                                "sequence": [{"action": "light.turn_off"}],
                            },
                        ]
                    }
                ],
            }
        """,
    )
    sim.state_change("sensor.p", "idle", "down")
    sim.assert_called("light.turn_off")
    sim.assert_not_called("light.turn_on")


def test_for_held_trigger_carries_the_same_context_when_it_finally_fires(
    tmp_path: Path,
) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import raw_automation

        @raw_automation(id="a")
        def a():
            return {
                "alias": "a",
                "triggers": [
                    {
                        "trigger": "state",
                        "entity_id": "binary_sensor.motion",
                        "to": "on",
                        "id": "held",
                        "for": {"minutes": 5},
                    }
                ],
                "actions": [
                    {
                        "action": "notify.persistent_notification",
                        "data": {
                            "message": "{{ trigger.id }}:{{ trigger.entity_id }}:"
                            "{{ trigger.from_state.state }}->{{ trigger.to_state.state }}:"
                            "{{ trigger.to_state.attributes.zone }}",
                        },
                    }
                ],
            }
        """,
    )
    sim.state_change("binary_sensor.motion", "off", "on", {"zone": "hall"})
    sim.assert_not_called("notify.persistent_notification")
    sim.advance(minutes=5)
    sim.assert_called(
        "notify.persistent_notification",
        message="held:binary_sensor.motion:off->on:hall",
    )


def test_numeric_state_and_zone_triggers_carry_the_state_namespace(tmp_path: Path) -> None:
    sim = build_sim(
        tmp_path,
        """
        from hassle import raw_automation

        @raw_automation(id="a")
        def a():
            return {
                "alias": "a",
                "triggers": [
                    {"trigger": "numeric_state", "entity_id": "sensor.temp", "above": 20},
                ],
                "actions": [
                    {
                        "action": "notify.persistent_notification",
                        "data": {
                            "message": "{{ trigger.platform }}:{{ trigger.id }}:"
                            "{{ trigger.entity_id }}:{{ trigger.to_state.state }}",
                        },
                    }
                ],
            }
        """,
    )
    sim.state_change("sensor.temp", "18", "22")
    sim.assert_called(
        "notify.persistent_notification",
        message="numeric_state:0:sensor.temp:22",
    )


def test_event_trigger_keeps_its_event_namespace_and_gains_an_id(tmp_path: Path) -> None:
    # `trigger.event.data.*` is long-standing behavior and must not move.
    sim = build_sim(
        tmp_path,
        """
        from hassle import raw_automation

        @raw_automation(id="a")
        def a():
            return {
                "alias": "a",
                "triggers": [{"trigger": "event", "event_type": "doorbell", "id": "ring"}],
                "actions": [
                    {
                        "action": "notify.persistent_notification",
                        "data": {
                            "message": "{{ trigger.id }}:{{ trigger.platform }}:"
                            "{{ trigger.event.data.who }}",
                        },
                    }
                ],
            }
        """,
    )
    sim.fire_event("doorbell", who="kai")
    sim.assert_called("notify.persistent_notification", message="ring:event:kai")


def test_sim_fire_trigger_ctx_still_wins(tmp_path: Path) -> None:
    # `sim.fire(..., trigger_ctx=...)` is the documented escape hatch for
    # trigger types the simulator does not evaluate; it is unaffected.
    sim = build_sim(
        tmp_path,
        """
        from hassle import automation, service

        @automation(id="a", alias="a")
        def a():
            service("notify.persistent_notification", message="{{ trigger.target.area_id }}")
        """,
    )
    sim.fire("automation:a", trigger_ctx={"target": {"area_id": "office"}})
    sim.assert_called("notify.persistent_notification", message="office")
