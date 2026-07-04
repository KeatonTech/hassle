"""Golden case: `sun` trigger builder.

Mirrors fixtures/configs/automation_sun_trigger.json.
"""

from hassle import automation, service, sun, when


@automation(id="sun_trigger", alias="Sun Trigger")
def sun_trigger():
    when(sun(event="sunset", offset="-00:30:00"))
    service("light.turn_on", target={"entity_id": "light.porch"}, brightness_pct=75)
