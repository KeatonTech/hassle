"""Hallway automations.

Hand-written comments and blank lines here must survive a splice untouched.
"""

from hassle import automation, service, when
from hassle.registry import entities as e


# Turns on the hallway light on motion. Do not remove this comment.
@automation(id="hall_light_on_motion", alias="Hallway: light on motion")
def hall_light_on_motion():
    when(state_is_on())
    service("light.turn_on", target={"entity_id": "light.hallway"})


def state_is_on():
    # a helper local to this file -- not a top-level hassle object
    from hassle import state

    return state(e.binary_sensor.hall_motion).to("on")


@automation(id="middle_automation", alias="Middle: will be spliced")
def middle_automation():
    when(state_is_on())
    service("light.turn_off", target={"entity_id": "light.hallway"})


# Trailing comment on the porch light automation.
@automation(id="porch_light_on_motion", alias="Porch: light on motion")
def porch_light_on_motion():
    when(state_is_on())
    service("light.turn_on", target={"entity_id": "light.porch"})
