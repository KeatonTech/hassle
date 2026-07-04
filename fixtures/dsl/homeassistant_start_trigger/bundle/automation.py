"""Golden case: `homeassistant_start` trigger builder.

Mirrors fixtures/configs/automation_homeassistant_start_trigger.json.
"""

from hassle import automation, homeassistant_start, service, when


@automation(id="homeassistant_start_trigger", alias="HA Start Trigger")
def homeassistant_start_trigger():
    when(homeassistant_start())
    service("automation.reload")
