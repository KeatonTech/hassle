"""Golden case: raw_trigger/raw_condition/raw_action passthrough (DESIGN §5.8).

The raw action is authored in legacy `service:` form to prove the containing
object's whole-body `normalize_ha` pass rewrites it to `action:`, exactly as
HA itself would on storage (docs/internals/ha-api-notes.md §10.1) -- the raw builders
themselves do not touch the dict.
"""

from hassle import automation, raw_action, raw_condition, raw_trigger


@automation(id="weird_device_trigger", alias="Weird device trigger thing")
def weird_device_trigger():
    raw_trigger({"platform": "device", "device_id": "abc123", "type": "turned_on"})
    raw_condition({"condition": "device", "device_id": "abc123", "type": "is_on"})
    raw_action({"service": "light.turn_on", "entity_id": "light.hallway"})
