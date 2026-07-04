"""Golden case: the smallest useful automation — alias + one service call."""

from hassle import automation, service


@automation(alias="Minimal")
def minimal():
    service("light.turn_on", entity_id="light.hallway")
