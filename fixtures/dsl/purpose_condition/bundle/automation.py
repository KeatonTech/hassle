"""Golden case: classic state trigger + purpose-specific condition.

Mirrors fixtures/configs/automation_purpose_condition.json.
"""

from hassle import automation, met, only_if, service, state, when


@automation(id="purpose_condition", alias="Purpose-Specific Condition")
def purpose_condition():
    when(state("binary_sensor.living_room_motion").to("on"))
    only_if(met("climate.is_target_temperature", target="climate.living_room"))
    service("light.turn_on", target={"entity_id": "light.living_room"})
