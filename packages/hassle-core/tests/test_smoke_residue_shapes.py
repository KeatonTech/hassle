"""Smoke-test task #8 -- residue coverage, round 2, from the owner's live bundle.

Round 1 (``test_smoke_real_world_shapes.py``, docs/ha-api-notes.md §19) fixed three
mundane UI-authored shapes. A second live smoke test against a real 2026.7 Home
Assistant bundle (101 objects) surfaced 12 more granular ``raw_action`` fallbacks,
tracing to four more root causes -- all ordinary shapes the HA UI writes on every
save:

1. ``data_template`` on a service action (the legacy templated-data key; HA still
   stores it verbatim, distinct from ``data``).
2. List-valued ``state`` **condition** fields (``entity_id``/``state``) -- the
   condition-side mirror of round 1's trigger fix, including nested inside
   if/choose blocks.
3. Per-step ``alias``/``enabled`` (the UI names and toggles individual steps).
4. Container recursion tolerance: if/then/else, choose, parallel, and
   wait_for_trigger must decompile their inner steps through the same improved
   path, so a container is never raw'd merely because a child carries one of the
   above shapes.

Each gap gets a builder-level unit test (this file) plus a new corpus fixture
under ``fixtures/configs/`` that the existing parametrized round-trip
(``test_roundtrip_corpus.py``) and coverage (``test_decompile_coverage.py``) tests
pick up automatically. I3 (round-trip) requires ``data_template`` and list-valued
condition fields be preserved byte-stable -- never folded/normalized away.
"""

from __future__ import annotations

from hassle.compiler.actions import delay, service
from hassle.compiler.builders import DelayAction, ServiceAction, state
from hassle.compiler.control_flow import choose, if_then, parallel
from hassle.compiler.recording import recording
from hassle.decompiler.actions import decompile_action
from hassle.decompiler.exprs import decompile_condition

# ---------------------------------------------------------------------------
# Gap 1 -- action `data_template` field.
# ---------------------------------------------------------------------------


def test_service_action_omits_data_template_by_default() -> None:
    body = ServiceAction("climate.set_temperature", target={"entity_id": "climate.x"}).to_action()
    assert "data_template" not in body


def test_service_action_emits_data_template_verbatim_not_folded_into_data() -> None:
    body = ServiceAction(
        "climate.set_temperature",
        target={"entity_id": "climate.living_room"},
        data_template={"temperature": "{{ states('input_number.target_temp') | float }}"},
    ).to_action()
    assert body == {
        "action": "climate.set_temperature",
        "target": {"entity_id": "climate.living_room"},
        "data_template": {"temperature": "{{ states('input_number.target_temp') | float }}"},
    }
    assert "data" not in body


def test_service_verb_records_data_template_kwarg() -> None:
    with recording() as rec:
        service(
            "climate.set_temperature",
            target={"entity_id": "climate.x"},
            data_template={"temperature": "{{ 21 }}"},
        )
    (action,) = rec.actions
    assert action.body == {
        "action": "climate.set_temperature",
        "target": {"entity_id": "climate.x"},
        "data_template": {"temperature": "{{ 21 }}"},
    }


def test_decompile_action_with_data_template_round_trips_through_service_call() -> None:
    body = {
        "action": "climate.set_temperature",
        "target": {"entity_id": "climate.living_room"},
        "data_template": {"temperature": "{{ states('input_number.target_temp') | float }}"},
    }
    (src,) = decompile_action(body)
    assert src.startswith("service(")
    assert "raw_action" not in src
    assert "data_template={'temperature': " in src
    assert "'data':" not in src


def test_decompile_action_without_data_template_omits_kwarg() -> None:
    body = {
        "action": "climate.set_temperature",
        "target": {"entity_id": "climate.living_room"},
        "data": {"temperature": 21},
    }
    (src,) = decompile_action(body)
    assert "data_template" not in src


# ---------------------------------------------------------------------------
# Gap 2 -- list-valued state CONDITION fields.
# ---------------------------------------------------------------------------


def test_state_condition_accepts_list_entity_id_and_state() -> None:
    cond = state(["input_boolean.x"]).is_(["on"]).to_condition()
    assert cond == {"condition": "state", "entity_id": ["input_boolean.x"], "state": ["on"]}


def test_decompile_state_condition_singleton_list_stays_a_list() -> None:
    body = {"condition": "state", "entity_id": ["input_boolean.x"], "state": ["on"]}
    src = decompile_condition(body)
    assert src is not None
    assert "raw_condition" not in src
    assert src == "state(['input_boolean.x']).is_(['on'])"


def test_decompile_state_condition_multi_entry_list() -> None:
    body = {
        "condition": "state",
        "entity_id": ["binary_sensor.hall_motion", "binary_sensor.kitchen_motion"],
        "state": ["on", "detected"],
    }
    src = decompile_condition(body)
    assert src is not None
    assert "raw_condition" not in src
    assert (
        src == "state(['binary_sensor.hall_motion', 'binary_sensor.kitchen_motion'])"
        ".is_(['on', 'detected'])"
    )


def test_decompile_state_condition_list_valued_nested_in_if_action() -> None:
    body = {
        "if": [{"condition": "state", "entity_id": ["input_boolean.guest_mode"], "state": ["on"]}],
        "then": [{"action": "light.turn_on", "target": {"entity_id": "light.guest_room"}}],
    }
    src = "\n".join(decompile_action(body))
    assert "raw_action" not in src
    assert "raw_condition" not in src
    assert "state(['input_boolean.guest_mode']).is_(['on'])" in src


def test_decompile_state_condition_list_valued_nested_in_choose_branch() -> None:
    body = {
        "choose": [
            {
                "conditions": [
                    {
                        "condition": "state",
                        "entity_id": ["binary_sensor.hall_motion"],
                        "state": ["on"],
                    }
                ],
                "sequence": [{"action": "light.turn_on", "target": {"entity_id": "light.hallway"}}],
            }
        ]
    }
    src = "\n".join(decompile_action(body))
    assert "raw_action" not in src
    assert "raw_condition" not in src
    assert "state(['binary_sensor.hall_motion']).is_(['on'])" in src


# ---------------------------------------------------------------------------
# Gap 3 -- per-step `alias`/`enabled`.
# ---------------------------------------------------------------------------


def test_service_action_emits_alias_and_enabled() -> None:
    body = ServiceAction(
        "light.turn_on",
        target={"entity_id": "light.bedroom"},
        alias="Turn on bedroom",
        enabled=False,
    ).to_action()
    assert body == {
        "action": "light.turn_on",
        "target": {"entity_id": "light.bedroom"},
        "alias": "Turn on bedroom",
        "enabled": False,
    }


def test_service_action_omits_alias_and_enabled_by_default() -> None:
    body = ServiceAction("light.turn_on", target={"entity_id": "light.x"}).to_action()
    assert "alias" not in body
    assert "enabled" not in body


def test_delay_action_emits_alias_and_enabled() -> None:
    body = DelayAction(seconds=5, alias="Wait a bit", enabled=True).to_action()
    assert body == {"delay": {"seconds": 5}, "alias": "Wait a bit", "enabled": True}


def test_service_verb_records_alias_and_enabled_kwargs() -> None:
    with recording() as rec:
        service("light.turn_on", target={"entity_id": "light.x"}, alias="Step name", enabled=False)
    (action,) = rec.actions
    assert action.body["alias"] == "Step name"
    assert action.body["enabled"] is False


def test_delay_verb_records_alias_and_enabled_kwargs() -> None:
    with recording() as rec:
        delay(seconds=5, alias="Wait step", enabled=True)
    (action,) = rec.actions
    assert action.body == {"delay": {"seconds": 5}, "alias": "Wait step", "enabled": True}


def test_decompile_service_call_with_alias_and_enabled() -> None:
    body = {
        "alias": "Turn on bedroom",
        "action": "light.turn_on",
        "target": {"entity_id": "light.bedroom"},
    }
    (src,) = decompile_action(body)
    assert "raw_action" not in src
    assert "alias='Turn on bedroom'" in src


def test_decompile_delay_with_alias_and_enabled() -> None:
    body = {"alias": "Wait a bit", "delay": {"seconds": 5}, "enabled": True}
    (src,) = decompile_action(body)
    assert "raw_action" not in src
    assert src.startswith("delay(")
    assert "alias='Wait a bit'" in src
    assert "enabled=True" in src


def test_decompile_service_call_disabled_step() -> None:
    body = {
        "alias": "Disabled cleanup step",
        "action": "light.turn_off",
        "target": {"entity_id": "light.bedroom"},
        "enabled": False,
    }
    (src,) = decompile_action(body)
    assert "raw_action" not in src
    assert "enabled=False" in src


def test_if_then_context_manager_accepts_alias_kwarg() -> None:
    with recording() as rec:
        with if_then(state("input_boolean.x").is_("on"), alias="Guard block"):
            service("light.turn_on", target={"entity_id": "light.x"})
    (action,) = rec.actions
    assert action.body["alias"] == "Guard block"
    assert action.body["if"] == [{"condition": "state", "entity_id": "input_boolean.x", "state": "on"}]


def test_choose_context_manager_accepts_alias_kwarg() -> None:
    with recording() as rec:
        with choose(alias="Pick a branch") as c:
            with c.when_(state("input_boolean.x").is_("on")):
                service("light.turn_on", target={"entity_id": "light.x"})
    (action,) = rec.actions
    assert action.body["alias"] == "Pick a branch"
    assert "choose" in action.body


def test_parallel_context_manager_accepts_alias_kwarg() -> None:
    with recording() as rec:
        with parallel(alias="Do both"):
            service("light.turn_on", target={"entity_id": "light.a"})
            service("light.turn_on", target={"entity_id": "light.b"})
    (action,) = rec.actions
    assert action.body["alias"] == "Do both"
    assert "parallel" in action.body


def test_decompile_if_then_with_alias_round_trips_to_context_manager_kwarg() -> None:
    body = {
        "alias": "Guard block",
        "if": [{"condition": "state", "entity_id": "input_boolean.x", "state": "on"}],
        "then": [{"action": "light.turn_on", "target": {"entity_id": "light.x"}}],
    }
    src = "\n".join(decompile_action(body))
    assert "raw_action" not in src
    assert "with if_then(" in src
    assert "alias='Guard block'" in src


# ---------------------------------------------------------------------------
# Gap 4 -- container recursion tolerance: a nested child carrying any of the
# above shapes must not force the whole container to raw_action.
# ---------------------------------------------------------------------------


def test_if_else_container_not_raw_when_children_carry_metadata_and_data_template() -> None:
    body = {
        "if": [{"condition": "state", "entity_id": ["input_boolean.away_mode"], "state": ["on"]}],
        "then": [
            {
                "alias": "Notify away",
                "action": "notify.mobile_app",
                "metadata": {},
                "data": {"message": "hi"},
            }
        ],
        "else": [
            {
                "alias": "Set warm light",
                "action": "light.turn_on",
                "target": {"entity_id": "light.entryway"},
                "data_template": {"brightness": "{{ 128 }}"},
                "enabled": True,
            }
        ],
    }
    src = "\n".join(decompile_action(body))
    assert "raw_action" not in src
    assert "raw_condition" not in src
    assert "with if_then(" in src
    assert "with else_then():" in src
    assert "metadata={}" in src
    assert "data_template={'brightness': '{{ 128 }}'}" in src
    assert "alias='Notify away'" in src
    assert "alias='Set warm light'" in src
    assert "enabled=True" in src


def test_parallel_container_not_raw_when_branch_carries_alias_and_metadata() -> None:
    body = {
        "parallel": [
            {
                "sequence": [
                    {"alias": "Chime", "action": "notify.chime", "metadata": {}, "enabled": True}
                ]
            },
            {
                "sequence": [
                    {
                        "choose": [
                            {
                                "conditions": [
                                    {
                                        "condition": "state",
                                        "entity_id": ["binary_sensor.hall_motion"],
                                        "state": ["on"],
                                    }
                                ],
                                "sequence": [
                                    {
                                        "alias": "Hallway on",
                                        "action": "light.turn_on",
                                        "metadata": {},
                                        "target": {"entity_id": "light.hallway"},
                                    }
                                ],
                            }
                        ]
                    }
                ]
            },
        ]
    }
    src = "\n".join(decompile_action(body))
    assert "raw_action" not in src
    assert "raw_condition" not in src
    assert "with parallel():" in src
    assert "with choose() as c:" in src
    assert "alias='Chime'" in src
    assert "alias='Hallway on'" in src


def test_wait_for_trigger_container_not_raw_with_list_valued_state_trigger() -> None:
    body = {
        "wait_for_trigger": [{"trigger": "state", "entity_id": ["binary_sensor.front_door"], "to": ["off"]}],
        "timeout": {"minutes": 5},
    }
    (src,) = decompile_action(body)
    assert "raw_action" not in src
    assert src.startswith("wait_for(")
    assert "state(['binary_sensor.front_door']).to(['off'])" in src
