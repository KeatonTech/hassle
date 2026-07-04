"""Golden case: `calendar` trigger builder.

Mirrors fixtures/configs/automation_calendar_trigger.json.
"""

from hassle import automation, calendar, service, when


@automation(id="calendar_trigger", alias="Calendar Trigger")
def calendar_trigger():
    when(calendar("calendar.holidays", event="start"))
    service("notify.mobile_app", message="Calendar event starting")
