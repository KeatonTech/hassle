"""Golden case: repeat_for_each(items) -> HA's `repeat.for_each` action."""

from hassle import automation, repeat_for_each, service, state, when


@automation(id="lights_repeat_for_each", alias="Lights repeat for_each")
def lights_repeat_for_each():
    when(state("input_text.entities").to("changed"))
    with repeat_for_each(["light.bedroom", "light.kitchen", "light.hallway"]):
        service("light.turn_on", target={"entity_id": "{{ repeat.item }}"})
