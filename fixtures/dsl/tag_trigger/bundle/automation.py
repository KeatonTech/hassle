"""Golden case: `tag` trigger builder.

Mirrors fixtures/configs/automation_tag_trigger.json.
"""

from hassle import automation, service, tag, when


@automation(id="tag_trigger", alias="Tag Trigger")
def tag_trigger():
    when(tag("tag_abc123"))
    service("light.turn_on", target={"entity_id": "light.entryway"})
