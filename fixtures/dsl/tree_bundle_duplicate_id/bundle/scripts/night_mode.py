"""Error case: declares the same id as automations/hallway.py.
Duplicate-id detection must span the whole tree, not just one dir."""

from hassle import automation, service


@automation(id="shared", alias="Second")
def second():
    service("light.turn_on", entity_id="light.b")
