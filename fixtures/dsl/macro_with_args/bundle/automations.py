"""Golden case: macro called with compile-time args (positional and keyword)."""

from lib import flash_light

from hassle import automation, state, when


@automation(id="alert", alias="Alert flash")
def alert():
    when(state("binary_sensor.alarm").to("on"))
    flash_light("light.hallway", times=3)
