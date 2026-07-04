"""M1 triggers+conditions workstream — unit tests for the classic builder family.

Exercises the trigger/condition builders directly (not through a full bundle
compile) against the exact field shapes captured in the fixture corpus
(``fixtures/configs/automation_*_trigger.json`` and
``fixtures/configs/automation_condition_*.json`` are ground truth for each type).
The golden-pair tests (``test_dsl_golden_pairs.py``, driven by ``fixtures/dsl/``)
cover the full compile pipeline; these tests pin the builder-level contract so a
failure here points straight at the offending builder.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from hassle import (
    all_of,
    any_of,
    calendar,
    device,
    event,
    geo_location,
    homeassistant_shutdown,
    homeassistant_start,
    hours,
    minutes,
    mqtt,
    not_,
    numeric_state,
    persistent_notification,
    seconds,
    sun,
    tag,
    template,
    time,
    time_pattern,
    trigger_condition,
    webhook,
    zone,
)
from hassle_core.compiler import CompileTimeBranchError
from hassle_core.compiler.builders import state


# ---------------------------------------------------------------------------
# Classic trigger builders — field shapes pinned against the fixture corpus.
# ---------------------------------------------------------------------------
def test_numeric_state_trigger_shape() -> None:
    trig = numeric_state("sensor.outdoor_temperature", above=25)
    assert trig.to_trigger() == {
        "trigger": "numeric_state",
        "entity_id": "sensor.outdoor_temperature",
        "above": 25,
    }


def test_numeric_state_trigger_below_and_for() -> None:
    trig = numeric_state("sensor.humidity", below=30, for_=minutes(5))
    body = trig.to_trigger()
    assert body["below"] == 30
    assert body["for"] == {"hours": 0, "minutes": 5, "seconds": 0}


def test_time_trigger_shape() -> None:
    assert time(at="07:00:00").to_trigger() == {"trigger": "time", "at": "07:00:00"}


def test_time_pattern_trigger_shape() -> None:
    trig = time_pattern(hours="/1", minutes="0")
    assert trig.to_trigger() == {"trigger": "time_pattern", "hours": "/1", "minutes": "0"}


def test_sun_trigger_shape() -> None:
    trig = sun(event="sunset", offset="-00:30:00")
    assert trig.to_trigger() == {"trigger": "sun", "event": "sunset", "offset": "-00:30:00"}


def test_event_trigger_shape() -> None:
    trig = event("custom_event", event_data={"action": "test"})
    assert trig.to_trigger() == {
        "trigger": "event",
        "event_type": "custom_event",
        "event_data": {"action": "test"},
    }


def test_zone_trigger_shape() -> None:
    trig = zone("device_tracker.john", zone="zone.work", event="enter")
    assert trig.to_trigger() == {
        "trigger": "zone",
        "entity_id": "device_tracker.john",
        "zone": "zone.work",
        "event": "enter",
    }


def test_template_trigger_is_raw_jinja_string() -> None:
    trig = template("{{ state_attr('light.hallway', 'brightness') > 100 }}")
    assert trig.to_trigger() == {
        "trigger": "template",
        "value_template": "{{ state_attr('light.hallway', 'brightness') > 100 }}",
    }


def test_webhook_trigger_shape() -> None:
    assert webhook("abc123def456").to_trigger() == {
        "trigger": "webhook",
        "webhook_id": "abc123def456",
    }


def test_mqtt_trigger_shape() -> None:
    trig = mqtt("home/bedroom/motion", payload="on")
    assert trig.to_trigger() == {
        "trigger": "mqtt",
        "topic": "home/bedroom/motion",
        "payload": "on",
    }


def test_calendar_trigger_shape() -> None:
    trig = calendar("calendar.holidays", event="start")
    assert trig.to_trigger() == {
        "trigger": "calendar",
        "entity_id": "calendar.holidays",
        "event": "start",
    }


def test_persistent_notification_trigger_shape() -> None:
    trig = persistent_notification(notification_id="test_notification")
    assert trig.to_trigger() == {
        "trigger": "persistent_notification",
        "notification_id": "test_notification",
    }


def test_tag_trigger_shape() -> None:
    assert tag("tag_abc123").to_trigger() == {"trigger": "tag", "tag_id": "tag_abc123"}


def test_geo_location_trigger_shape() -> None:
    trig = geo_location(source="nsw_rural_fire_service_feed", zone="zone.home", event="enter")
    assert trig.to_trigger() == {
        "trigger": "geo_location",
        "source": "nsw_rural_fire_service_feed",
        "zone": "zone.home",
        "event": "enter",
    }


def test_homeassistant_start_trigger_shape() -> None:
    assert homeassistant_start().to_trigger() == {"trigger": "homeassistant", "event": "start"}


def test_homeassistant_shutdown_trigger_shape() -> None:
    assert homeassistant_shutdown().to_trigger() == {
        "trigger": "homeassistant",
        "event": "shutdown",
    }


def test_device_trigger_is_raw_passthrough() -> None:
    trig = device(
        {
            "device_id": "1234567890abcdef",
            "domain": "zwave",
            "type": "scene_activation",
            "subtype": "scene_001",
        }
    )
    assert trig.to_trigger() == {
        "trigger": "device",
        "device_id": "1234567890abcdef",
        "domain": "zwave",
        "type": "scene_activation",
        "subtype": "scene_001",
    }


# ---------------------------------------------------------------------------
# Common trigger options: for_, id=, enabled=, variables=
# ---------------------------------------------------------------------------
def test_for_accepts_timedelta() -> None:
    trig = numeric_state("sensor.x", above=1, for_=timedelta(hours=1, minutes=2, seconds=3))
    assert trig.to_trigger()["for"] == {"hours": 1, "minutes": 2, "seconds": 3}


def test_for_accepts_string() -> None:
    trig = numeric_state("sensor.x", above=1, for_="01:02:03")
    assert trig.to_trigger()["for"] == {"hours": 1, "minutes": 2, "seconds": 3}


def test_for_accepts_dict() -> None:
    trig = numeric_state("sensor.x", above=1, for_={"minutes": 5})
    assert trig.to_trigger()["for"] == {"hours": 0, "minutes": 5, "seconds": 0}


def test_duration_helpers() -> None:
    assert hours(2) == {"hours": 2, "minutes": 0, "seconds": 0}
    assert minutes(5) == {"hours": 0, "minutes": 5, "seconds": 0}
    assert seconds(30) == {"hours": 0, "minutes": 0, "seconds": 30}


def test_trigger_id_option() -> None:
    trig = numeric_state("sensor.x", above=1).with_options(id="motion_trigger")
    assert trig.to_trigger()["id"] == "motion_trigger"


def test_trigger_enabled_option() -> None:
    trig = numeric_state("sensor.x", above=1).with_options(enabled=False)
    assert trig.to_trigger()["enabled"] is False


def test_trigger_variables_option() -> None:
    trig = numeric_state("sensor.x", above=1).with_options(variables={"a": 1})
    assert trig.to_trigger()["variables"] == {"a": 1}


# ---------------------------------------------------------------------------
# Classic condition builders
# ---------------------------------------------------------------------------
def test_state_condition_shape() -> None:
    cond = state("input_boolean.enable_automation").is_("on")
    assert cond.to_condition() == {
        "condition": "state",
        "entity_id": "input_boolean.enable_automation",
        "state": "on",
    }


def test_numeric_state_condition_shape() -> None:
    cond = numeric_state("sensor.humidity", above=60)
    assert cond.to_condition() == {
        "condition": "numeric_state",
        "entity_id": "sensor.humidity",
        "above": 60,
    }


def test_sun_condition_shape() -> None:
    cond = sun(after="sunset", after_offset="-01:00:00")
    assert cond.to_condition() == {
        "condition": "sun",
        "after": "sunset",
        "after_offset": "-01:00:00",
    }


def test_time_condition_shape() -> None:
    cond = time(after="22:00:00", before="06:00:00", weekday=["mon", "tue", "wed", "thu", "fri"])
    assert cond.to_condition() == {
        "condition": "time",
        "after": "22:00:00",
        "before": "06:00:00",
        "weekday": ["mon", "tue", "wed", "thu", "fri"],
    }


def test_zone_condition_shape() -> None:
    cond = zone("device_tracker.john", zone="zone.work")
    assert cond.to_condition() == {
        "condition": "zone",
        "entity_id": "device_tracker.john",
        "zone": "zone.work",
    }


def test_template_condition_shape() -> None:
    cond = template("{{ now().hour >= 6 and now().hour < 22 }}")
    assert cond.to_condition() == {
        "condition": "template",
        "value_template": "{{ now().hour >= 6 and now().hour < 22 }}",
    }


def test_trigger_condition_shape() -> None:
    cond = trigger_condition("motion_trigger")
    assert cond.to_condition() == {"condition": "trigger", "id": "motion_trigger"}


# ---------------------------------------------------------------------------
# Combinators
# ---------------------------------------------------------------------------
def test_all_of_compiles_to_and() -> None:
    cond = all_of(
        state("input_boolean.mode").is_("on"),
        any_of(
            state("light.bedroom").is_("on"),
            state("light.living_room").is_("on"),
        ),
        not_(state("input_boolean.away").is_("on")),
    )
    assert cond.to_condition() == {
        "condition": "and",
        "conditions": [
            {"condition": "state", "entity_id": "input_boolean.mode", "state": "on"},
            {
                "condition": "or",
                "conditions": [
                    {"condition": "state", "entity_id": "light.bedroom", "state": "on"},
                    {"condition": "state", "entity_id": "light.living_room", "state": "on"},
                ],
            },
            {
                "condition": "not",
                "conditions": [
                    {"condition": "state", "entity_id": "input_boolean.away", "state": "on"}
                ],
            },
        ],
    }


def test_any_of_compiles_to_or() -> None:
    cond = any_of(state("a").is_("on"), state("b").is_("on"))
    assert cond.to_condition()["condition"] == "or"


def test_not_compiles_to_not() -> None:
    cond = not_(state("a").is_("on"))
    assert cond.to_condition() == {
        "condition": "not",
        "conditions": [{"condition": "state", "entity_id": "a", "state": "on"}],
    }


def test_combinator_bool_trap() -> None:
    # A combinator must keep the CompileTimeBranchError __bool__ trap (M1 scope
    # item: "extend the core's pattern; add a trap test for a combinator").
    combo = any_of(state("a").is_("on"), state("b").is_("on"))
    with pytest.raises(CompileTimeBranchError):
        bool(combo)


def test_not_bool_trap() -> None:
    combo = not_(state("a").is_("on"))
    with pytest.raises(CompileTimeBranchError):
        if combo:  # pragma: no branch - must raise before evaluating
            pass
