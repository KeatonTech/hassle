"""Golden case: `capture_actions()`/`emit_actions(...)` (task #30 public
capture seam) -- one captured action list spliced into two `choose()`
branches inside a single automation.
"""

from shared_actions import porch_off_on_either_door

from hassle import automation, state, when


@automation(id="doors_porch_light", alias="Doors: porch light off")
def doors_porch_light():
    when(state("binary_sensor.front_door").to("open"))
    porch_off_on_either_door()
