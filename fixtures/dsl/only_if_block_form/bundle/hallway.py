"""Golden case: `with only_if(...):` block form (`ux/dsl-ergonomics`, item 1) --
the NEW context-manager usage. Paired with `only_if_bare_form_parity/`'s bare
call to prove compile parity: both must produce byte-identical IR. Every
action lives inside the block (the "all actions must be inside" invariant).
"""

from hassle import automation, delay, only_if, service, state, sun, when


@automation(id="hall_light_on_motion", alias="Hallway: light on motion", mode="restart")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    with only_if(
        state("input_boolean.guest_mode").is_("off"),
        sun(after="sunset", after_offset="-00:30"),
    ):
        service("light.turn_on", entity_id="light.hallway", brightness_pct=60)
        delay(minutes=5)
        service("light.turn_off", entity_id="light.hallway")
