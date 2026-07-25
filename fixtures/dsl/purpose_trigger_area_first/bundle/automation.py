"""Golden case: purpose-specific trigger, area target, behavior=first.

Mirrors fixtures/configs/automation_purpose_trigger_area_behavior_first.json.
"""

from hassle import area, automation, on, service, when


@automation(id="purpose_trigger_area_first", alias="Purpose Trigger Area Behavior First")
def purpose_trigger_area_first():
    when(on("motion.detected", target=area("office"), behavior="first"))
    service("light.turn_on", target={"entity_id": "light.office_ceiling"})
