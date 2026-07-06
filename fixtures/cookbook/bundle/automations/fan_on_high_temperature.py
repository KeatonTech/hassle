"""Cookbook recipe 11: fan on high temperature.

`numeric_state` crossing UP through a threshold turns the bedroom fan on.
"""

from hassle import automation, numeric_state, service, when


@automation(id="cookbook_fan_on_high_temp", alias="Cookbook: fan on high temp")
def cookbook_fan_on_high_temp():
    when(numeric_state("sensor.outdoor_temperature", above=28))
    service("fan.turn_on", target={"entity_id": "fan.bedroom"})
