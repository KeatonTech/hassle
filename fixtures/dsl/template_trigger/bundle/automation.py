"""Golden case: `template` trigger builder (raw Jinja string).

Mirrors fixtures/configs/automation_template_trigger.json.
"""

from hassle import automation, service, template, when


@automation(id="template_trigger", alias="Template Trigger")
def template_trigger():
    when(template("{{ state_attr('light.hallway', 'brightness') > 100 }}"))
    service("automation.turn_off", target={"entity_id": "automation.template_trigger"})
