"""Golden case: `mqtt` trigger builder.

Mirrors fixtures/configs/automation_mqtt_trigger.json.
"""

from hassle import automation, mqtt, service, when


@automation(id="mqtt_trigger", alias="MQTT Trigger")
def mqtt_trigger():
    when(mqtt("home/bedroom/motion", payload="on"))
    service("switch.turn_on", target={"entity_id": "switch.bedroom_fan"})
