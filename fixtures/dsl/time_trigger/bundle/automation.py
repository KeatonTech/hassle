"""Golden case: `time` trigger builder.

Mirrors fixtures/configs/automation_time_trigger.json.
"""

from hassle import automation, service, time, when


@automation(id="time_trigger", alias="Time Trigger")
def time_trigger():
    when(time(at="07:00:00"))
    service("light.turn_on", target={"entity_id": "light.bedroom"})
