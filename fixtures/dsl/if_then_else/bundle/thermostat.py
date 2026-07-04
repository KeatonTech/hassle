"""Golden case: if_then / else_then -> HA's `if`/`then`/`else` action.

Matches the shape of fixtures/configs/automation_if_then_else.json (a state
trigger, an `if` with a nested service call, and an else branch).
"""

from hassle import automation, else_then, if_then, service, state, when


@automation(id="thermostat_if_then", alias="Thermostat if/then/else")
def thermostat_if_then():
    when(state("sensor.temperature").to("above_25"))
    with if_then(state("sensor.temperature").is_("above_25")):
        service(
            "climate.set_temperature",
            target={"entity_id": "climate.living_room"},
            temperature=20,
        )
    with else_then():
        service(
            "climate.set_temperature",
            target={"entity_id": "climate.living_room"},
            temperature=22,
        )
