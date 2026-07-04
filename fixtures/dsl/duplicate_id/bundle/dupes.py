"""Error case: two automations declare the same id -> bundle load must reject."""

from hassle import automation, service


@automation(id="shared", alias="First")
def first():
    service("light.turn_on", entity_id="light.a")


@automation(id="shared", alias="Second")
def second():
    service("light.turn_on", entity_id="light.b")
