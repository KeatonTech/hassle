"""Golden case: purpose-specific trigger, entity target, `for_=` duration.

Mirrors fixtures/configs/automation_purpose_trigger_entity_target.json.
"""

from hassle import automation, minutes, on, service, when


@automation(id="purpose_trigger_entity_for", alias="Purpose Trigger Entity Target")
def purpose_trigger_entity_for():
    when(on("motion.detected", target="binary_sensor.hall_motion", for_=minutes(5)))
    service("light.turn_on", target={"entity_id": "light.hallway"})
