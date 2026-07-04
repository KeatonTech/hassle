"""Golden case: choose() with when_() branches + default().

Matches fixtures/configs/automation_choose_action.json's stored shape: a list
of {conditions, sequence} branches plus a trailing `default` sequence.
"""

from hassle import automation, choose, service, state, when


@automation(id="bedroom_choose", alias="Bedroom choose")
def bedroom_choose():
    when(state("binary_sensor.motion").to("on"))
    with choose() as c:
        with c.when_(state("light.bedroom").is_("off")):
            service(
                "light.turn_on",
                target={"entity_id": "light.bedroom"},
                brightness=255,
            )
        with c.when_(state("light.bedroom").is_("on")):
            service("light.turn_off", target={"entity_id": "light.bedroom"})
        with c.default():
            service("light.toggle", target={"entity_id": "light.bedroom"})
