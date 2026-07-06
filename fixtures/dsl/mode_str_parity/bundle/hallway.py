"""Golden case: plain string `mode=`/`max_exceeded=` (`ux/dsl-ergonomics`, item 2) --
the pre-existing behavior, unchanged. Paired with `mode_enum_parity/`'s `Mode`/
`MaxExceeded` enum form to prove compile parity: both must produce byte-identical IR.
"""

from hassle import automation, service, state, when


@automation(
    id="hall_light_on_motion",
    alias="Hallway: light on motion",
    mode="restart",
    max_exceeded="silent",
)
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", entity_id="light.hallway")
