"""Golden case: group-helper declarations for all twelve group flavors,
covering the three schema shapes (docs/ha-api-notes.md §38.1) -- base (name/
entities/hide_members), +all (binary_sensor/light/switch), +type (sensor).

Identity: there is no `id=`/`unique_id=` kwarg, mirroring template helpers
(docs/ha-api-notes.md §38.1) -- real HA's `group` config flow rejects an
unrecognized `unique_id` key outright. Identity is derived from `name`
(slugified): "Entryway Top" -> `group_cover:entryway_top`.

`hide_members`/`all` are always materialized explicitly in the compiled
options body (one canonical form, §38.1) -- never omitted just because they
equal their default.

Every `entities=` member below is a REAL entity id from
`fixtures/registry/home.json` (except `cover.bay_window_top`, which is this
bundle's OWN nested group's entity -- a real-world live example, §38.1:
a `cover.entryway_top` group containing `cover.bay_window_top`,
itself a group), so this fixture is also exercised by
`test_registry_validate.py::test_no_false_positives_on_golden_corpus`
(validation-clean, no `_DELIBERATELY_NOT_CLEAN` escape hatch needed).
"""

from hassle import (
    group_binary_sensor,
    group_button,
    group_cover,
    group_event,
    group_fan,
    group_light,
    group_lock,
    group_media_player,
    group_notify,
    group_sensor,
    group_switch,
    group_valve,
)

# Nested: "Bay Window Top" is declared first so "Entryway Top" can reference
# its produced entity (`cover.bay_window_top`) as a member -- a group whose
# members are themselves a group, a real-world live example (§38.1).
group_cover(
    name="Bay Window Top",
    entities=["cover.bedroom_blinds", "cover.living_room_blinds"],
)
group_cover(
    name="Entryway Top",
    entities=["cover.bay_window_top", "cover.garage_door"],
)
group_light(
    name="Downstairs Lights",
    entities=["light.hallway", "light.living_room", "light.kitchen"],
    all=True,
)
group_switch(
    name="Outdoor Switches",
    entities=["switch.garage_door_opener", "switch.office_monitor"],
    hide_members=True,
)
group_binary_sensor(
    name="Any Door Open",
    entities=["binary_sensor.door", "binary_sensor.back_door"],
)
group_sensor(
    name="Average Temp",
    entities=["sensor.living_room_temperature", "sensor.bedroom_temperature"],
    type="mean",
)
group_button(name="All Doorbells", entities=["button.restart"])
group_event(name="All Doorbell Events", entities=["event.doorbell"])
group_fan(name="All Fans", entities=["fan.bedroom", "fan.living_room"])
group_lock(name="All Locks", entities=["lock.front_door", "lock.back_door"])
group_media_player(
    name="Whole House Audio",
    entities=["media_player.living_room_speaker", "media_player.kitchen_speaker"],
)
group_notify(name="All Phones", entities=["notify.mobile_app_kai", "notify.mobile_app_spouse"])
# No `valve` entities exist in fixtures/registry/home.json at all (its
# registry snapshot has no valve domain coverage) -- validation only checks
# that a referenced entity id EXISTS, not that its domain matches the
# group's own flavor, so a real (if domain-mismatched) registry entity keeps
# this fixture validation-clean without needing to touch the shared registry
# fixture just for this one domain.
group_valve(name="Irrigation Zone A", entities=["cover.garage_door"])
