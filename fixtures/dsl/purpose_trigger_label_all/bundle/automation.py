"""Golden case: purpose-specific trigger, label target, behavior=all (M1 test 10).

Mirrors fixtures/configs/automation_purpose_trigger_label_behavior_all.json.
"""

from hassle import automation, label, on, service, when


@automation(id="purpose_trigger_label_all", alias="Purpose Trigger Label Behavior All")
def purpose_trigger_label_all():
    when(on("opening.opened", target=label("security"), behavior="all"))
    service("siren.turn_on", target={"entity_id": "siren.garage_alarm"})
