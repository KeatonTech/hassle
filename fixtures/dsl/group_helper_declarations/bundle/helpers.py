"""Golden case: group-helper declarations (M21) for all twelve group flavors,
covering the three schema shapes (docs/ha-api-notes.md §38.1) -- base (name/
entities/hide_members), +all (binary_sensor/light/switch), +type (sensor).

Identity: there is no `id=`/`unique_id=` kwarg, mirroring template helpers
(docs/ha-api-notes.md §38.1) -- real HA's `group` config flow rejects an
unrecognized `unique_id` key outright. Identity is derived from `name`
(slugified): "Entryway Top" -> `group_cover:entryway_top`.

`hide_members`/`all` are always materialized explicitly in the compiled
options body (one canonical form, §38.1) -- never omitted just because they
equal their default.
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

group_cover(
    name="Entryway Top",
    # Groups may nest: this cover group contains another group's own entity.
    entities=["cover.bay_window_top", "cover.garage_door"],
)
group_light(
    name="Downstairs Lights",
    entities=["light.hallway", "light.living_room", "light.kitchen"],
    all=True,
)
group_switch(
    name="Outdoor Switches",
    entities=["switch.porch", "switch.garden"],
    hide_members=True,
)
group_binary_sensor(
    name="Any Door Open",
    entities=["binary_sensor.front_door", "binary_sensor.back_door"],
)
group_sensor(
    name="Average Temp",
    entities=["sensor.living_room_temp", "sensor.bedroom_temp"],
    type="mean",
)
group_button(name="All Doorbells", entities=["button.front_doorbell"])
group_event(name="All Doorbell Events", entities=["event.front_doorbell"])
group_fan(name="All Fans", entities=["fan.living_room", "fan.bedroom"])
group_lock(name="All Locks", entities=["lock.front_door", "lock.back_door"])
group_media_player(
    name="Whole House Audio", entities=["media_player.living_room", "media_player.kitchen"]
)
group_notify(name="All Phones", entities=["notify.phone_a", "notify.phone_b"])
group_valve(name="All Valves", entities=["valve.irrigation_front", "valve.irrigation_back"])
