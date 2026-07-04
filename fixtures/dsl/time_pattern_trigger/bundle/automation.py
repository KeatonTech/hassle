"""Golden case: `time_pattern` trigger builder.

Mirrors fixtures/configs/automation_time_pattern_trigger.json.
"""

from hassle import automation, service, time_pattern, when


@automation(id="time_pattern_trigger", alias="Time Pattern Trigger")
def time_pattern_trigger():
    when(time_pattern(hours="/1", minutes="0"))
    service("homeassistant.update_entity", target={"entity_id": "sensor.uptime"})
