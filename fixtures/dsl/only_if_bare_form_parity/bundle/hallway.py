"""Golden case: bare `only_if(...)` call form (`ux/dsl-ergonomics`, item 1) --
the pre-existing, unchanged behavior. Paired with `only_if_block_form/`'s
`with only_if(...):` form to prove compile parity: both must produce
byte-identical IR (same precedent as `triggers_in_decorator/` vs.
`state_delay_service/`).
"""

from hassle import automation, delay, only_if, service, state, sun, when


@automation(id="hall_light_on_motion", alias="Hallway: light on motion", mode="restart")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    only_if(
        state("input_boolean.guest_mode").is_("off"),
        sun(after="sunset", after_offset="-00:30"),
    )
    service("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    delay(minutes=5)
    service("light.turn_off", entity_id="light.hallway")
