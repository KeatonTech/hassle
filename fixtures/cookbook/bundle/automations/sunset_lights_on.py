"""Cookbook recipe 15: sunset lights on.

A `sun` trigger (not a condition, this time) turns the porch light on at
dusk.
"""

from hassle import automation, service, sun, when


@automation(id="cookbook_sunset_lights_on", alias="Cookbook: sunset lights on")
def cookbook_sunset_lights_on():
    when(sun(event="sunset"))
    service("light.turn_on", target={"entity_id": "light.porch"})
