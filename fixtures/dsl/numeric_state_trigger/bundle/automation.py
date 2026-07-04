"""Golden case: `numeric_state` trigger builder.

Mirrors fixtures/configs/automation_numeric_state_trigger.json.
"""

from hassle import automation, numeric_state, service, when


@automation(id="numeric_state_trigger", alias="Numeric State Trigger")
def numeric_state_trigger():
    when(numeric_state("sensor.outdoor_temperature", above=25))
    service(
        "climate.set_temperature",
        target={"entity_id": "climate.living_room"},
        temperature=20,
    )
