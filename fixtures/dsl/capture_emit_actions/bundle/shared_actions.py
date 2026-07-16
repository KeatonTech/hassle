"""Shared capture/emit helper library (DESIGN §5.6-style `lib/` pattern).

Demonstrates the public capture seam: a `lib/` builder captures one block
of actions once with `capture_actions()`
and splices the SAME captured bodies into more than one place with
`emit_actions(...)` -- here, a single "turn off the porch light" action
reused across two `choose()` branches keyed on which door opened.
"""

from hassle import capture_actions, choose, emit_actions, service, state


def porch_off_on_either_door():
    with capture_actions() as porch_off:
        service("light.turn_off", entity_id="light.porch")

    with choose() as c:
        with c.when_(state("binary_sensor.front_door").is_("open")):
            emit_actions(porch_off)
        with c.when_(state("binary_sensor.back_door").is_("open")):
            emit_actions(porch_off)
