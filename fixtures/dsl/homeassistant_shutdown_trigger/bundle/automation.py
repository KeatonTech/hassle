"""Golden case: `homeassistant_shutdown` trigger builder.

Mirrors fixtures/configs/automation_homeassistant_shutdown_trigger.json.
"""

from hassle import automation, homeassistant_shutdown, service, when


@automation(id="homeassistant_shutdown_trigger", alias="HA Shutdown Trigger")
def homeassistant_shutdown_trigger():
    when(homeassistant_shutdown())
    service("light.turn_off", target={"entity_id": "light.all"})
