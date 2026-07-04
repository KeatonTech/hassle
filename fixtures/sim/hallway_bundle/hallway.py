"""Example bundle for DESIGN §10.2 / MILESTONES M4 test 8.

`hall_light_on_motion` is the DESIGN §10.2 example verbatim (motion at night
turns the hallway light on at 60% and off again after 5 minutes, but never
during the day).

See `fixtures/sim/hallway_bundle_buggy/` for the seeded-logic-bug sibling used
by the M4 done-gate (a copy of `hall_light_on_motion` with its guest_mode
condition inverted): that bundle is deliberately kept out of this one so this
bundle's own test suite (test_sim_example_bundle.py) stays green -- the buggy
variant is exercised by test_sim_seeded_bug_caught.py, which asserts the
*intended* behavior and demonstrates it fails against the buggy bundle.
"""

from hassle import automation, delay, only_if, service, state, when


@automation(id="hall_light_on_motion", alias="Hallway: light on motion", mode="restart")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    only_if(state("input_boolean.guest_mode").is_("off"))
    service("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    delay(minutes=5)
    service("light.turn_off", entity_id="light.hallway")
