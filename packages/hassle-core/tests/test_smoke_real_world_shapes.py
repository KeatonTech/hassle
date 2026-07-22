"""Smoke test -- real-world decompiler/builder coverage.

A live smoke test against a real 2026.7 Home Assistant instance
surfaced 118 granular ``raw_*`` decompiler fallbacks across 101 real objects,
tracing to three root causes -- all mundane, extremely common shapes the HA UI
actually writes that the (hand-authored, docs-derived) synthetic corpus never
happened to exercise:

1. The HA UI stamps ``"metadata": {}`` on every action it saves.
2. The HA UI stores ``entity_id``/``to``/``from`` on a ``state``/``numeric_state``
   trigger as *lists*, even for a single entity/value.
3. A ``time`` trigger's ``weekday`` field (day-abbreviation list), and ``at`` as
   an entity reference (``input_datetime.x``) rather than a literal time string.

Each gap gets: a builder-level unit test (this file), plus a new corpus fixture
under ``fixtures/configs/`` that the existing parametrized round-trip
(``test_roundtrip_corpus.py``) and coverage (``test_decompile_coverage.py``)
tests pick up automatically. The round-trip invariant
(compile(decompile(x)) == x) requires the empty ``metadata: {}``
be preserved byte-stable -- dropping/eliding it would hash-drift every
UI-authored action forever.
"""

from __future__ import annotations

from hassle.compiler.actions import service
from hassle.compiler.builders import ServiceAction, state
from hassle.compiler.recording import recording
from hassle.compiler.triggers import time
from hassle.decompiler.actions import decompile_action
from hassle.decompiler.exprs import decompile_trigger

# ---------------------------------------------------------------------------
# Gap 1 -- action `metadata` field.
# ---------------------------------------------------------------------------


def test_service_action_omits_metadata_by_default() -> None:
    body = ServiceAction("light.turn_on", target={"entity_id": "light.x"}).to_action()
    assert "metadata" not in body


def test_service_action_emits_metadata_when_present_including_empty() -> None:
    body = ServiceAction(
        "light.turn_on",
        target={"entity_id": "light.x"},
        data={"brightness_pct": 50},
        metadata={},
    ).to_action()
    assert body == {
        "action": "light.turn_on",
        "target": {"entity_id": "light.x"},
        "data": {"brightness_pct": 50},
        "metadata": {},
    }


def test_service_action_emits_nonempty_metadata_verbatim() -> None:
    body = ServiceAction(
        "light.turn_on",
        target={"entity_id": "light.x"},
        metadata={"secondary": True},
    ).to_action()
    assert body["metadata"] == {"secondary": True}


def test_service_verb_records_metadata_kwarg() -> None:
    with recording() as rec:
        service("light.turn_on", target={"entity_id": "light.x"}, metadata={})
    (action,) = rec.actions
    assert action.body == {
        "action": "light.turn_on",
        "target": {"entity_id": "light.x"},
        "metadata": {},
    }


def test_decompile_action_with_metadata_round_trips_through_service_call() -> None:
    body = {
        "action": "light.turn_on",
        "metadata": {},
        "data": {"brightness_pct": 50, "transition": 4},
        "target": {"entity_id": "light.x"},
    }
    (src,) = decompile_action(body)
    assert src.startswith("service(")
    assert "raw_action" not in src
    assert "metadata={}" in src


def test_decompile_action_without_metadata_omits_kwarg() -> None:
    body = {
        "action": "light.turn_on",
        "data": {"brightness_pct": 50},
        "target": {"entity_id": "light.x"},
    }
    (src,) = decompile_action(body)
    assert "metadata" not in src


# ---------------------------------------------------------------------------
# Gap 2 -- list-valued state/numeric_state trigger fields.
# ---------------------------------------------------------------------------


def test_state_trigger_accepts_list_entity_id() -> None:
    trig = state(["binary_sensor.x"])
    assert trig.to_trigger() == {"trigger": "state", "entity_id": ["binary_sensor.x"]}


def test_state_trigger_singleton_list_to_from_not_normalized_to_scalar() -> None:
    trig = state(["binary_sensor.x"]).is_(["off"]).to(["on"])
    body = trig.to_trigger()
    assert body["entity_id"] == ["binary_sensor.x"]
    assert body["from"] == ["off"]
    assert body["to"] == ["on"]


def test_state_trigger_multi_entry_lists() -> None:
    trig = state(["binary_sensor.hall_motion", "binary_sensor.kitchen_motion"]).to(
        ["on", "detected"]
    )
    body = trig.to_trigger()
    assert body["entity_id"] == ["binary_sensor.hall_motion", "binary_sensor.kitchen_motion"]
    assert body["to"] == ["on", "detected"]


def test_decompile_state_trigger_singleton_list_stays_a_list() -> None:
    body = {
        "trigger": "state",
        "entity_id": ["binary_sensor.x"],
        "to": ["on"],
        "from": ["off"],
    }
    src = decompile_trigger(body)
    assert src is not None
    assert "raw_trigger" not in src
    # Entity position (DESIGN §7.3): entity_id renders through
    # the registry accessor; `to`/`from` are state *values*, never entity
    # positions, so they stay plain strings even when list-valued.
    assert src == "state([e.binary_sensor.x]).is_(['off']).to(['on'])"


def test_decompile_state_trigger_multi_entry_list() -> None:
    body = {
        "trigger": "state",
        "entity_id": ["binary_sensor.hall_motion", "binary_sensor.kitchen_motion"],
        "to": ["on", "detected"],
    }
    src = decompile_trigger(body)
    assert src is not None
    assert (
        src == "state([e.binary_sensor.hall_motion, e.binary_sensor.kitchen_motion])"
        ".to(['on', 'detected'])"
    )


def test_numeric_state_trigger_accepts_list_entity_id() -> None:
    from hassle.compiler.triggers import numeric_state

    trig = numeric_state(["sensor.outdoor_temperature"], above=25)
    assert trig.to_trigger() == {
        "trigger": "numeric_state",
        "entity_id": ["sensor.outdoor_temperature"],
        "above": 25,
    }


def test_decompile_numeric_state_trigger_list_entity_id() -> None:
    body = {
        "trigger": "numeric_state",
        "entity_id": ["sensor.living_room_temp", "sensor.bedroom_temp"],
        "above": 20,
    }
    src = decompile_trigger(body)
    assert src is not None
    assert "raw_trigger" not in src
    assert src == "numeric_state([e.sensor.living_room_temp, e.sensor.bedroom_temp], above=20)"


# ---------------------------------------------------------------------------
# Gap 3 -- time trigger `weekday` + `at` as an entity reference.
# ---------------------------------------------------------------------------


def test_time_trigger_accepts_weekday() -> None:
    trig = time(at="18:30:00", weekday=["mon", "tue", "wed", "thu", "fri"])
    assert trig.to_trigger() == {
        "trigger": "time",
        "at": "18:30:00",
        "weekday": ["mon", "tue", "wed", "thu", "fri"],
    }


def test_time_trigger_accepts_entity_ref_at() -> None:
    trig = time(at="input_datetime.wakeup")
    assert trig.to_trigger() == {"trigger": "time", "at": "input_datetime.wakeup"}


def test_decompile_time_trigger_weekday() -> None:
    body = {
        "trigger": "time",
        "at": "18:30:00",
        "weekday": ["mon", "tue", "wed", "thu", "fri"],
    }
    src = decompile_trigger(body)
    assert src is not None
    assert "raw_trigger" not in src
    assert src == "time(at='18:30:00', weekday=['mon', 'tue', 'wed', 'thu', 'fri'])"


def test_decompile_time_trigger_entity_ref_at() -> None:
    body = {"trigger": "time", "at": "input_datetime.wakeup"}
    src = decompile_trigger(body)
    assert src is not None
    assert "raw_trigger" not in src
    assert src == "time(at='input_datetime.wakeup')"
