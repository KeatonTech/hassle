"""M4 done-gate fixture: a deliberately seeded logic bug.

Copy of `fixtures/sim/hallway_bundle/hallway.py`'s `hall_light_on_motion`
(same day/night `sun` gate) with the guest_mode condition inverted --
`.is_("on")` instead of `.is_("off")`. The intent (unchanged from the clean
bundle) is "turn the light on when motion is detected, unless guest mode is
on"; this buggy version does the opposite: it fires exactly when guest mode
is on, and stays dark when guest mode is off. `test_sim_seeded_bug_caught.py`
writes a test encoding the *intended* behavior and demonstrates it fails
against this bundle -- proving a seeded logic bug is actually caught by the
simulator, not silently passed.
"""

from hassle import automation, delay, only_if, service, state, sun, when


@automation(id="hall_light_on_motion", alias="Hallway: light on motion (buggy)", mode="restart")
def hall_light_on_motion():
    when(state("binary_sensor.hall_motion").to("on"))
    only_if(state("input_boolean.guest_mode").is_("on"))  # BUG: should be "off"
    only_if(sun(after="sunset", after_offset="-00:30:00"))
    service("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    delay(minutes=5)
    service("light.turn_off", entity_id="light.hallway")
