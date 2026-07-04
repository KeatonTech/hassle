"""Golden case: one macro used by two automations (M1 test 2).

Both automations' action lists must contain the macro's expansion.
"""

from notify import notify_adults

from hassle import automation, service, state, when


@automation(id="front_door", alias="Front door opened")
def front_door():
    when(state("binary_sensor.front_door").to("open"))
    notify_adults("Front door opened")


@automation(id="back_door", alias="Back door opened")
def back_door():
    when(state("binary_sensor.back_door").to("open"))
    notify_adults("Back door opened")
    service("light.turn_on", entity_id="light.porch")
