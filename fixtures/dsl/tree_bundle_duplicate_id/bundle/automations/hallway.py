"""Error case (M7.1): duplicate id declared in two different subdirectory
files -- the message must show both relative paths
(automations/hallway.py and scripts/night_mode.py)."""

from hassle import automation, service


@automation(id="shared", alias="First")
def first():
    service("light.turn_on", entity_id="light.a")
