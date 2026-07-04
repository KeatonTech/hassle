"""Golden case: `event` trigger builder.

Mirrors fixtures/configs/automation_event_trigger.json.
"""

from hassle import automation, event, service, when


@automation(id="event_trigger", alias="Event Trigger")
def event_trigger():
    when(event("custom_event", event_data={"action": "test"}))
    service("notify.mobile_app", message="Custom event triggered")
