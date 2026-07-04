"""Golden case: `webhook` trigger builder.

Mirrors fixtures/configs/automation_webhook_trigger.json.
"""

from hassle import automation, service, webhook, when


@automation(id="webhook_trigger", alias="Webhook Trigger")
def webhook_trigger():
    when(webhook("abc123def456"))
    service("light.turn_on", target={"entity_id": "light.bedroom"})
