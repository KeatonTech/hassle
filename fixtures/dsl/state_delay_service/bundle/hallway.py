"""Golden case: state trigger + delay + service call.

Exercises the one end-to-end trigger builder (`state(...).to(...)`), the first
action primitive (`delay`), and a service-call action with kwargs.
"""

from hassle import automation, delay, service, state, when


@automation(id="hall_light_on_motion", alias="Hallway: light on motion", mode="restart")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    delay(minutes=5)
    service("light.turn_off", entity_id="light.hallway")
