"""Golden case: `zone` trigger builder.

Mirrors fixtures/configs/automation_zone_trigger.json.
"""

from hassle import automation, service, when, zone


@automation(id="zone_trigger", alias="Zone Trigger")
def zone_trigger():
    when(zone("device_tracker.john", zone="zone.work", event="enter"))
    service("light.turn_on", target={"entity_id": "light.office"})
