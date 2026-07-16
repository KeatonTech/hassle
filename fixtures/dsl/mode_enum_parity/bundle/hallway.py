"""Golden case: `Mode`/`MaxExceeded` StrEnum form --
`StrEnum` IS a `str` subclass, so passing a member compiles byte-identical to the
equivalent plain string. Paired with `mode_str_parity/`'s plain-string form to
prove compile parity.
"""

from hassle import MaxExceeded, Mode, automation, service, state, when


@automation(
    id="hall_light_on_motion",
    alias="Hallway: light on motion",
    mode=Mode.RESTART,
    max_exceeded=MaxExceeded.SILENT,
)
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    service("light.turn_on", entity_id="light.hallway")
