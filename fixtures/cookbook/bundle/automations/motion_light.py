"""Cookbook recipe 1: motion light, night-only.

The canonical DESIGN §10.2 example: motion turns the hallway light on at
night, off again 5 minutes later, gated by guest mode and a sun condition.
"""

from hassle import automation, delay, only_if, service, state, sun, when


@automation(id="cookbook_motion_light", alias="Cookbook: motion light", mode="restart")
def cookbook_motion_light():
    when(state("binary_sensor.hall_motion").to("on"))
    only_if(state("input_boolean.guest_mode").is_("off"))
    only_if(sun(after="sunset", after_offset="-00:30:00"))
    service("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    delay(minutes=5)
    service("light.turn_off", entity_id="light.hallway")
