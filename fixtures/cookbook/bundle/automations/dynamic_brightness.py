"""Cookbook recipe 23: template-based dynamic brightness.

The template expression builder (DESIGN §5.4) computes a brightness value
from the outdoor temperature at compile time -- HA evaluates the resulting
Jinja string at runtime, the simulator's template engine evaluates it too.
"""

from hassle import automation, service, state, when


@automation(id="cookbook_dynamic_brightness", alias="Cookbook: dynamic brightness")
def cookbook_dynamic_brightness():
    when(state("binary_sensor.living_room_motion").to("on"))
    service(
        "light.turn_on",
        entity_id="light.living_room",
        brightness_pct=(state("sensor.outdoor_temperature").value < 10) * 30
        + (state("sensor.outdoor_temperature").value >= 10) * 80,
    )
