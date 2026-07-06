"""Cookbook recipe 3: thermostat schedule.

A daily time trigger sets the living-room thermostat back for the night.
"""

from hassle import automation, service, time, when


@automation(id="cookbook_thermostat_schedule", alias="Cookbook: night setback")
def cookbook_thermostat_schedule():
    when(time(at="22:00:00"))
    service(
        "climate.set_temperature",
        target={"entity_id": "climate.living_room"},
        temperature=18,
    )
