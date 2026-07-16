"""Purpose-specific trigger/condition builder (DESIGN §5.4).

``on(type_string, target=..., behavior=..., for_=..., **options)`` and
``met(type_string, target=...)`` golden-compile to the stored 2026.7 shape
(``trigger``/``condition`` type string, ``target``, ``behavior``, ``options``).
Field shapes are pinned against ``fixtures/configs/automation_purpose_*.json``
(ground truth). All five target forms (entity/area/floor/label/device) are
covered. Type strings pass through unvalidated (vocabulary validation is
handled elsewhere, by the registry validator).
"""

from __future__ import annotations

from hassle import area, device_id, floor, label, met, minutes, on


def test_purpose_trigger_area_target_behavior_first() -> None:
    trig = on("motion.detected", target=area("office"), behavior="first")
    assert trig.to_trigger() == {
        "trigger": "motion.detected",
        "target": {"area_id": "office"},
        "behavior": "first",
    }


def test_purpose_trigger_entity_target_and_for() -> None:
    trig = on(
        "motion.detected",
        target="binary_sensor.hall_motion",
        for_=minutes(5),
    )
    assert trig.to_trigger() == {
        "trigger": "motion.detected",
        "target": {"entity_id": "binary_sensor.hall_motion"},
        "options": {"for": {"hours": 0, "minutes": 5, "seconds": 0}},
    }


def test_purpose_trigger_floor_target_behavior_each() -> None:
    trig = on("battery.became_low", target=floor("upstairs"), behavior="each")
    assert trig.to_trigger() == {
        "trigger": "battery.became_low",
        "target": {"floor_id": "upstairs"},
        "behavior": "each",
    }


def test_purpose_trigger_device_target() -> None:
    trig = on("vacuum.returned_to_dock", target=device_id("aaaabbbbccccdddd1111222233334444"))
    assert trig.to_trigger() == {
        "trigger": "vacuum.returned_to_dock",
        "target": {"device_id": "aaaabbbbccccdddd1111222233334444"},
    }


def test_purpose_trigger_label_target_behavior_all() -> None:
    trig = on("opening.opened", target=label("security"), behavior="all")
    assert trig.to_trigger() == {
        "trigger": "opening.opened",
        "target": {"label_id": "security"},
        "behavior": "all",
    }


def test_purpose_trigger_renamed_legacy_key_passes_through_unvalidated() -> None:
    # The vocabulary is instance data (validated by the registry validator);
    # this builder must not reject or rewrite a renamed/unknown type string.
    trig = on("battery.low", target="sensor.wireless_device_battery")
    assert trig.to_trigger() == {
        "trigger": "battery.low",
        "target": {"entity_id": "sensor.wireless_device_battery"},
    }


def test_purpose_condition_shape() -> None:
    cond = met("climate.is_target_temperature", target="climate.living_room")
    assert cond.to_condition() == {
        "condition": "climate.is_target_temperature",
        "target": {"entity_id": "climate.living_room"},
    }


def test_purpose_trigger_entity_target_accepts_plain_entity_id_string() -> None:
    # Entity refs: bare "domain.object_id" string is one of the five target forms
    # (the `e.<domain>.<object_id>` stub sugar is a later-milestone convenience
    # over the same primitive).
    trig = on("motion.detected", target="binary_sensor.hall_motion")
    assert trig.to_trigger()["target"] == {"entity_id": "binary_sensor.hall_motion"}


def test_purpose_trigger_no_target_or_behavior_omits_keys() -> None:
    trig = on("homeassistant.started")
    body = trig.to_trigger()
    assert "target" not in body
    assert "behavior" not in body
    assert "options" not in body


def test_purpose_trigger_extra_options_land_in_options_block() -> None:
    trig = on("motion.detected", target=area("office"), for_=minutes(1), custom_opt="x")
    assert trig.to_trigger()["options"] == {
        "for": {"hours": 0, "minutes": 1, "seconds": 0},
        "custom_opt": "x",
    }
