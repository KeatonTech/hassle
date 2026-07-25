"""Golden case: `triggers=` decorator metadata -- the canonical form for a
`state()` trigger, side by side with `fixtures/dsl/state_delay_service/`
(the equivalent `when()` form) to prove compile parity: both must produce
byte-identical IR.
"""

from hassle import automation, delay, service, state


@automation(
    id="hall_light_on_motion",
    alias="Hallway: light on motion",
    mode="restart",
    triggers=[state("binary_sensor.hall_motion").to("on")],
)
def hall_light_on_motion():
    service("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    delay(minutes=5)
    service("light.turn_off", entity_id="light.hallway")
