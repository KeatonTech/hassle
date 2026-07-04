"""Golden case: `persistent_notification` trigger builder.

Mirrors fixtures/configs/automation_persistent_notification_trigger.json.
"""

from hassle import automation, persistent_notification, service, when


@automation(id="persistent_notification_trigger", alias="Persistent Notification Trigger")
def persistent_notification_trigger():
    when(persistent_notification(notification_id="test_notification"))
    service("persistent_notification.dismiss", notification_id="test_notification")
